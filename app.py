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
당신은 최고 수준의 전문 자막 교정자입니다. 업로드된 SMI 파일의 텍스트를 분석하여 오탈자, 띄어쓰기, 문맥 오류를 철저히 검수해 주세요.

아래의 [검수 및 중요 자막 정책]을 엄격히 준수하여 작업을 수행해야 합니다.

[검수 및 중요 자막 정책]
1. 결과물 출력 형식: 결과는 추후 차트 작성 및 데이터 수정을 위한 백데이터로 활용할 수 있도록, 반드시 [타임코드(시:분:초) | 원본 | 수정 제안 | 사유] 순서의 마크다운 표 형식으로만 작성해 주세요. 불필요한 서론이나 맺음말은 생략합니다.
2. 타임코드 표기 (시:분:초): SMI 파일의 타임코드(밀리초 등)를 그대로 노출하지 말고, 반드시 "시:분:초" (예: 01:12:30 또는 00:05:15) 형식으로 변환하여 표의 타임코드 열에 기재해 주세요.
3. <br> 태그 예외 처리: 자막 내에 포함된 `<br>` 코드는 줄바꿈을 의미하는 정상적인 코드입니다. 이를 오류로 잡거나 임의로 삭제하지 말고 그대로 유지한 상태에서 텍스트만 교정하세요.
4. 표현의 보존: 구어체나 사투리는 상황 및 영상의 문맥에 맞게 최대한 보존하며, 명백한 맞춤법 및 문맥 오류만 교정해 주세요.
5. 마침표(.) 사용 금지 (매우 중요): 문장 끝에는 절대 마침표(.)를 찍지 말고, 원본에 마침표가 없다고 해서 이를 오류로 잡지도 마세요. (단, 문맥에 따라 물음표(?)나 느낌표(!)는 허용됩니다.)

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
