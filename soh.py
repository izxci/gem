import streamlit as st
import zipfile
import xml.etree.ElementTree as ET
import re
from pypdf import PdfReader
from io import BytesIO
import google.generativeai as genai

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
    .stTextInput>div>div>input { background-color: #ffffff; }
    .chat-message { padding: 1.5rem; border-radius: 0.5rem; margin-bottom: 1rem; display: flex }
    .chat-message.user { background-color: #e3f2fd }
    .chat-message.bot { background-color: #f1f3f4 }
    </style>
    """, unsafe_allow_html=True)

# --- FONKSİYONLAR ---

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
    
    # Regex Desenleri
    esas = re.search(r"(?i)Esas\s*No\s*[:\-]?\s*(\d{4}/\d+)", text)
    karar = re.search(r"(?i)Karar\s*No\s*[:\-]?\s*(\d{4}/\d+)", text)
    tarih = re.search(r"(\d{1,2}[./]\d{1,2}[./]\d{4})", text)
    
    # Mahkeme Tahmini
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

# --- ANA UYGULAMA ---
def main():
    st.title("⚖️ Akıllı Hukuk Otomasyonu & Sohbet")
    
    # --- SOL MENÜ (AYARLAR & GİRİŞ) ---
    with st.sidebar:
        st.header("⚙️ Ayarlar")
        api_key = st.text_input("Google Gemini API Key", type="password", help="Sohbet özelliği için gereklidir.")
        
        st.divider()
        st.header("📁 Dosya Bilgileri")
        
        # Manuel Giriş Alanları
        input_davaci = st.text_input("Davacı / Alacaklı")
        input_davali = st.text_input("Davalı / Borçlu")
        input_mahkeme = st.text_input("Mahkeme Adı (Manuel)")
        input_dosya_no = st.text_input("Dosya No (Manuel)")
        
        st.info("Dosya yüklendiğinde otomatik veriler buradaki manuel verilerle birleştirilir.")

    # --- DOSYA YÜKLEME ---
    uploaded_file = st.file_uploader("Bir UDF veya PDF dosyası yükleyin", type=['udf', 'pdf'])

    # Session State Başlatma (Sohbet geçmişi ve metin hafızası için)
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "doc_text" not in st.session_state:
        st.session_state.doc_text = ""

    if uploaded_file:
        # Dosyayı işle (Sadece dosya değiştiyse tekrar işle)
        if st.session_state.get("last_file") != uploaded_file.name:
            with st.spinner("Dosya okunuyor..."):
                file_bytes = BytesIO(uploaded_file.getvalue())
                ext = uploaded_file.name.split('.')[-1].lower()
                
                if ext == 'udf':
                    raw_text = parse_udf(file_bytes)
                else:
                    raw_text = parse_pdf(file_bytes)
                
                st.session_state.doc_text = raw_text
                st.session_state.last_file = uploaded_file.name
                # Yeni dosya gelince sohbeti temizle
                st.session_state.messages = [] 

        # Otomatik Verileri Çek
        auto_data = extract_metadata(st.session_state.doc_text)

        # --- SEKME YAPISI ---
        tab1, tab2 = st.tabs(["📋 Dosya Özeti & Veriler", "💬 Belgeyle Sohbet"])

        # --- SEKME 1: VERİ GÖRÜNTÜLEME ---
        with tab1:
            st.subheader("Dosya Künyesi")
            
            # Otomatik ve Manuel veriyi önceliklendirerek göster
            final_mahkeme = input_mahkeme if input_mahkeme else auto_data['mahkeme']
            final_esas = input_dosya_no if input_dosya_no else auto_data['esas']
            
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"**Mahkeme:** {final_mahkeme}")
                st.markdown(f"**Dosya/Esas No:** {final_esas}")
                st.markdown(f"**Karar No:** {auto_data['karar']}")
                st.markdown(f"**Tarih:** {auto_data['tarih']}")
            
            with col2:
                st.markdown(f"**Davacı:** {input_davaci if input_davaci else '-'}")
                st.markdown(f"**Davalı:** {input_davali if input_davali else '-'}")
            
            st.divider()
            with st.expander("📄 Belge İçeriğini Görüntüle"):
                st.text_area("Ham Metin", st.session_state.doc_text, height=300)

        # --- SEKME 2: SOHBET (AI) ---
        with tab2:
            if not api_key:
                st.warning("⚠️ Sohbet özelliğini kullanmak için sol menüden Google API Anahtarını giriniz.")
            else:
                st.info("Bu belge hakkında sorular sorun. (Örn: 'Davanın sonucu nedir?', 'Davacı ne talep etmiş?')")

                # Geçmiş mesajları göster
                for message in st.session_state.messages:
                    with st.chat_message(message["role"]):
                        st.markdown(message["content"])

                # Kullanıcı girişi
                if prompt := st.chat_input("Sorunuzu yazın..."):
                    # Kullanıcı mesajını ekle
                    st.session_state.messages.append({"role": "user", "content": prompt})
                    with st.chat_message("user"):
                        st.markdown(prompt)

                    # AI Cevabı
                    with st.chat_message("assistant"):
                        with st.spinner("Hukuk asistanı düşünüyor..."):
                            try:
                                genai.configure(api_key=api_key)
                                model = genai.GenerativeModel('gemini-1.5-flash')
                                
                                # Prompt Mühendisliği: Belgeyi bağlam olarak veriyoruz
                                context_prompt = f"""
                                Sen uzman bir Türk Hukuku asistanısın. Aşağıdaki belge metnine dayanarak kullanıcının sorusunu cevapla.
                                Cevapların net, hukuki terminolojiye uygun ama anlaşılır olsun. Belgede olmayan bir bilgi uydurma.
                                
                                BELGE METNİ:
                                {st.session_state.doc_text[:30000]} 
                                
                                KULLANICI SORUSU:
                                {prompt}
                                """
                                # Not: Gemini 1.5 Flash çok büyük metinleri alabilir, 30k karakter sınırı koydum ama artırılabilir.
                                
                                response = model.generate_content(context_prompt)
                                st.markdown(response.text)
                                
                                # Cevabı geçmişe ekle
                                st.session_state.messages.append({"role": "assistant", "content": response.text})
                                
                            except Exception as e:
                                st.error(f"API Hatası: {str(e)}")

if __name__ == "__main__":
    main()
