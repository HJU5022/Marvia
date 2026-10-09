"""LLM 호출의 주소·재시도·상한 같은 설정 값 (services/llm.py에서 옮김). 값만 있고 동작은 없다. 호출은 llm.py 한 곳에서 한다 (CLAUDE.md)."""
from __future__ import annotations

# OpenRouter는 OpenAI와 같은 요청 형식을 받는다. 그래서 openai SDK에 주소만 바꿔 쓴다 (requirements.txt 주석).
BASE_URL = "https://openrouter.ai/api/v1"

# Vertex AI도 OpenAI 형식 주소를 따로 연다. strict json_schema까지 같은 요청으로 통과했다 (curl 확인).
# global 위치를 쓴다: 지역을 고르지 않아도 되고, gemini-2.5-flash 호출이 여기서 됐다
VERTEX_PREFIX = "vertex/"

VERTEX_URL = "https://aiplatform.googleapis.com/v1/projects/{project}/locations/global/endpoints/openapi"

VERTEX_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

# 재시도는 횟수가 아니라 요청당 시간 예산으로 정하기로 했다. 예산 숫자가 정해지기 전까지는
# 최초 1회 + 재시도 1회만 한다. 3회씩 돌리면 사용자가 너무 오래 기다린다.
MAX_ATTEMPTS = 2

# 후속 질문 한 번에 LLM이 도구를 부를 수 있는 횟수(라운드) 상한. 질문 하나에 필요한 도구는 많아야 2~3개다
# (위치 → 거리, 입항 일정). 넘으면 도구 없이 답하게 한다 (_ask_json)
MAX_TOOL_ROUNDS = 3

# 다시 불러 볼 만한 것: 한도 초과(429), 제공사 과부하·게이트웨이(500·502·503).
# 스모크 테스트에서 nemotron 무료가 503 provider_overloaded를 5번 중 3번 냈다.
# 500은 나중에 넣었다. Vertex가 과부하를 500으로 줬고(평가 3.8 Flash B09), _status_kind도 500을 overloaded로
# 분류하는데 재시도만 안 해서 분류와 동작이 어긋나 있었다.
# 타임아웃은 넣지 않는다. 60초를 한 번 더 기다리면 시간 예산을 넘는다.
RETRYABLE_CODES = {429, 500, 502, 503}

# 끝까지 못 쓰고 끊긴 답의 finish_reason. JSON이 깨졌고 이 값이면 _ask_json이 같은 대화로 한 번 더 묻는다.
# None: 끝 신호 없이 스트림이 끊김 (서류 판독). "error": 제공사가 생성 중 오류로 멈춤 (판정 평가 3회, 74번 중 4번)
# length(토큰 한도)와 stop(정상 종료)은 넣지 않는다. 다시 물어도 같은 한도에 닿거나, 형식 문제라 프롬프트로 고쳐야 한다
CUT_FINISH_REASONS = {None, "error"}

# 판정 LLM 입력에서 뺄 통관 칸. B/L(bl_masked)·MRN·조회 시각 외에, 나중에 붙은 포워더·선사·컨테이너 번호도 뺀다:
# 판정에 쓰이지 않고(프롬프트·평가 결과를 그대로 두려고), 컨테이너 번호는 B/L처럼 화물을 특정하는 번호라 LLM에 줄 수 없다.
# 포워더·선사 이름은 채팅 에이전트가 받는다 (services/chat/chat.py _cargo_summary).
# 품명(goods_name)도 판정에 쓰이지 않아 뺀다. 채팅 에이전트만 받는다
JUDGE_CUSTOMS_EXCLUDE = {"bl_masked", "mrn", "fetched_at", "forwarder_name", "carrier_name", "container_no", "goods_name"}

STAGE_SUSPECT = "(단계 이름 확인 필요)"  # 주입 모양 단계명 대신 LLM에 넘기는 글자 (_clean_customs)

REPLAY_LLM_DIR = "llm"  # replay.REPLAY_DIR 아래 폴더. 평가 실행기가 REPLAY_DIR를 바꿔 끼워도 같이 따라간다
