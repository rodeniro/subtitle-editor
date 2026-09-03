import streamlit as st
import time
from openai import OpenAI

# --- 1. 페이지 기본 설정 ---
st.set_page_config(page_title="AI 자막 교정기", page_icon="📝", layout="wide")

# ==========================================
# --- 2. API 클라이언트 초기화 ---
# ==========================================
@st.cache_resource
def get_openai_client():
    try:
        api_key = st.secrets["OPENAI_API_KEY"]
        return OpenAI(api_key=api_key)
    except KeyError:
        st.error("⚠️ Streamlit Secrets에 'OPENAI_API_KEY'가 설정되지 않았습니다.")
        st.stop()

client = get_openai_client()

# --- 3. 모델 및 프롬프트 설정 ---
MODEL_ID = 'gpt-4o-mini'

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

def split_text_into_chunks(text, lines_per_chunk=400):
    """긴 자막 파일을 여러 개의 덩어리(Chunk)로 안전하게 나눕니다."""
    lines = text.split('\n')
    chunks = []
    for i in range(0, len(lines), lines_per_chunk):
        chunk = '\n'.join(lines[i:i + lines_per_chunk])
        chunks.append(chunk)
    return chunks

# --- 4. 웹앱 UI 구성 ---
st.title("📝 AI 전문 자막 교정기 (OpenAI 대용량 버전)")
st.markdown("""
빠르고 안정적인 **OpenAI GPT-4o-mini** 모델을 탑재하여, 
**2시간 이상의 긴 자막 파일도 끊김 없이 자동으로 분할 검수**하는 솔루션입니다.
""")

with st.sidebar:
    st.header("📌 이용 가이드")
    st.markdown("""
    **1. 파일 업로드**
    지원되는 형식(.smi, .srt, .txt)의 자막 파일을 화면에 끌어다 놓으세요.
    
    **2. 검수 시작**
    파일 길이가 길어도 시스템이 자동으로 400줄씩 분할하여 연속으로 검수를 진행합니다.
    
    **3. 결과 확인 및 활용**
    모든 파트의 검수가 완료되면 하단의 '다운로드' 버튼을 눌러 전체 문서를 저장하세요.
    """)

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

    # --- 6. 대용량 교정 실행 로직 (자동 분할 및 연속 스트리밍) ---
    if st.button("🚀 AI 자막 검수 시작", type="primary", use_container_width=True):
        ui_container = st.empty()
        
        try:
            with ui_container.container():
                st.divider()
                st.subheader("📊 전체 검수 및 교정 결과")
                
                # 파일을 400줄(약 10~15분) 단위로 쪼갬
                chunks = split_text_into_chunks(file_content, lines_per_chunk=400)
                
                # 여러 개의 분할된 요청을 하나의 스트림으로 매끄럽게 이어붙이는 함수
                def stream_all_chunks():
                    for i, chunk in enumerate(chunks):
                        yield f"\n\n### 🔄 파트 {i+1} / {len(chunks)} 진행 중...\n\n"
                        
                        response_stream = client.chat.completions.create(
                            model=MODEL_ID,
                            messages=[
                                {"role": "system", "content": SYSTEM_INSTRUCTION},
                                {"role": "user", "content": f"--- 자막 내용 ---\n{chunk}\n\n[중요] 자막 내용의 시작부터 마지막 줄까지 절대 생략하거나 멈추지 말고, 누락 없이 모든 오류를 검수 표로 작성해 주세요."}
                            ],
                            temperature=0.2,
                            max_tokens=16000,
                            stream=True
                        )
                        
                        for chunk_resp in response_stream:
                            content = chunk_resp.choices[0].delta.content
                            if content is not None:
                                yield content
                        
                        yield "\n\n---\n"
                
                # 화면에 실시간으로 연속 출력
                with st.spinner("AI가 자막을 분석하고 있습니다... (대용량 파일은 순차적으로 처리됩니다)"):
                    full_text = st.write_stream(stream_all_chunks)
                
                # 전체 출력이 끝나면 단일 파일로 다운로드 버튼 생성
                st.download_button(
                    label="📥 전체 검수 결과 다운로드 (.md)",
                    data=full_text,
                    file_name=f"검수결과_{uploaded_file.name}.md",
                    mime="text/markdown",
                    use_container_width=True
                )
                
        except Exception as e:
            ui_container.empty()
            st.error(f"❌ API 호출 중 오류가 발생했습니다: {e}")
