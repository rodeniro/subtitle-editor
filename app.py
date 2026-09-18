from openai import OpenAI
import streamlit as st

# --- 1. 페이지 기본 설정 ---
st.set_page_config(
    page_title="AI 자막 교정기 (완벽 마무리 버전)", page_icon="📝", layout="wide"
)

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
MODEL_ID = "gpt-4o-mini"

SYSTEM_INSTRUCTION = """
당신은 최고 수준의 전문 자막 교정자입니다. 업로드된 파일의 텍스트를 분석하여 오탈자, 띄어쓰기, 문맥 오류를 철저히 검수해 주세요.

아래의 [검수 및 중요 자막 정책]을 엄격히 준수하여 작업을 수행해야 합니다.

[검수 및 중요 자막 정책]
1. 결과물 출력 형식: 반드시 [타임코드(시:분:초) | 원본 | 수정 제안 | 사유] 순서의 마크다운 표 형식으로만 작성해 주세요. 불필요한 서론이나 맺음말은 절대 작성하지 마세요.
2. 타임코드 표기 (시:분:초): SMI/SRT 파일의 타임코드(밀리초 등)를 그대로 노출하지 말고, 반드시 "시:분:초" (예: 01:12:30 또는 00:05:15) 형식으로 변환하여 표의 타임코드 열에 기재해 주세요.
3. <br> 태그 예외 처리: 자막 내에 포함된 `<br>` 코드는 줄바꿈을 의미하는 정상적인 코드입니다. 이를 오류로 잡거나 임의로 삭제하지 말고 그대로 유지한 상태에서 텍스트만 교정하세요.
4. 표현의 보존: 구어체나 사투리는 상황 및 영상의 문맥에 맞게 최대한 보존하며, 명백한 맞춤법 및 문맥 오류만 교정해 주세요.
5. 마침표(.) 사용 금지 (매우 중요): 문장 끝에는 절대 마침표(.)를 찍지 말고, 원본에 마침표가 없다고 해서 이를 오류로 잡지도 마세요. (단, 문맥에 따라 물음표(?)나 느낌표(!)는 허용됩니다.)
6. 중간 끊김 방지: 주어진 텍스트의 끝까지 빠짐없이 모두 검수하여 표로 완성해야 합니다. 절대 중간에 임의로 출력을 끊지 마세요.
"""


def split_text_safely(text, target_lines=250):
  """긴 자막을 안전하게 분할 (토큰 초과 방지를 위해 크기를 250줄로 최적화)"""
  lines = text.split("\n")
  chunks = []
  current_chunk = []

  for line in lines:
    if len(current_chunk) >= target_lines:
      strip_line = line.strip().upper()
      if (
          strip_line == ""
          or strip_line.startswith("<SYNC")
          or strip_line.isdigit()
      ):
        chunks.append("\n".join(current_chunk))
        current_chunk = []

    current_chunk.append(line)

  if current_chunk:
    chunks.append("\n".join(current_chunk))

  return chunks


# --- 4. 웹앱 UI 구성 ---
st.title("📝 AI 전문 자막 교정기 (완벽 마무리 버전)")
st.markdown("""
긴 자막 파일도 중간에 끊김 없이 **끝까지 완벽하게** 검수하는 솔루션입니다.
""")

with st.sidebar:
  st.header("📌 이용 가이드")
  st.markdown("""
    **1. 파일 업로드**
    지원되는 형식(.smi, .srt, .txt)의 자막 파일을 업로드하세요.
    
    **2. 검수 시작**
    버튼을 누르면 파트별로 나누어 순차적으로 끝까지 안전하게 검수합니다.
    """)

# --- 5. 세션 상태 초기화 ---
if "accumulated_result" not in st.session_state:
  st.session_state.accumulated_result = ""

# --- 6. 파일 업로드 및 처리 ---
uploaded_file = st.file_uploader(
    "자막 파일을 업로드하세요 (지원 형식: .smi, .srt, .txt)",
    type=["smi", "srt", "txt"],
)

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
    st.text(
        file_content[:1000]
        + ("\n\n...(이하 생략)" if len(file_content) > 1000 else "")
    )

  # --- 7. 대용량 교정 실행 로직 ---
  if st.button("🚀 AI 자막 검수 시작", type="primary", use_container_width=True):
    st.session_state.accumulated_result = ""
    chunks = split_text_safely(file_content, target_lines=250)

    st.divider()
    st.subheader("📊 전체 검수 및 교정 결과")

    result_placeholder = st.empty()

    try:
      for i, chunk in enumerate(chunks):
        st.toast(
            f"🔄 자막 검수 진행 중... (파트 {i+1} / 총 {len(chunks)} 파트)"
        )

        if i == 0:
          prompt = f"--- 자막 내용 (파트 {i+1}/{len(chunks)}) ---\n{chunk}\n\n[중요] 처음부터 빠짐없이 검수를 시작해 주세요. 반드시 마크다운 표 형식(첫 줄 표 헤더 포함)으로 출력하세요."
        else:
          prompt = f"--- 자막 내용 (파트 {i+1}/{len(chunks)}) ---\n{chunk}\n\n[중요] 이전 파트에서 바로 이어지는 자막입니다. **표의 헤더(|타임코드|원본|...|)는 절대 다시 작성하지 말고**, 이전 표에 이어지도록 데이터 행(|01:12:30|...|)부터 연속해서 바로 기재하세요. 본 파트의 마지막 줄까지 누락 없이 끝까지 작성해 주세요."

        response_stream = client.chat.completions.create(
            model=MODEL_ID,
            messages=[
                {"role": "system", "content": SYSTEM_INSTRUCTION},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,  # 문맥 변동을 줄이고 안정적인 출력을 위해 낮춤
            max_tokens=16000,
            stream=True,
        )

        chunk_accumulated = ""
        for chunk_resp in response_stream:
          content = chunk_resp.choices[0].delta.content
          if content is not None:
            chunk_accumulated += content
            result_placeholder.markdown(
                st.session_state.accumulated_result + chunk_accumulated
            )

        # 각 파트 완료 시 줄바꿈 추가하여 누적
        st.session_state.accumulated_result += chunk_accumulated + "\n"
        result_placeholder.markdown(st.session_state.accumulated_result)

      st.toast("✅ 전체 자막 검수가 완벽하게 완료되었습니다!", icon="🎉")

    except Exception as e:
      st.error(f"❌ API 호출 중 오류가 발생했습니다: {e}")

  # 검수 결과가 남아있을 경우 화면에 계속 유지
  elif st.session_state.accumulated_result:
    st.divider()
    st.subheader("📊 전체 검수 및 교정 결과")
    st.markdown(st.session_state.accumulated_result)
