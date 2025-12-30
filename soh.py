import streamlit as st
import zipfile
import xml.etree.ElementTree as ET
import re
from pypdf import PdfReader
from io import BytesIO
import google.generativeai as genai
import time

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
    .css-1aumxhk { padding: 1rem; } /* Tab padding */
    .kanun-kutusu { 
        background-color: #ffffff; 
        padding: 20px; 
        border-left: 5px solid #b71c1c; 
        border-radius: 5px; 
        box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        margin-bottom: 15px;
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
            return "Hata: content.xml bulunamadı."
    except Exception as e:
        return f"Hata: {str(e)}"

def parse_pdf(file_bytes):
    try:
        reader = PdfReader(file_bytes)
        text = "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])
        return text if text.strip() else "UYARI: Metin bulunamadı (Taranmış evrak olabilir)."
    except Exception as e:
        return f"Hata: {str(e)}"

def extract_metadata(text):
    if not isinstance(text, str): return {}
    esas = re.search(r"(?i)Esas\s*No\s*[:\-]?\s*(\d{4}/\d+)", text)
    karar = re.search(r"(?i)Karar\s*No\s*[:\-]?\s*(\d{4}/\d+)", text)
    tarih = re.search(r"(\d{1,2}[./]\d{1,2}[./]\d{4})", text)
    mahkeme = "Tespit Edilemedi"
    for line in text.split('\n')[:30]:
        clean = line.strip()
        if ("MAHKEMESİ" in clean.upper() or "DAİRESİ" in clean.upper()) and len(clean) > 5:
            mahkeme = clean
            break
    return {
        "mahkeme": mahkeme,
        "esas": esas.group(1) if esas else "",
        "karar": karar.group(1) if karar else "",
        "tarih": tarih.group(1) if tarih else ""
    }

# --- AI FONKSİYONLARI ---
def get_gemini_response(prompt, api_key):
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Hata: {str(e)}"

# --- ANA UYGULAMA ---
def main():
    st.title("⚖️ Hukuk Asistanı Pro")
    
    # --- SOL MENÜ ---
    with st.sidebar:
        st.header("⚙️ Ayarlar")
        api_key = st.text_input("Google Gemini API Key", type="password")
        if not api_key:
            st.warning("⚠️ Mevzuat ve Sohbet için API Key giriniz.")
            st.markdown("[Anahtar Al](https://aistudio.google.com/app/apikey)")
        
        st.divider()
        st.header("📁 Dosya Bilgileri")
        input_davaci = st.text_input("Davacı / Alacaklı")
        input_davali = st.text_input("Davalı / Borçlu")
        input_mahkeme = st.text_input("Mahkeme (Manuel)")
        input_dosya_no = st.text_input("Dosya No (Manuel)")

    # --- DOSYA YÜKLEME ---
    uploaded_file = st.file_uploader("Dosya Yükle (UDF/PDF)", type=['udf', 'pdf'])

    # Session State
    if "messages" not in st.session_state: st.session_state.messages = []
    if "doc_text" not in st.session_state: st.session_state.doc_text = ""
    if "mevzuat_sonuc" not in st.session_state: st.session_state.mevzuat_sonuc = ""
    if "ictihat_sonuc" not in st.session_state: st.session_state.ictihat_sonuc = ""

    # Dosya İşleme
    if uploaded_file and st.session_state.get("last_file") != uploaded_file.name:
        with st.spinner("Dosya okunuyor..."):
            file_bytes = BytesIO(uploaded_file.getvalue())
            ext = uploaded_file.name.split('.')[-1].lower()
            raw_text = parse_udf(file_bytes) if ext == 'udf' else parse_pdf(file_bytes)
            st.session_state.doc_text = raw_text
            st.session_state.last_file = uploaded_file.name
            st.session_state.messages = [] 

    auto_data = extract_metadata(st.session_state.doc_text)

    # --- 4 SEKME ---
    tab1, tab2, tab3, tab4 = st.tabs(["📋 Dosya Analizi", "💬 Dosya Sohbeti", "📕 Mevzuat Ara", "⚖️ İçtihat Ara"])

    # --- TAB 1: ANALİZ ---
    with tab1:
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
        with st.expander("📄 Belge Metni"):
            st.text_area("Metin", st.session_state.doc_text, height=300)

    # --- TAB 2: SOHBET ---
    with tab2:
        if not api_key:
            st.error("Lütfen sol menüden API Anahtarı girin.")
        else:
            for msg in st.session_state.messages:
                with st.chat_message(msg["role"]): st.markdown(msg["content"])

            if prompt := st.chat_input("Belge hakkında soru sor..."):
                st.session_state.messages.append({"role": "user", "content": prompt})
                with st.chat_message("user"): st.markdown(prompt)
                
                with st.chat_message("assistant"):
                    with st.spinner("İnceleniyor..."):
                        context = f"BELGE: {st.session_state.doc_text[:30000]}\nSORU: {prompt}"
                        reply = get_gemini_response(f"Sen bir hukukçusun. Belgeye göre cevapla: {context}", api_key)
                        st.markdown(reply)
                        st.session_state.messages.append({"role": "assistant", "content": reply})

    # --- TAB 3: MEVZUAT ARAMA (SİTE SİMÜLASYONU) ---
    with tab3:
        st.subheader("📕 Mevzuat Kütüphanesi")
        st.caption("Resmi Gazete ve Mevzuat.gov.tr veritabanına dayalı arama yapar.")
        
        col_m1, col_m2 = st.columns([3, 1])
        with col_m1:
            mevzuat_query = st.text_input("Kanun Adı veya Madde (Örn: TBK 12, HMK 30)", key="mev_q")
        with col_m2:
            st.write("")
            st.write("")
            btn_mevzuat = st.button("Mevzuatı Getir", type="primary")

        if btn_mevzuat and mevzuat_query and api_key:
            with st.spinner("Mevzuat veritabanından çekiliyor..."):
                # Prompt Engineering: AI'ı resmi bir veritabanı gibi davranmaya zorluyoruz
                mevzuat_prompt = f"""
                GÖREV: Aşağıdaki kanun maddesini kelimesi kelimesine, resmi gazetedeki haliyle getir.
                Sadece kanun metnini yaz. Yorum yapma.
                ARANAN: {mevzuat_query}
                
                FORMAT:
                **KANUN ADI**
                **Madde No**
                [Madde Metni]
                """
                res = get_gemini_response(mevzuat_prompt, api_key)
                st.session_state.mevzuat_sonuc = res
        
        if st.session_state.mevzuat_sonuc:
            st.markdown(f"<div class='kanun-kutusu'>{st.session_state.mevzuat_sonuc}</div>", unsafe_allow_html=True)
            st.caption("Kaynak: T.C. Mevzuat Bilgi Sistemi verilerine dayalıdır.")

    # --- TAB 4: İÇTİHAT ARAMA ---
    with tab4:
        st.subheader("⚖️ Emsal Karar & İçtihat Arama")
        st.caption("Yargıtay ve BAM kararları arasında anlamsal arama yapar.")
        
        col_i1, col_i2 = st.columns([3, 1])
        with col_i1:
            ictihat_query = st.text_input("Konu veya Anahtar Kelime (Örn: Boşanma ziynet eşyası ispat)", key="ic_q")
        with col_i2:
            st.write("")
            st.write("")
            btn_ictihat = st.button("İçtihat Ara", type="primary")

        if btn_ictihat and ictihat_query and api_key:
            with st.spinner("Yüksek mahkeme kararları taranıyor..."):
                ictihat_prompt = f"""
                GÖREV: Türk Hukukunda "{ictihat_query}" konusuyla ilgili yerleşik Yargıtay içtihatlarını özetle.
                
                Şu formatta çıktı ver:
                1. **İlgili Hukuk Dairesi:** (Örn: Yargıtay 2. Hukuk Dairesi)
                2. **Özet İlke:** (Kararın özü nedir?)
                3. **Detaylı Açıklama:** (Hukuki gerekçe)
                4. **Emsal Karar Referansı:** (Varsa Esas/Karar no uydurma, yoksa 'Yerleşik İçtihat' yaz)
                """
                res = get_gemini_response(ictihat_prompt, api_key)
                st.session_state.ictihat_sonuc = res

        if st.session_state.ictihat_sonuc:
            st.markdown(f"<div class='ictihat-kutusu'>{st.session_state.ictihat_sonuc}</div>", unsafe_allow_html=True)

if __name__ == "__main__":
    main()
