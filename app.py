from datetime import datetime
from io import BytesIO
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
1. 타임코드 절대 변경/조합 금지: 각 행에 지정된 타임코드는 절대 수정하거나 다른 행의 타임코드와 바꾸지 말고 그대로 사용하세요.
2. 1:1 매칭 고정: 입력된 [타임코드 | 원본대사] 세트의 순서와 개수를 완벽하게 유지하세요.
3. 결과물 형식: 반드시 [타임코드 | 원본 | 수정 제안 | 사유] 형식의 마크다운 표 행(|...|...|...|...)으로만 출력하세요. 다른 텍스트나 헤더를 임의로 넣지 마세요.
4. <br> 태그 및 특수문자 유지: 줄바꿈용 `<br>` 태그는 삭제하지 말고 그대로 두세요.
5. 마침표(.) 금지: 문장 끝에 마침표를 찍지 마세요 (물음표, 느낌표는 허용).
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


def parse_subtitles_to_pairs(text):
  """자막 파일을 파싱하여 [타임코드, 대사 텍스트] 쌍의 리스트로 추출합니다.

  대사가 없는 빈 행은 이 단계에서 원천적으로 배제하여 싱크 엇나감을 방지합니다.
  """
  lines = text.split("\n")
  pairs = []
  current_time = "00:00:00"
  current_text_lines = []

  for line in lines:
    stripped = line.strip()

    # SMI 타임코드 감지
    smi_match = re.search(r"Start\s*=\s*(\d+)", line, re.IGNORECASE)
    # SRT 타임코드 감지
    srt_match = re.search(
        r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})",
        line,
    )

    if smi_match or srt_match:
      # 이전 누적된 텍스트가 있다면 페어로 저장
      if current_text_lines:
        text_content = " ".join(current_text_lines).strip()
        # 실제 의미 있는 텍스트가 있는 경우만 추가 (공백, 태그만 있는 경우 제외)
        cleaned_check = re.sub(r"<[^>]+>", "", text_content).strip()
        if cleaned_check and cleaned_check != "&nbsp;":
          pairs.append((current_time, text_content))
        current_text_lines = []

      if smi_match:
        current_time = format_milliseconds_to_hms(int(smi_match.group(1)))
      elif srt_match:
        current_time = parse_srt_time_to_hms(srt_match.group(1))
    else:
      # 태그나 자막 번호 등 불필요한 라인 제외하고 텍스트 누적
      if stripped and not stripped.isdigit() and "-->" not in stripped:
        # HTML 태그나 특수문자만 있는 경우 거름
        current_text_lines.append(line)

  # 마지막 남은 블록 처리
  if current_text_lines:
    text_content = " ".join(current_text_lines).strip()
    cleaned_check = re.sub(r"<[^>]+>", "", text_content).strip()
    if cleaned_check and cleaned_check != "&nbsp;":
      pairs.append((current_time, text_content))

  return pairs


# --- 4. 웹앱 UI 구성 ---
st.title("📝 AI 전문 자막 교정기 (싱크 밀림 방지 정밀 버전)")
st.markdown("""
자막의 개별 싱크와 대사를 엄격하게 묶어 **타임코드 엇갈림 없이 정확하게 1:1 교정**을 수행합니다.
""")

with st.sidebar:
  st.header("📌 이용 가이드")
  st.markdown("""
    **1. 파일 업로드**
    지원되는 형식(.smi, .srt, .txt)의 자막 파일을 업로드하세요.
    
    **2. 정밀 검수 및 백데이터 다운로드**
    싱크가 완벽히 고정된 교정 결과와 함께, 수정 및 재가공용 백데이터(CSV)를 다운로드할 수 있습니다.
    """)

# --- 5. 세션 상태 초기화 ---
if "accumulated_result" not in st.session_state:
  st.session_state.accumulated_result = ""
