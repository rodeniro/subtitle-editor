from openai import OpenAI
import re
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
1. 대사 없는 행 제외: 텍스트(대사) 내용이 아예 없거나 공백, 혹은 단순 태그(`&nbsp;` 등)만 있어서 실제 발화 대사가 없는 행은 **출력에서 제외(스킵)**하세요. 오직 실제 대사가 존재하는 행만 처리해야 합니다.
2. 타임코드 형식 준수: 검출된 행의 타임코드는 보기 쉬운 시:분:초(HH:MM:SS) 형식으로 첫 번째 열에 작성하세요.
3. 1:1 대응 유지: 대사가 있는 행들에 대해서는 입력된 순서와 개수를 정확히 유지하여 싱크가 어긋나지 않도록 하세요.
4. 결과물 형식: 반드시 [타임코드 | 원본 | 수정 제안 | 사유] 형식의 마크다운 표로만 출력하세요.
5. <br> 태그 및 특수문자 유지: 줄바꿈용 `<br>` 태그는 삭제하지 말고 그대로 두세요.
6. 마침표(.) 금지: 문장 끝에 마침표를 찍지 마세요 (물음표, 느낌표는 허용).
"""


def format_milliseconds_to_hms(ms):
  """밀리초(ms)를 시:분:초 형태로 변환합니다."""
  total_seconds = int(ms) // 1000
  hours = total_seconds // 3600
  minutes = (total_seconds % 3600) // 60
  seconds = total_seconds % 60
  return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def parse_srt_time_to_hms(srt_time_str):
  """SRT 타임코드(00:00:00,000)를 시:분:초 형태로 변환합니다."""
  match = re.match(r"(\d{2}:\d{2}:\d{2})", srt_time_str)
  if match:
    return match.group(1)
  return srt_time_str


def split_subtitles_by_cue(text):
  """자막 파일(.smi, .srt, .txt)을 싱크 단위(Cues)로 정확하게 파싱하여 분할합니다."""
  lines = text.split("\n")
  cues = []
  current_cue = []

  for line in lines:
    stripped = line.strip()
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

  chunk_size = 30
  cleaned_cues = [c for c in cues if c.strip()]
  chunks = []

  for i in range(0, len(cleaned_cues), chunk_size):
    chunks.append("\n".join(cleaned_cues[i : i + chunk_size]))

  return chunks


# --- 4. 웹앱 UI 구성 ---
st.title("📝 AI 전문 자막 교정기 (싱크 밀림 방지 정밀 버전)")
st.markdown("""
자막의 개별 싱크 단위를 엄격하게 고정하여 **대사가 없는 빈 행은 깔끔하게 제외하고 정확하게 교정**합니다.
""")

with st.sidebar:
  st.header("📌 이용 가이드")
  st.markdown("""
    **1. 파일 업로드**
    지원되는 형식(.smi, .srt, .txt)의 자막 파일을 업로드하세요.
    
    **2. 정밀 검수 시작**
    대사가 존재하는 행들만 추출되어 `시:분:초` 표 형태로 실시간 출력됩니다.
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
1. 텍스트(대사)가 아예 없거나 공백, 혹은 무의미한 태그만 있는 행은 **절대 출력하지 말고 제외**하세요. 오직 실제 대사가 있는 행만 표의 행으로 작성하세요.
2. 각 자막 블록의 타임코드를 추출하여 첫 번째 열인 '타임코드' 칸에 보기 쉬운 **시:분:초(HH:MM:SS)** 형식으로 작성하세요.
3. 테이블 헤더(|타임코드|원본|수정 제안|사유|)는 출력하지 말고, 오직 내용에 해당하는 행(|...|)들만 작성하세요.
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
                header_markdown + "".join(all_markdown_chunks) + chunk_accumulated
            )
            result_placeholder.markdown(temp_full)

        if chunk_accumulated.strip():
          all_markdown_chunks.append(chunk_accumulated.strip() + "\n")

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
