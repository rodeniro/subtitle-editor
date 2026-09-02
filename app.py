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
# 안정화된 3.5 플래시 모델로 변경
MODEL_ID = 'gemini-3.5-flash'

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
st.title("📝 AI 전문 자막 교정기 (v3.5)")
st.markdown("""
안정적인 **Gemini 3.5 Flash** 모델을 탑재하고, 
서버 과부하 시 자동으로 재시도하는 기능을 갖춘 자막 검수 솔루션입니다.
""")

with st.sidebar:
    st.header("⚙️ 검수 설정")
    temperature = st.slider(
        "AI 창의성 (Temperature)", 
        min_value=0.0, max_value=1.0, value=0.2, step=0.1
    )
    st.divider()
    st.info("💡 **Tip:** 서버 과부하(503 에러) 발생 시 자동으로 3초 대기 후 최대 3회까지 재시도합니다.")

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
        status_container = st.empty() # 재시도 메시지 출력을 위한 빈 공간
        
        with status_container.container():
            with st.spinner("AI가 자막을 꼼꼼히 분석하고 있습니다. 잠시만 기다려주세요..."):
                for attempt in range(max_retries):
                    try:
                        # API 호출
                        response = client.models.generate_content(
                            model=MODEL_ID,
                            contents=f"--- 자막 내용 ---\n{file_content}",
                            config=types.GenerateContentConfig(
                                system_instruction=SYSTEM_INSTRUCTION,
                                temperature=temperature
                            )
                        )
                        
                        # 성공 시 기존 대기 메시지 삭제 및 결과 출력
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
                        break # 성공하면 반복문 즉시 탈출
                        
                    except Exception as e:
                        # 503 에러 발생 시 재시도 로직
                        if "503" in str(e) and attempt < max_retries - 1:
                            st.warning(f"⚠️ 서버 과부하 감지. 3초 후 다시 시도합니다... (재시도 {attempt+1}/{max_retries})")
                            time.sleep(3)
                        else:
                            # 503 이외의 에러거나 최대 재시도 횟수를 초과한 경우
                            status_container.empty()
                            st.error(f"❌ API 호출 중 오류가 발생했습니다: {e}")
                            break
