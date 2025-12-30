import streamlit as st
import zipfile
import xml.etree.ElementTree as ET
import re
from pypdf import PdfReader
from io import BytesIO
import google.generativeai as genai

# --- Sayfa Ayarları ---
st.set_page_config(
    page_title="Hukuk Asistanı Pro",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CSS Tasarım ---
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stTextInput>div>div>input { border-radius: 8px; }
    .kanun-kutusu { 
        background-color: #ffffff; 
        padding: 20px; 
        border-left: 5px solid #b71c1c; 
        border-radius: 5px; 
        box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        margin-bottom: 15px;
        white-space: pre-wrap;
    }
    .ictihat-kutusu {
        background-color: #ffffff;
        padding: 20px;
        border-left: 5px solid #0d47a1;
        border-radius: 5px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        margin-bottom: 15px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- YARDIMCI FONKSİYONLAR ---

def parse_udf(file_bytes):
    try:
        with zipfile.ZipFile(file_bytes) as z:
            if 'content.xml' in z.namelist():
                with z.open('content.xml') as f:
                    tree = ET.parse(f)
                    root = tree.getroot()
                    text_content = [elem.text.strip() for elem in root.iter() if elem.text]
                    return " ".join(text_content)
            return "HATA: UDF dosyası bozuk veya content.xml bulunamadı."
    except Exception as e:
        return f"HATA: {str(e)}"

def parse_pdf(file_bytes):
    try:
        reader = PdfReader(file_bytes)
        text = "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])
        if not text.strip():
            return "UYARI: PDF metin içermiyor. Taranmış resim formatında olabilir."
        return text
    except Exception as e:
        return f"HATA: {str(e)}"

def extract_metadata(text):
    if not isinstance(text, str) or text.startswith("HATA") or text.startswith("UYARI"):
        return {"mahkeme": "-", "esas": "-", "karar": "-", "tarih": "-"}
    
    esas = re.search(r"(?i)Esas\s*No\s*[:\-]?\s*(\d{4}/\d+)", text)
    karar = re.search(r"(?i)Karar\s*No\s*[:\-]?\s*(\d{4}/\d+)", text)
    tarih = re.search(r"(\d{1,2}[./]\d{1,2}[./]\d{4})", text)
    
    mahkeme = "Tespit Edilemedi"
    for line in text.split('\n')[:40]:
        clean = line.strip()
        if ("MAHKEMESİ" in clean.upper() or "DAİRESİ" in clean.upper()) and len(clean) > 5:
            mahkeme = clean
            break
            
    return {
        "mahkeme": mahkeme,
        "esas": esas.group(1) if esas else "Bulunamadı",
        "karar": karar.group(1) if karar else "Bulunamadı",
        "tarih": tarih.group(1) if tarih else "Bulunamadı"
    }

# --- AI FONKSİYONU (OTOMATİK MODEL BULUCU) ---
def get_gemini_response(prompt, api_key):
    if not api_key: return "Lütfen API Anahtarı giriniz."
    
    try:
        genai.configure(api_key=api_key)
        
        # 1. Adım: Mevcut modelleri listele ve çalışan bir tane bul
        available_models = []
        try:
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    available_models.append(m.name)
        except:
            pass # Listeleme başarısız olursa varsayılana dön

        # Öncelik sırasına göre model seçimi
        selected_model = 'gemini-pro' # Varsayılan (Fallback)
        
        # Eğer listede varsa bunları tercih et:
        preferred_order = ['models/gemini-1.5-flash', 'models/gemini-1.5-pro', 'models/gemini-pro', 'models/gemini-1.0-pro']
        
        for pref in preferred_order:
            if pref in available_models:
                selected_model = pref
                break
        
        # Modeli çalıştır
        model = genai.GenerativeModel(selected_model)
        response = model.generate_content(prompt)
        return response.text

    except Exception as e:
        return f"AI Hatası: {str(e)}\n(Kullanılan Model: {selected_model if 'selected_model' in locals() else 'Bilinmiyor'})"

# --- ANA UYGULAMA ---
def main():
    st.title("⚖️ Hukuk Asistanı Pro")
    
    if "doc_text" not in st.session_state: st.session_state.doc_text = ""
    if "last_file_id" not in st.session_state: st.session_state.last_file_id = None
    if "messages" not in st.session_state: st.session_state.messages = []
    if "mevzuat_sonuc" not in st.session_state: st.session_state.mevzuat_sonuc = ""
    if "ictihat_sonuc" not in st.session_state: st.session_state.ictihat_sonuc = ""

    with st.sidebar:
        st.header("⚙️ Ayarlar")
        api_key = st.text_input("Google Gemini API Key", type="password")
        
        # API Bağlantı Testi (Kullanıcıya bilgi vermek için)
        if api_key:
            try:
                genai.configure(api_key=api_key)
                st.success("API Anahtarı Bağlandı")
            except:
                st.error("API Anahtarı Geçersiz")

        st.divider()
        st.header("📁 Dosya Bilgileri")
        input_davaci = st.text_input("Davacı / Alacaklı")
        input_davali = st.text_input("Davalı / Borçlu")
        input_mahkeme = st.text_input("Mahkeme (Manuel)")
        input_dosya_no = st.text_input("Dosya No (Manuel)")
        
        if st.button("Sıfırla / Yeni Dosya"):
            st.session_state.doc_text = ""
            st.session_state.last_file_id = None
            st.session_state.messages = []
            st.rerun()

    uploaded_file = st.file_uploader("Dosya Yükle (UDF/PDF)", type=['udf', 'pdf'], key="uploader")

    if uploaded_file is not None:
        if st.session_state.last_file_id != uploaded_file.file_id:
            with st.spinner("Dosya analiz ediliyor..."):
                file_bytes = BytesIO(uploaded_file.getvalue())
                ext = uploaded_file.name.split('.')[-1].lower()
                
                if ext == 'udf':
                    raw_text = parse_udf(file_bytes)
                else:
                    raw_text = parse_pdf(file_bytes)
                
                st.session_state.doc_text = raw_text
                st.session_state.last_file_id = uploaded_file.file_id
                st.session_state.messages = []
                
    if st.session_state.doc_text.startswith("HATA"):
        st.error(st.session_state.doc_text)
    elif st.session_state.doc_text.startswith("UYARI"):
        st.warning(st.session_state.doc_text)
        st.info("Bu dosya resim formatında olduğu için metin okunamadı.")
    
    auto_data = extract_metadata(st.session_state.doc_text)

    tab1, tab2, tab3, tab4 = st.tabs(["📋 Dosya Analizi", "💬 Dosya Sohbeti", "📕 Mevzuat Ara", "⚖️ İçtihat Ara"])

    with tab1:
        if not st.session_state.doc_text or st.session_state.doc_text.startswith(("HATA", "UYARI")):
            st.info("Lütfen geçerli bir dosya yükleyin.")
        else:
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"**Mahkeme:** {input_mahkeme or auto_data['mahkeme']}")
                st.markdown(f"**Dosya No:** {input_dosya_no or auto_data['esas']}")
                st.markdown(f"**Karar No:** {auto_data['karar']}")
                st.markdown(f"**Tarih:** {auto_data['tarih']}")
            with col2:
                st.markdown(f"**Davacı:** {input_davaci or '-'}")
                st.markdown(f"**Davalı:** {input_davali or '-'}")
            
            st.divider()
            with st.expander("📄 Ham Metni Gör"):
                st.text_area("Metin", st.session_state.doc_text, height=200)

    with tab2:
        if not api_key:
            st.error("API Anahtarı gerekli.")
        else:
            for msg in st.session_state.messages:
                with st.chat_message(msg["role"]): st.markdown(msg["content"])

            if prompt := st.chat_input("Soru sor..."):
                st.session_state.messages.append({"role": "user", "content": prompt})
                with st.chat_message("user"): st.markdown(prompt)
                
                with st.chat_message("assistant"):
                    with st.spinner("Düşünülüyor..."):
                        safe_text = st.session_state.doc_text[:25000]
                        context = f"BELGE: {safe_text}\nSORU: {prompt}"
                        reply = get_gemini_response(f"Hukukçu gibi cevapla: {context}", api_key)
                        st.markdown(reply)
                        st.session_state.messages.append({"role": "assistant", "content": reply})

    with tab3:
        st.subheader("📕 Mevzuat")
        col_m1, col_m2 = st.columns([3, 1])
        with col_m1: mevzuat_query = st.text_input("Kanun/Madde", key="mev_q")
        with col_m2: 
            st.write("")
            st.write("")
            btn_mevzuat = st.button("Getir", type="primary")

        if btn_mevzuat and mevzuat_query:
            with st.spinner("Aranıyor..."):
                prompt = f"GÖREV: '{mevzuat_query}' maddesini tam metin yaz."
                res = get_gemini_response(prompt, api_key)
                st.session_state.mevzuat_sonuc = res
        
        if st.session_state.mevzuat_sonuc:
            st.markdown(f"<div class='kanun-kutusu'>{st.session_state.mevzuat_sonuc}</div>", unsafe_allow_html=True)

    with tab4:
        st.subheader("⚖️ İçtihat")
        col_i1, col_i2 = st.columns([3, 1])
        with col_i1: ictihat_query = st.text_input("Konu", key="ic_q")
        with col_i2: 
            st.write("")
            st.write("")
            btn_ictihat = st.button("Ara", type="primary")

        if btn_ictihat and ictihat_query:
            with st.spinner("Taranıyor..."):
                prompt = f"GÖREV: '{ictihat_query}' konusunda Yargıtay içtihatlarını özetle."
                res = get_gemini_response(prompt, api_key)
                st.session_state.ictihat_sonuc = res

        if st.session_state.ictihat_sonuc:
            st.markdown(f"<div class='ictihat-kutusu'>{st.session_state.ictihat_sonuc}</div>", unsafe_allow_html=True)

if __name__ == "__main__":
    main()
