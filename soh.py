import streamlit as st
import zipfile
import xml.etree.ElementTree as ET
import re
from pypdf import PdfReader
from io import BytesIO
import google.generativeai as genai
import importlib.metadata

# --- Sayfa Ayarları ---
st.set_page_config(
    page_title="Hukuk Asistanı AI",
    page_icon="⚖️",
    layout="wide"
)

# --- CSS ---
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .kanun-kutusu { 
        background-color: #fff3e0; 
        padding: 15px; 
        border-left: 5px solid #ff9800; 
        border-radius: 5px; 
        margin-bottom: 10px;
        white-space: pre-wrap;
    }
    .ictihat-kutusu {
        background-color: #e3f2fd;
        padding: 15px;
        border-left: 5px solid #2196f3;
        border-radius: 5px;
        margin-bottom: 10px;
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
            return "HATA: UDF içeriği okunamadı."
    except Exception as e:
        return f"HATA: {str(e)}"

def parse_pdf(file_bytes):
    try:
        reader = PdfReader(file_bytes)
        text = "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])
        return text if text.strip() else "UYARI: PDF metin içermiyor (Resim olabilir)."
    except Exception as e:
        return f"HATA: {str(e)}"

def extract_metadata(text):
    if not isinstance(text, str) or text.startswith(("HATA", "UYARI")):
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

# --- AKILLI AI MOTORU (HATA ÇÖZÜCÜ) ---
def get_ai_response(prompt, api_key):
    if not api_key: return "Lütfen API Anahtarı giriniz."
    
    genai.configure(api_key=api_key)
    
    # Denenecek Modeller Listesi (En yeniden en eskiye)
    # Google şu an 'gemini-1.5-flash' modelini standart yaptı.
    candidate_models = [
        'gemini-1.5-flash',
        'gemini-1.5-pro',
        'gemini-1.0-pro',
        'gemini-pro'
    ]
    
    last_error = ""
    
    # 1. YÖNTEM: Listeden sırayla dene
    for model_name in candidate_models:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            return response.text # Başarılıysa döndür ve çık
        except Exception as e:
            last_error = str(e)
            continue # Hata verirse bir sonrakini dene

    # 2. YÖNTEM: Eğer hepsi başarısızsa, API'den dinamik liste iste
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                try:
                    model = genai.GenerativeModel(m.name)
                    response = model.generate_content(prompt)
                    return response.text
                except:
                    continue
    except:
        pass

    return f"Tüm modeller denendi ve başarısız oldu. Son Hata: {last_error}\nLütfen API Anahtarınızın geçerli olduğundan emin olun."

# --- ANA UYGULAMA ---
def main():
    st.title("⚖️ Hukuk Asistanı (v3.0)")
    
    # Kütüphane Sürüm Kontrolü (Debug için)
    try:
        lib_ver = importlib.metadata.version("google-generativeai")
    except:
        lib_ver = "Bilinmiyor"

    # Session State
    if "doc_text" not in st.session_state: st.session_state.doc_text = ""
    if "last_file_id" not in st.session_state: st.session_state.last_file_id = None
    if "messages" not in st.session_state: st.session_state.messages = []
    if "mevzuat_sonuc" not in st.session_state: st.session_state.mevzuat_sonuc = ""
    if "ictihat_sonuc" not in st.session_state: st.session_state.ictihat_sonuc = ""

    with st.sidebar:
        st.header("⚙️ Ayarlar")
        api_key = st.text_input("Google Gemini API Key", type="password")
        st.caption(f"Kütüphane Sürümü: {lib_ver}")
        
        st.divider()
        st.header("📁 Dosya Bilgileri")
        input_davaci = st.text_input("Davacı")
        input_davali = st.text_input("Davalı")
        input_mahkeme = st.text_input("Mahkeme")
        input_dosya_no = st.text_input("Dosya No")
        
        if st.button("🗑️ Temizle"):
            st.session_state.doc_text = ""
            st.session_state.last_file_id = None
            st.session_state.messages = []
            st.rerun()

    uploaded_file = st.file_uploader("Dosya Yükle (UDF/PDF)", type=['udf', 'pdf'])

    if uploaded_file and st.session_state.last_file_id != uploaded_file.file_id:
        with st.spinner("Okunuyor..."):
            file_bytes = BytesIO(uploaded_file.getvalue())
            ext = uploaded_file.name.split('.')[-1].lower()
            raw_text = parse_udf(file_bytes) if ext == 'udf' else parse_pdf(file_bytes)
            st.session_state.doc_text = raw_text
            st.session_state.last_file_id = uploaded_file.file_id
            st.session_state.messages = []

    if st.session_state.doc_text.startswith(("HATA", "UYARI")):
        st.warning(st.session_state.doc_text)
    
    auto_data = extract_metadata(st.session_state.doc_text)

    # --- SEKMELER ---
    tab1, tab2, tab3, tab4 = st.tabs(["📋 Analiz", "💬 Sohbet", "📕 Mevzuat", "⚖️ İçtihat"])

    with tab1:
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"**Mahkeme:** {input_mahkeme or auto_data['mahkeme']}")
            st.write(f"**Dosya No:** {input_dosya_no or auto_data['esas']}")
        with col2:
            st.write(f"**Davacı:** {input_davaci or '-'}")
            st.write(f"**Davalı:** {input_davali or '-'}")
        st.text_area("Metin Önizleme", st.session_state.doc_text, height=150)

    with tab2:
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]): st.markdown(msg["content"])

        if prompt := st.chat_input("Soru sor..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"): st.markdown(prompt)
            
            with st.chat_message("assistant"):
                with st.spinner("AI Yanıtlıyor..."):
                    context = f"BELGE: {st.session_state.doc_text[:20000]}\nSORU: {prompt}"
                    reply = get_ai_response(f"Sen bir avukatsın. Şuna cevap ver: {context}", api_key)
                    st.markdown(reply)
                    st.session_state.messages.append({"role": "assistant", "content": reply})

    with tab3:
        c1, c2 = st.columns([3,1])
        q = c1.text_input("Kanun Madde No", key="mq")
        if c2.button("Getir", key="mb") and q:
            with st.spinner("Aranıyor..."):
                res = get_ai_response(f"GÖREV: '{q}' maddesini tam metin yaz.", api_key)
                st.session_state.mevzuat_sonuc = res
        if st.session_state.mevzuat_sonuc:
            st.markdown(f"<div class='kanun-kutusu'>{st.session_state.mevzuat_sonuc}</div>", unsafe_allow_html=True)

    with tab4:
        c3, c4 = st.columns([3,1])
        iq = c3.text_input("İçtihat Konusu", key="iq")
        if c4.button("Ara", key="ib") and iq:
            with st.spinner("Taranıyor..."):
                res = get_ai_response(f"GÖREV: '{iq}' hakkında Yargıtay kararlarını özetle.", api_key)
                st.session_state.ictihat_sonuc = res
        if st.session_state.ictihat_sonuc:
            st.markdown(f"<div class='ictihat-kutusu'>{st.session_state.ictihat_sonuc}</div>", unsafe_allow_html=True)

if __name__ == "__main__":
    main()
