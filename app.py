import streamlit as st
from google import genai
from google.genai import types

# --- 1. 페이지 기본 설정 (반드시 최상단에 위치) ---
st.set_page_config(page_title="AI 자막 교정기", page_icon="📝", layout="wide")

# --- 2. API 클라이언트 초기화 (캐싱 적용) ---
# Streamlit Cloud 환경에서 매번 재연결하지 않도록 캐싱(@st.cache_resource)을 적용합니다.
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
# 최신 3.6 플래시 모델 적용
MODEL_ID = 'gemini-3.6-flash'

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
st.title("📝 AI 전문 자막 교정기 (v3.6)")
st.markdown("""
**최신 Gemini 3.6 Flash 모델**을 탑재한 자막 검수 솔루션입니다.
SMI, SRT 자막 파일을 업로드하면 AI가 오탈자와 문맥 오류를 검수하여 교정표를 제공합니다.
""")

# 사이드바 (설정 및 안내)
with st.sidebar:
    st.header("⚙️ 검수 설정")
    # 온도(Temperature) 조절 슬라이더 추가
    temperature = st.slider(
        "AI 창의성 (Temperature)", 
        min_value=0.0, max_value=1.0, value=0.2, step=0.1, 
        help="0에 가까울수록 일관되고 보수적인 검수를, 1에 가까울수록 유연한 교정을 제안합니다. 자막 검수는 0.2를 권장합니다."
    )
    st.divider()
    st.info("💡 **Tip:** 파일 용량에 따라 검수 완료까지 약 10초 ~ 30초 정도 소요될 수 있습니다.")

# --- 5. 파일 업로드 및 처리 ---
uploaded_file = st.file_uploader("자막 파일을 업로드하세요 (지원 형식: .smi, .srt, .txt)", type=["smi", "srt", "txt"])

if uploaded_file is not None:
    # 윈도우/맥 등 다양한 환경에서 작성된 자막 파일 인코딩(한글 깨짐) 완벽 대응
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
    
    # 원본 내용 미리보기 (너무 길면 자름)
    with st.expander("원본 자막 내용 미리보기"):
        st.text(file_content[:1000] + ("\n\n...(이하 생략)" if len(file_content) > 1000 else ""))

    # --- 6. 교정 실행 및 결과 출력 ---
    # 버튼을 넓게 배치하여 클릭 유도
    if st.button("🚀 AI 자막 검수 시작", type="primary", use_container_width=True):
        with st.spinner("AI가 자막을 꼼꼼히 분석하고 있습니다. 잠시만 기다려주세요..."):
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
                
                # 결과 출력
                st.divider()
                st.subheader("📊 검수 및 교정 결과")
                st.markdown(response.text)
                
                # 엑셀/백데이터 활용을 위한 다운로드 버튼 제공
                st.download_button(
                    label="📥 검수 결과 다운로드 (.md)",
                    data=response.text,
                    file_name=f"검수결과_{uploaded_file.name}.md",
                    mime="text/markdown",
                    use_container_width=True
                )
                
            except Exception as e:
                st.error(f"❌ API 호출 중 오류가 발생했습니다: {e}")
