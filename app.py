import streamlit as st
import google.generativeai as genai
import os

# --- API 키 설정 ---
# 실제 서비스 시에는 환경변수(os.environ)나 Streamlit Secrets를 사용하는 것이 안전합니다.

API_KEY = st.secrets["GEMINI_API_KEY"]

# 모델 설정 (최신 2.5 버전으로 변경!)
model = genai.GenerativeModel('gemini-2.5-flash')

# --- 프롬프트 설정 ---
SYSTEM_PROMPT = """
너는 전문 자막 교정자야. 업로드된 SMI 파일에서 오탈자, 띄어쓰기, 문맥 오류를 검수해줘. 
결과는 반드시[타임코드 | 원본 | 수정 제안 | 사유] 순서의 마크다운 표 형식으로만 작성해줘.
구어체나 사투리는 상황에 맞게 보존하고, 명백한 오류만 교정해.

[중요 자막 정책]
- 문장 끝에는 절대 마침표(.)를 찍지 말고 없다고 오류로 잡지도 마. (물음표나 느낌표는 상황에 따라 허용)
"""

# --- 웹앱 UI 구성 ---
st.set_page_config(page_title="AI 자막 교정기", page_icon="📝", layout="wide")

st.title("📝 AI 전문 자막 교정기")
st.write("SMI 자막 파일을 업로드하면 AI가 오탈자와 문맥 오류를 검수하여 교정표를 만들어 줍니다.")

# 파일 업로드 컴포넌트
uploaded_file = st.file_uploader("SMI 파일을 업로드하세요", type=["smi", "srt", "txt"])

if uploaded_file is not None:
    # 파일 읽기 (인코딩 처리: utf-8 우선, 실패 시 euc-kr)
    try:
        file_content = uploaded_file.read().decode("utf-8")
    except UnicodeDecodeError:
        uploaded_file.seek(0)
        file_content = uploaded_file.read().decode("euc-kr")
    
    st.success("파일이 성공적으로 업로드되었습니다!")
    
    # 원본 내용 미리보기 (접기/펴기)
    with st.expander("원본 자막 내용 보기"):
        st.text(file_content[:1000] + "...\n(이하 생략)")

    # 교정 시작 버튼
    if st.button("🚀 AI 자막 검수 시작", type="primary"):
        with st.spinner("AI가 자막을 꼼꼼히 검수하고 있습니다. 잠시만 기다려주세요..."):
            try:
                # AI에게 요청 보내기
                full_prompt = f"{SYSTEM_PROMPT}\n\n--- 자막 내용 ---\n{file_content}"
                response = model.generate_content(full_prompt)
                
                # 결과 출력
                st.subheader("✅ 검수 및 교정 결과")
                st.markdown(response.text)
                
            except Exception as e:
                st.error(f"오류가 발생했습니다: {e}")