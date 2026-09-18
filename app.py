from openai import OpenAI
import streamlit as st

# --- 1. 페이지 기본 설정 ---
st.set_page_config(
    page_title="AI 자막 교정기 (연속 누적 버전)", page_icon="📝", layout="wide"
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
2. 타임코드 순서 유지 (매우 중요): 입력된 자막의 시간 순서(과거 -> 미래)를 완벽하게 유지하여 위에서부터 아래로 순차적으로 출력해야 합니다. 타임코드가 '0:00:00' 등으로 초기화되거나 뒤죽박죽이 되면 안 됩니다.
3. 실제 등장하는 대사 보존: 원본 자막에 동일한 대사가 실제로 반복해서 등장한다면, 검수 결과에서도 누락하지 말고 각각의 타임코드에 맞춰 모두 표출해 주세요.
4. 타임코드 표기 (시:분:초): SMI/SRT 파일의 타임코드(밀리초 등)를 그대로 노출하지 말고, 반드시 "시:분:초" (예: 01:12:30 또는 00:05:15) 형식으로 변환하여 표의 타임코드 열에 기재해 주세요.
5. <br> 태그 예외 처리: 자막 내에 포함된 `<br>` 코드는 줄바꿈을 의미하는 정상적인 코드입니다. 이를 오류로 잡거나 임의로 삭제하지 말고 그대로 유지한 상태에서 텍스트만 교정하세요.
6. 표현의 보존: 구어체나 사투리는 상황 및 영상의 문맥에 맞게 최대한 보존하며, 명백한 맞춤법 및 문맥 오류만 교정하세요.
7. 마침표(.) 사용 금지 (매우 중요): 문장 끝에는 절대 마침표(.)를 찍지 말고, 원본에 마침표가 없다고 해서 이를 오류로 잡지도 마세요. (단, 문맥에 따라 물음표(?)나 느낌표(!)는 허용됩니다.)
"""


def split_subtitles_naturally(text, block_size=70):
  """자막의 시간 흐름이 깨지지 않도록 자연스럽게 블록 단위로 분할합니다."""
  lines = text.split("\n")
  blocks = []
  current_block = []

  for line in lines:
    if (
        line.strip().upper().startswith("<SYNC")
        or line.strip().isdigit()
        or line.strip() == ""
    ):
      if current_block:
        blocks.append("\n".join(current_block))
        current_block = []
    current_block.append(line)

  if current_block:
    blocks.append("\n".join(current_block))

  cleaned_blocks = [b for b in blocks if b.strip()]

  chunks = []
  for i in range(0, len(cleaned_blocks), block_size):
    chunk_blocks = cleaned_blocks[i : i + block_size]
    chunks.append("\n".join(chunk_blocks))

  return chunks


# --- 4. 웹앱 UI 구성 ---
st.title("📝 AI 전문 자막 교정기 (연속 누적 버전)")
st.markdown("""
긴 자막을 파트별로 나누어 처리하되, **이전 검수 결과는 그대로 유지한 채 타임코드 순서대로 아래에 계속 이어서** 출력하는 솔루션입니다.
""")

with st.sidebar:
  st.header("📌 이용 가이드")
  st.markdown("""
    **1. 파일 업로드**
    지원되는 형식(.smi, .srt, .txt)의 자막 파일을 업로드하세요.
    
    **2. 검수 시작**
    모든 대사가 누락 없이 시간 순서대로 안전하게 누적 출력됩니다.
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
    chunks = split_subtitles_naturally(file_content, block_size=70)

    st.divider()
    st.subheader("📊 전체 검수 및 교정 결과")

    result_placeholder = st.empty()

    try:
      for i, chunk in enumerate(chunks):
        st.toast(
            f"🔄 자막 검수 진행 중... (파트 {i+1} / 총 {len(chunks)} 파트)"
        )

        if i == 0:
          prompt = f"""--- 자막 내용 (파트 {i+1}/{len(chunks)}) ---
{chunk}

[중요 지침]
1. 위 자막의 타임코드와 대사를 시간 순서(과거 -> 미래)대로 정확히 분석하여 표를 만드세요.
2. 원본 대사가 실제로 반복된다면 누락하지 말고 모두 표출하세요.
3. 반드시 마크다운 표 형식(첫 줄 표 헤더 포함)으로 출력하세요.
"""
        else:
          prompt = f"""--- 자막 내용 (파트 {i+1}/{len(chunks)}) ---
{chunk}

[중요 지침]
1. 이 자막은 이전 파트의 시간대 바로 뒤에 이어지는 다음 시간대의 자막입니다.
2. **표의 헤더(|타임코드|원본|...|)는 절대 다시 작성하지 말고**, 이전 표 내용에 바로 이어지도록 새로운 데이터 행들만 연속해서 작성하세요.
3. 타임코드와 대사 흐름이 시간순으로 자연스럽게 이어지도록 하세요.
"""

        response_stream = client.chat.completions.create(
            model=MODEL_ID,
            messages=[
                {"role": "system", "content": SYSTEM_INSTRUCTION},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=16000,
            stream=True,
        )

        chunk_accumulated = ""
        for chunk_resp in response_stream:
          content = chunk_resp.choices[0].delta.content
          if content is not None:
            chunk_accumulated += content
            # 이전 결과물 뒤에 현재 청크의 스트리밍 내용을 실시간으로 붙여서 표시
            result_placeholder.markdown(
                st.session_state.accumulated_result + chunk_accumulated
            )

        # 한 파트가 완전히 끝나면 전체 누적 변수에 확정 저장
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
