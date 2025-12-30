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
            return "UYARI: PDF metin içermiyor. Taranmış resim (OCR gerektiren) formatında olabilir."
        return text
    except Exception as e:
        return f"HATA: {str(e)}"

def extract_metadata(text):
    if not isinstance(text, str) or text.startswith("HATA") or text.startswith("UYARI"):
        return {"mahkeme": "-", "esas": "-", "karar": "-", "tarih": "-"}
    
    # Regex Desenleri (Daha esnek)
    esas = re.search(r"(?i)Esas\s*No\s*[:\-]?\s*(\d{4}/\d+)", text)
    karar = re.search(r"(?i)Karar\s*No\s*[:\-]?\s*(\d{4}/\d+)", text)
    tarih = re.search(r"(\d{1,2}[./]\d{1,2}[./]\d{4})", text)
    
    mahkeme = "Tespit Edilemedi"
    for line in text.split('\n')[:40]: # İlk 40 satıra bak
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

def get_gemini_response(prompt, api_key):
    if not api_key: return "Lütfen API Anahtarı giriniz."
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-pro')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI Bağlantı Hatası: {str(e)}"

# --- ANA UYGULAMA ---
def main():
    st.title("⚖️ Hukuk Asistanı Pro")
    
    # --- SESSION STATE BAŞLATMA ---
    if "doc_text" not in st.session_state: st.session_state.doc_text = ""
    if "last_file_id" not in st.session_state: st.session_state.last_file_id = None
    if "messages" not in st.session_state: st.session_state.messages = []
    if "mevzuat_sonuc" not in st.session_state: st.session_state.mevzuat_sonuc = ""
    if "ictihat_sonuc" not in st.session_state: st.session_state.ictihat_sonuc = ""

    # --- SOL MENÜ ---
    with st.sidebar:
        st.header("⚙️ Ayarlar")
        api_key = st.text_input("Google Gemini API Key", type="password")
        if not api_key:
            st.info("Sohbet ve Mevzuat için API Key gereklidir.")
        
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

    # --- DOSYA YÜKLEME ALANI ---
    uploaded_file = st.file_uploader("Dosya Yükle (UDF/PDF)", type=['udf', 'pdf'], key="uploader")

    # --- DOSYA İŞLEME MANTIĞI (GÜNCELLENDİ) ---
    if uploaded_file is not None:
        # Dosya ID'si değiştiyse (yeni dosya geldiyse) işle
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
                st.session_state.messages = [] # Sohbeti temizle
                
    # --- HATA KONTROLÜ VE ARAYÜZ ---
    if st.session_state.doc_text.startswith("HATA"):
        st.error(st.session_state.doc_text)
    elif st.session_state.doc_text.startswith("UYARI"):
        st.warning(st.session_state.doc_text)
        st.info("Bu dosya resim formatında olduğu için metin okunamadı. Ancak diğer özellikleri (Mevzuat/İçtihat) kullanabilirsiniz.")
    
    # Dosya yüklü olmasa bile Mevzuat/İçtihat çalışsın diye Tabs her zaman görünür
    # Ancak Analiz sekmesi boşsa uyarı verir.
    
    auto_data = extract_metadata(st.session_state.doc_text)

    # --- SEKMELER ---
    tab1, tab2, tab3, tab4 = st.tabs(["📋 Dosya Analizi", "💬 Dosya Sohbeti", "📕 Mevzuat Ara", "⚖️ İçtihat Ara"])

    # --- TAB 1: ANALİZ ---
    with tab1:
        if not st.session_state.doc_text or st.session_state.doc_text.startswith(("HATA", "UYARI")):
            st.info("Lütfen geçerli bir UDF veya PDF dosyası yükleyin.")
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
            with st.expander("📄 Çıkarılan Ham Metni Gör"):
                st.text_area("Metin", st.session_state.doc_text, height=200)

    # --- TAB 2: SOHBET ---
    with tab2:
        if not st.session_state.doc_text or st.session_state.doc_text.startswith(("HATA", "UYARI")):
            st.warning("Sohbet etmek için önce okunabilir bir dosya yüklemelisiniz.")
        elif not api_key:
            st.error("Sohbet için API Anahtarı gereklidir.")
        else:
            # Geçmiş mesajları göster
            for msg in st.session_state.messages:
                with st.chat_message(msg["role"]): st.markdown(msg["content"])

            # Yeni mesaj girişi
            if prompt := st.chat_input("Dosya hakkında soru sor..."):
                st.session_state.messages.append({"role": "user", "content": prompt})
                with st.chat_message("user"): st.markdown(prompt)
                
                with st.chat_message("assistant"):
                    with st.spinner("Düşünülüyor..."):
                        safe_text = st.session_state.doc_text[:25000] # Token limiti koruması
                        context = f"BELGE: {safe_text}\nSORU: {prompt}"
                        reply = get_gemini_response(f"Sen uzman bir avukatsın. Sadece bu belgeye göre cevap ver: {context}", api_key)
                        st.markdown(reply)
                        st.session_state.messages.append({"role": "assistant", "content": reply})

    # --- TAB 3: MEVZUAT ---
    with tab3:
        st.subheader("📕 Mevzuat Kütüphanesi")
        col_m1, col_m2 = st.columns([3, 1])
        with col_m1:
            mevzuat_query = st.text_input("Kanun/Madde (Örn: TBK 12)", key="mev_q")
        with col_m2:
            st.write("")
            st.write("")
            btn_mevzuat = st.button("Getir", type="primary")

        if btn_mevzuat and mevzuat_query:
            with st.spinner("Aranıyor..."):
                prompt = f"GÖREV: '{mevzuat_query}' maddesini tam metin olarak yaz. Yorum yapma."
                res = get_gemini_response(prompt, api_key)
                st.session_state.mevzuat_sonuc = res
        
        if st.session_state.mevzuat_sonuc:
            st.markdown(f"<div class='kanun-kutusu'>{st.session_state.mevzuat_sonuc}</div>", unsafe_allow_html=True)

    # --- TAB 4: İÇTİHAT ---
    with tab4:
        st.subheader("⚖️ İçtihat Arama")
        col_i1, col_i2 = st.columns([3, 1])
        with col_i1:
            ictihat_query = st.text_input("Konu (Örn: Ziynet eşyası ispat)", key="ic_q")
        with col_i2:
            st.write("")
            st.write("")
            btn_ictihat = st.button("Ara", type="primary")

        if btn_ictihat and ictihat_query:
            with st.spinner("Taranıyor..."):
                prompt = f"GÖREV: '{ictihat_query}' konusunda Yargıtay içtihatlarını özetle. Format: Daire, İlke, Açıklama."
                res = get_gemini_response(prompt, api_key)
                st.session_state.ictihat_sonuc = res

        if st.session_state.ictihat_sonuc:
            st.markdown(f"<div class='ictihat-kutusu'>{st.session_state.ictihat_sonuc}</div>", unsafe_allow_html=True)

if __name__ == "__main__":
    main()
