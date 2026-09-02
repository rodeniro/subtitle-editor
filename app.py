import streamlit as st
import time
from google import genai
from google.genai import types

# --- 1. 페이지 기본 설정 ---
st.set_page_config(page_title="AI 자막 교정기", page_icon="📝", layout="wide")

# --- 2. API 클라이언트 초기화 ---
@st.cache_resource
def get_genai_client():
    try:
        api_key = st.secrets["GEMINI_API_KEY"]
        return genai.Client(api_key=api_key)
    except KeyError:
        st.error("⚠️ Streamlit Secrets에 'GEMINI_API_KEY'가 설정되지 않았습니다.")
        st.stop()

client = get_genai_client()

# --- 3. 모델 및 프롬프트 설정 ---
# 안정화된 2.5 플래시 모델 사용
MODEL_ID = 'gemini-2.5-flash'

SYSTEM_INSTRUCTION = """
당신은 최고 수준의 전문 자막 교정자입니다. 업로드된 파일의 텍스트를 분석하여 오탈자, 띄어쓰기, 문맥 오류를 철저히 검수해 주세요.

아래의 [검수 및 중요 자막 정책]을 엄격히 준수하여 작업을 수행해야 합니다.

[검수 및 중요 자막 정책]
1. 결과물 출력 형식: 결과는 추후 차트 작성 및 데이터 수정을 위한 백데이터로 활용할 수 있도록, 반드시 [타임코드(시:분:초) | 원본 | 수정 제안 | 사유] 순서의 마크다운 표 형식으로만 작성해 주세요. 불필요한 서론이나 맺음말은 생략합니다.
2. 타임코드 표기 (시:분:초): SMI/SRT 파일의 타임코드(밀리초 등)를 그대로 노출하지 말고, 반드시 "시:분:초" (예: 01:12:30 또는 00:05:15) 형식으로 변환하여 표의 타임코드 열에 기재해 주세요.
3. <br> 태그 예외 처리: 자막 내에 포함된 `<br>` 코드는 줄바꿈을 의미하는 정상적인 코드입니다. 이를 오류로 잡거나 임의로 삭제하지 말고 그대로 유지한 상태에서 텍스트만 교정하세요.
4. 표현의 보존: 구어체나 사투리는 상황 및 영상의 문맥에 맞게 최대한 보존하며, 명백한 맞춤법 및 문맥 오류만 교정해 주세요.
5. 마침표(.) 사용 금지 (매우 중요): 문장 끝에는 절대 마침표(.)를 찍지 말고, 원본에 마침표가 없다고 해서 이를 오류로 잡지도 마세요. (단, 문맥에 따라 물음표(?)나 느낌표(!)는 허용됩니다.)
"""

# --- 4. 웹앱 UI 구성 ---
st.title("📝 AI 전문 자막 교정기")
st.markdown("""
안정적인 **Gemini 2.5 Flash** 모델을 탑재하고, 
자막 텍스트의 오탈자 및 문맥 오류를 정밀하게 분석해 주는 검수 솔루션입니다.
""")

# 슬라이더 대신 사용자 친화적인 가이드라인 추가
with st.sidebar:
    st.header("📌 이용 가이드")
    st.markdown("""
    **1. 파일 업로드**
    지원되는 형식(.smi, .srt, .txt)의 자막 파일을 화면에 끌어다 놓으세요.
    
    **2. 검수 시작**
    'AI 자막 검수 시작' 버튼을 누릅니다. 자막 분량에 따라 약 10초 ~ 60초 정도 소요될 수 있습니다.
    
    **3. 결과 확인 및 활용**
    검수가 끝나면 타임코드와 함께 오탈자, 수정 제안이 표 형태로 출력됩니다. 결과표 하단의 '다운로드' 버튼을 눌러 문서로 저장해 보세요.
    """)
    st.divider()
    st.info("💡 **시스템 안내:** 일시적인 서버 과부하 발생 시 자동으로 최대 3회까지 재시도하도록 설계되어 있습니다.")

# --- 5. 파일 업로드 및 처리 ---
uploaded_file = st.file_uploader("자막 파일을 업로드하세요 (지원 형식: .smi, .srt, .txt)", type=["smi", "srt", "txt"])

if uploaded_file is not None:
    file_content = None
    encodings = ["utf-8", "euc-kr", "cp949"]
    
    for enc in encodings:
        try:
            uploaded_file.seek(0)
            file_content = uploaded_file.read().decode(enc)
            break
        except UnicodeDecodeError:
            continue
    
    if file_content is None:
        st.error("❌ 파일을 읽을 수 없습니다. 파일의 인코딩 형식을 확인해 주세요.")
        st.stop()
        
    st.success(f"✅ '{uploaded_file.name}' 파일이 준비되었습니다.")
    
    with st.expander("원본 자막 내용 미리보기"):
        st.text(file_content[:1000] + ("\n\n...(이하 생략)" if len(file_content) > 1000 else ""))

    # --- 6. 교정 실행 및 자동 재시도 로직 ---
    if st.button("🚀 AI 자막 검수 시작", type="primary", use_container_width=True):
        max_retries = 3
        status_container = st.empty() 
        
        with status_container.container():
            with st.spinner("AI가 자막을 꼼꼼히 분석하고 있습니다. 잠시만 기다려주세요..."):
                for attempt in range(max_retries):
                    try:
                        # API 호출 (Temperature 0.2 하드코딩)
                        response = client.models.generate_content(
                            model=MODEL_ID,
                            contents=f"--- 자막 내용 ---\n{file_content}",
                            config=types.GenerateContentConfig(
                                system_instruction=SYSTEM_INSTRUCTION,
                                temperature=0.2 # 검수 품질을 위해 0.2로 고정
                            )
                        )
                        
                        status_container.empty() 
                        
                        st.divider()
                        st.subheader("📊 검수 및 교정 결과")
                        st.markdown(response.text)
                        
                        st.download_button(
                            label="📥 검수 결과 다운로드 (.md)",
                            data=response.text,
                            file_name=f"검수결과_{uploaded_file.name}.md",
                            mime="text/markdown",
                            use_container_width=True
                        )
                        break
                        
                    except Exception as e:
                        if "503" in str(e) and attempt < max_retries - 1:
                            st.warning(f"⚠️ 서버 접속량이 많습니다. 3초 후 다시 시도합니다... (재시도 {attempt+1}/{max_retries})")
                            time.sleep(3)
                        else:
                            status_container.empty()
                            st.error(f"❌ API 호출 중 오류가 발생했습니다: {e}")
                            break
