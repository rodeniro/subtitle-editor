from openai import OpenAI
import streamlit as st

# --- 1. 페이지 기본 설정 ---
st.set_page_config(
    page_title="AI 자막 교정기 (싱크 밀림 방지 정밀 버전)",
    page_icon="📝",
    layout="wide",
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
당신은 완벽한 타임코드 싱크 매칭을 보장하는 전문 자막 교정자입니다. 
업로드된 자막의 타임라인과 텍스트를 분석하여 오탈자, 띄어쓰기, 문맥 오류를 검수합니다.

[핵심 검수 원칙 (매우 중요)]
1. 타임코드 절대 변경 금지: 입력된 각 행의 타임코드(시:분:초)는 임의로 수정, 이동, 생성할 수 없습니다. 원본의 타임코드를 그대로 유지하세요.
2. 1:1 대응 유지: 입력된 자막의 개수와 순서 그대로 결과가 나와야 하며, 임의로 문장을 합치거나 누락해서는 안 됩니다.
3. 결과물 형식: 반드시 [타임코드 | 원본 | 수정 제안 | 사유] 형식의 마크다운 표로만 출력하세요. (불필요한 인사말이나 서론 금지)
4. <br> 태그 및 특수문자 유지: 줄바꿈용 `<br>` 태그는 삭제하지 말고 그대로 두세요.
5. 마침표(.) 금지: 문장 끝에 마침표를 찍지 마세요 (물음표, 느낌표는 허용).
"""


def split_subtitles_by_cue(text):
  """자막 파일(.smi, .srt, .txt)을 싱크 단위(Cues)로 정확하게 파싱하여 분할합니다."""
  lines = text.split("\n")
  cues = []
  current_cue = []

  for line in lines:
    stripped = line.strip()
    # 새로운 자막 블록의 시작점 감지 (<SYNC>, SRT 숫자 번호 등)
    if (
        stripped.upper().startswith("<SYNC")
        or "-->" in stripped
        or (stripped.isdigit() and len(current_cue) > 2)
    ):
      if current_cue:
        cues.append("\n".join(current_cue))
        current_cue = []
    current_cue.append(line)

  if current_cue:
    cues.append("\n".join(current_cue))

  # 30개 단위로 묶어서 청크 구성 (싱크 밀림을 방지하기 위해 적정 크기 유지)
  chunk_size = 30
  cleaned_cues = [c for c in cues if c.strip()]
  chunks = []

  for i in range(0, len(cleaned_cues), chunk_size):
    chunks.append("\n".join(cleaned_cues[i : i + chunk_size]))

  return chunks


# --- 4. 웹앱 UI 구성 ---
st.title("📝 AI 전문 자막 교정기 (싱크 밀림 방지 정밀 버전)")
st.markdown("""
자막의 개별 싱크 단위를 엄격하게 고정하여 **타임라인 밀림이나 누락 없이 정확하게 1:1 교정**을 수행합니다.
""")

with st.sidebar:
  st.header("📌 이용 가이드")
  st.markdown("""
    **1. 파일 업로드**
    지원되는 형식(.smi, .srt, .txt)의 자막 파일을 업로드하세요.
    
    **2. 정밀 검수 시작**
    타임라인 싱크가 완벽히 보존된 교정 결과 마크다운 표가 실시간으로 출력됩니다.
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
        + ("\n\n...(이후 생략)" if len(file_content) > 1000 else "")
    )

  # --- 7. 교정 실행 로직 ---
  if st.button("🚀 정밀 자막 검수 시작", type="primary", use_container_width=True):
    st.session_state.accumulated_result = ""

    # 싱크 단위별로 안전하게 쪼개기
    chunks = split_subtitles_by_cue(file_content)

    st.divider()
    st.subheader("📊 전체 검수 및 교정 결과")

    result_placeholder = st.empty()

    try:
      all_markdown_chunks = []
      header_markdown = (
          "| 타임코드 | 원본 | 수정 제안 | 사유 |\n|:---:|:---:|:---:|:---:|\n"
      )

      for i, chunk in enumerate(chunks):
        st.toast(
            f"🔄 정밀 검수 진행 중... (파트 {i+1} / 총 {len(chunks)} 파트)"
        )

        prompt = f"""--- 자막 데이터 조각 (파트 {i+1}/{len(chunks)}) ---
{chunk}

[엄격한 지침]
1. 제공된 자막 조각의 타임코드를 **절대 변경하거나 임의로 재조합하지 말고 그대로 사용**하세요.
2. 테이블 헤더(|타임코드|원본|수정 제안|사유|)는 출력하지 말고, 오직 내용에 해당하는 행(|...|)들만 작성하세요.
3. 입력된 순서와 개수를 정확히 유지하여 싱크가 어긋나지 않도록 하세요.
"""

        response_stream = client.chat.completions.create(
            model=MODEL_ID,
            messages=[
                {"role": "system", "content": SYSTEM_INSTRUCTION},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=4000,
            stream=True,
        )

        chunk_accumulated = ""
        for chunk_resp in response_stream:
          content = chunk_resp.choices[0].delta.content
          if content is not None:
            chunk_accumulated += content
            temp_full = (
                header_markdown
                + "".join(all_markdown_chunks)
                + chunk_accumulated
            )
            result_placeholder.markdown(temp_full)

        all_markdown_chunks.append(chunk_accumulated + "\n")
        st.session_state.accumulated_result = (
            header_markdown + "".join(all_markdown_chunks)
        )
        result_placeholder.markdown(st.session_state.accumulated_result)

      st.toast("✅ 정밀 자막 검수가 완벽하게 완료되었습니다!", icon="🎉")

    except Exception as e:
      st.error(f"❌ API 호출 중 오류가 발생했습니다: {e}")

  # 결과 유지
  elif st.session_state.accumulated_result:
    st.divider()
    st.subheader("📊 전체 검수 및 교정 결과")
    st.markdown(st.session_state.accumulated_result)