if "raw_table_data" not in st.session_state:
  st.session_state.raw_table_data = []

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

  # --- 7. 교정 실행 로직 ---
  if st.button("🚀 정밀 자막 검수 시작", type="primary", use_container_width=True):
    st.session_state.accumulated_result = ""
    st.session_state.raw_table_data = []

    # 1단계: 타임코드와 대사를 안전하게 페어링 (대사 없는 행 원천 차단)
    pairs = parse_subtitles_to_pairs(file_content)

    if not pairs:
      st.error(
          "❌ 유효한 자막 대사를 찾지 못했습니다. 파일 형식을 확인해 주세요."
      )
      st.stop()

    # 30개 단위로 청크 분할
    chunk_size = 30
    chunks = []
    for i in range(0, len(pairs), chunk_size):
      chunks.append(pairs[i : i + chunk_size])

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

        # 청크 데이터를 명시적인 텍스트 형태로 조합하여 LLM에 주입
        chunk_text_block = ""
        for time_code, text_val in chunk:
          chunk_text_block += f"[{time_code}] {text_val}\n"

        prompt = f"""--- 자막 데이터 세트 (파트 {i+1}/{len(chunks)}) ---
{chunk_text_block}

[매우 엄격한 지침]
1. 위 데이터의 각 행에 적힌 [타임코드]를 결과 표의 첫 번째 칸에 그대로 사용하세요. 절대 타임코드를 바꾸거나  밀리게 해서는 안 됩니다.
2. 입력된 순서와 개수를 100% 동일하게 유지하여 마크다운 표 행(| 타임코드 | 원본 | 수정 제안 | 사유 |)으로만 작성하세요.
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
          cleaned_chunk_str = chunk_accumulated.strip()
          all_markdown_chunks.append(cleaned_chunk_str + "\n")

          # 백데이터 추출을 위한 행 파싱 저장 로직
          for row_line in cleaned_chunk_str.split("\n"):
            if "|" in row_line:
              cols = [c.strip() for c in row_line.split("|")]
              # 마크다운 표 구조상 양 끝 빈 요소 제거
              cols = [c for c in cols if c != ""]
              if len(cols) >= 4:
                st.session_state.raw_table_data.append(cols)

        st.session_state.accumulated_result = (
            header_markdown + "".join(all_markdown_chunks)
        )
        result_placeholder.markdown(st.session_state.accumulated_result)

      st.toast("✅ 정밀 자막 검수가 완벽하게 완료되었습니다!", icon="🎉")

    except Exception as e:
      st.error(f"❌ API 호출 중 오류가 발생했습니다: {e}")

  # 결과 유지 및 백데이터 다운로드 제공
  elif st.session_state.accumulated_result:
    st.divider()
    st.subheader("📊 전체 검수 및 교정 결과")
    st.markdown(st.session_state.accumulated_result)

# --- 8. 백데이터 다운로드 버튼 (요청 사항 반영) ---
if st.session_state.raw_table_data:
  st.markdown("---")
  st.subheader("📥 교정 백데이터(수정 가능 데이터) 다운로드")
  st.markdown(
      "차트 및 자막 검수 결과를 엑셀이나 스프레드시트에서 자유롭게 수정하고"
      " 활용할 수 있도록 CSV 백데이터로 제공합니다."
  )

  # CSV 데이터 생성
  csv_content = "타임코드,원본,수정 제안,사유\n"
  for row in st.session_state.raw_table_data:
    # 쉼표나 따옴표 깨짐 방지를 위해 쌍따옴표 래핑
    escaped_row = [f'"{col.replace('"', '""')}"' for col in row[:4]]
    csv_content += ",".join(escaped_row) + "\n"

  # 한글 깨짐 방지용 BOM 추가하여 바이너리 변환
  csv_bytes = csv_content.encode("utf-8-sig")

  st.download_button(
      label="💾 교정 백데이터(CSV) 다운로드",
      data=csv_bytes,
      file_name=f"subtitle_correction_backdata_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
      mime="text/csv",
      type="secondary",
      use_container_width=True,
  )
