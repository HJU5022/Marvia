"""LLM 호출은 이 파일 하나로 모읍니다 (작업 C-6, SDD 1.1).

라우터나 UI 코드가 openai를 직접 import하지 않게 하세요.
3차에서 이 파일 내부만 갈아끼우면 나머지는 그대로 돌아갑니다.

여기서 책임지는 것:
  - 출력 형식 검사 (Pydantic)          ← judge()가 JSON 모양만 본다. 내용 7규칙은 C-7 validate.py
  - 실패 시 재시도와 폴백, 라우팅       ← 재시도 1회만 있음. 폴백·라우팅·요청당 시간 예산은 TODO (09-23 결정)
  - Langfuse 트레이스 남기기            ← _ask_json()이 호출마다 generation 하나 (observability/langfuse.py, SDD 5.11)

지금 있는 것:
  chat()   OpenRouter(또는 Vertex AI)에 한 번 묻는다. 과부하·한도(503·429)면 한 번 더 묻는다
  judge()            2층 판정. 프롬프트(Langfuse) + skills/ 문서 + 코드가 모은 자료를 주고 판정 JSON을 받는다 (SDD 4.1 7단계, 5.6)
  pick_vessel()      이름 같은 후보가 여럿일 때 어느 배인지 고른다 (SDD 5.5, C-5)
  answer_follow_up() 판정 뒤 후속 질문에 근거 안에서만 답한다 (C-9)
  extract_doc_fields() 서류 사진 OCR 글자에서 선명·항차·ETA 등 6칸과 B/L 조건·연락처를 옮겨 적는다 (docs/specs/document-extract.md)
  write_memory()     조회·대화 뒤 메모장에 줄 단위 명령만 낸다. 적용은 services/memory.py가 한다 (docs/specs/memory.md)

모델 자리 (.env, 계약 C8):
  LLM_MODEL           서비스가 쓰는 모델. 위 네 함수 전부 (09-30 이름 바꿈, 전 MODEL_A)
  MEMORY_MODEL        기억 뽑기(write_memory)만. 비어 있으면 기억 뽑기를 건너뛴다 (10-02 결정 10, 계획 gpt-4o-mini)
  EVAL_COMPARE_MODEL  평가에서 비교할 두 번째 모델. run_eval --config c에서만 LLM_MODEL 자리에 들어간다 (전 MODEL_B)
  EVAL_GRADER_MODEL   평가 채점자. 통관 해설 채점(grade_customs)만. 채점받는 모델과 달라야 한다 (전 JUDGE_MODEL.
                      판정 함수 judge()와 헷갈려서 바꿈)

어디로 보내나 (모델 이름 앞머리로 가른다, 09-28):
  "vertex/"로 시작   Vertex AI (GCP 크레딧). 예: LLM_MODEL=vertex/google/gemini-2.5-flash
                     키 대신 `gcloud auth application-default login` 로그인 정보(ADC)를 쓴다.
                     Cloud Run에서는 서비스 계정에 Vertex AI 사용자 권한이 있어야 한다
                     VERTEX_THINKING_BUDGET=0이면 Gemini가 생각 없이 바로 답한다. 비우면 모델 기본값 (_vertex_thinking)
  그 밖             OpenRouter. 예: LLM_MODEL=openai/gpt-4o-mini
  개발 중엔 크레딧(vertex/)으로 돌리고, 최종 테스트 때 .env 한 줄만 되돌리려고 두 길을 같이 둔다.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Literal, get_args

import openai
from openai import OpenAI
from pydantic import BaseModel, ValidationError

from backend.app.clients import replay  # REPLAY_MODE 녹화 답 재생 (_replay_answer)
from backend.app.services import quota  # 1명당 하루 토큰 한도 (docs/specs/token-quota.md)
from backend.app.observability.langfuse import end_generation, end_web_search, get_prompt, start_generation
from backend.app.schemas.agent import AgentResponse, Conflict, Evidence, Reason, VesselCandidate, Verdict
from backend.app.schemas.customs import CustomsRecord
from backend.app.schemas.signals import SignalSet
from backend.app.services.evidence import KST  # 판정 입력의 날짜를 근거 카드와 같은 한국 시각으로 (09-29 D8)
from backend.app.services import guard  # 통관 단계명 주입 거르기 (_clean_customs, 10-01)
from backend.app.services.signals import needs_broker  # 관세사 필요 여부는 코드가 정해 입력으로 준다 (10-01)

# OpenRouter는 OpenAI와 같은 요청 형식을 받는다. 그래서 openai SDK에 주소만 바꿔 쓴다 (requirements.txt 주석).
BASE_URL = "https://openrouter.ai/api/v1"
# Vertex AI도 OpenAI 형식 주소를 따로 연다. strict json_schema까지 같은 요청으로 통과했다 (09-28 curl 확인).
# global 위치를 쓴다: 지역을 고르지 않아도 되고, 09-28 gemini-2.5-flash 호출이 여기서 됐다
VERTEX_PREFIX = "vertex/"
VERTEX_URL = "https://aiplatform.googleapis.com/v1/projects/{project}/locations/global/endpoints/openapi"
VERTEX_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
TIMEOUT_SEC = 60.0  # 호출 하나가 요청 전체 시간을 다 먹지 않게 하는 상한. p95 실측 뒤 조정

# 재시도는 횟수가 아니라 요청당 시간 예산으로 정하기로 했다 (09-23 결정). 예산 숫자가 정해지기 전까지는
# 최초 1회 + 재시도 1회만 한다. 3회씩 돌리면 사용자가 너무 오래 기다린다.
MAX_ATTEMPTS = 2
# 후속 질문 한 번에 LLM이 도구를 부를 수 있는 횟수(라운드) 상한 (10-02). 질문 하나에 필요한 도구는 많아야 2~3개다
# (위치 → 거리, 입항 일정). 넘으면 도구 없이 답하게 한다 (_ask_json)
MAX_TOOL_ROUNDS = 3
RETRY_WAIT_SEC = 2.0  # 과부하는 잠깐 뒤 풀리는 경우가 많다. 실측 전 임시값
# 다시 불러 볼 만한 것: 한도 초과(429), 제공사 과부하·게이트웨이(500·502·503).
# 09-23 스모크 테스트에서 nemotron 무료가 503 provider_overloaded를 5번 중 3번 냈다.
# 500은 09-29에 넣었다. Vertex가 과부하를 500으로 줬고(평가 3.8 Flash B09), _status_kind도 500을 overloaded로
# 분류하는데 재시도만 안 해서 분류와 동작이 어긋나 있었다.
# 타임아웃은 넣지 않는다. 60초를 한 번 더 기다리면 시간 예산을 넘는다.
RETRYABLE_CODES = {429, 500, 502, 503}

logger = logging.getLogger(__name__)


@dataclass
class LLMResult:
    """chat() 결과. 로그 4필드(요청 ID·모델·토큰·지연, 작업 A5)를 같이 들고 다닌다."""

    content: str | None                 # 모델이 쓴 본문. tool을 부르면 비어 있을 수 있다
    tool_calls: list[dict] = field(default_factory=list)  # [{"id": ..., "name": ..., "arguments": "<JSON 문자열>"}]
    model: str = ""                     # 실제로 답한 모델
    provider: str | None = None         # OpenRouter가 보낸 제공사. 무료 모델은 한 곳뿐인 경우가 많다
    request_id: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: int = 0                 # 마지막 시도 하나의 지연. 재시도 대기는 빠진다
    attempts: int = 1                   # 몇 번 만에 답을 받았나. Langfuse retry_count 자리 (SDD 5.11)
    # 입력 중 제공사 캐시에서 읽은 토큰. 프롬프트 + Skill처럼 매번 같은 앞부분이 자동 캐시된다 (09-30 확인: Vertex
    # Gemini 2.5 Flash 판정 입력 4,348 중 두 번째 호출부터 3,514). 요청 옵션 없이 응답 usage.prompt_tokens_details에 온다
    cached_tokens: int | None = None
    cost: float | None = None           # OpenRouter가 응답 usage.cost에 준 실제 금액 (크레딧 = USD). 무료 모델은 0. Vertex는 안 줘서 None
    finish_reason: str | None = None    # "length"면 토큰 한도에서 잘린 답. 형식 오류와 구분한다 (truncated)


class LLMError(Exception):
    """OpenRouter·Vertex AI가 답 대신 에러를 준 경우. code가 RETRYABLE_CODES면 chat()이 한 번 더 부른다.

    kind는 실패 종류다. 로그(log_failure)에 코드 대신 이 이름을 남긴다. 해결책이 종류마다 달라서 나눈다
    (09-29 평가 c에서 qwen 무료가 21건 실패했는데 429 말고는 왜 실패했는지 알 수 없었다).
      rate_limited  429 요청이 너무 잦음        overloaded  5xx 제공사 과부하
      auth          401·403·Vertex 로그인 문제   bad_request 그 밖의 4xx (요청 모양·지원 안 하는 옵션)
      connection    연결 실패                   no_choices  200인데 답 없이 error만 옴
      timeout       TIMEOUT_SEC 안에 답이 없음 (전체 시간 상한, _create_with_deadline)
      not_configured 모델 이름이 설정에 없음
      truncated·bad_format은 LLMFormatError 쪽 (답은 왔는데 쓸 수 없음)
    """

    def __init__(self, message: str, code: int | None = None, latency_ms: int = 0, kind: str = "unknown"):
        super().__init__(message)
        self.code = code
        self.latency_ms = latency_ms
        self.kind = kind

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE_CODES


class LLMFormatError(LLMError):
    """LLM이 답은 했는데 JSON이 아니거나 필수 칸이 빠지는 등 모양이 스키마와 다른 경우.

    호출 실패(네트워크·키·과부하)와 구분한다. 라우터는 이것을 규칙 위반처럼 보고 무엇이 틀렸는지 붙여 다시 묻는다.
    세 번 다 깨지면 failed다 (09-28 결정, SDD 5.7 "3단계 재시도 뒤 failed", 평가셋 F08).
    LLMError를 물려받으므로 이것을 따로 잡지 않는 곳(pick_vessel·후속 질문)은 지금처럼 LLM 실패로 처리한다.
    """

    def __init__(self, message: str, detail: str, kind: str = "bad_format"):
        super().__init__(message, kind=kind)
        self.detail = detail  # LLM에 다시 물을 때 붙일 설명 (영어, 프롬프트와 같은 언어)


def _client() -> OpenAI:
    # 키는 호출할 때 읽는다. import 시점에 .env가 아직 안 읽혔을 수 있어서 (clients/*.py와 같은 방식).
    # max_retries=0: openai SDK는 기본으로 몰래 2번 재시도한다. 재시도는 아래 chat()이 한 곳에서만 한다.
    # 키가 없으면 KeyError로 서버가 500을 내는 대신 LLMError로 올린다. 라우터가 판정 없이 partial로 돌려준다 (09-23 결정)
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise LLMError("OPENROUTER_API_KEY가 없습니다")
    return OpenAI(base_url=BASE_URL, api_key=key, timeout=TIMEOUT_SEC, max_retries=0)


# google-auth 자격 증명과 프로젝트. 처음 한 번만 읽고, 토큰(1시간짜리)이 만료되면 refresh만 한다
_vertex_creds = None
_vertex_project: str | None = None


def _vertex_client() -> OpenAI:
    """Vertex AI의 OpenAI 형식 주소로 가는 클라이언트. API 키 자리에 Google 액세스 토큰을 넣는다.

    google.auth는 여기서만 import한다. OpenRouter만 쓰는 사람은 google-auth가 없어도 서버가 뜬다.
    로그인 정보가 없거나 토큰을 못 받으면 _client()와 같이 LLMError로 올린다 (09-23 결정, partial 경로).
    """
    global _vertex_creds, _vertex_project
    import google.auth
    import google.auth.exceptions
    import google.auth.transport.requests

    try:
        if _vertex_creds is None:
            # 프로젝트는 GOOGLE_CLOUD_PROJECT가 있으면 그것, 없으면 ADC에 기록된 quota project (google.auth.default 순서)
            _vertex_creds, _vertex_project = google.auth.default(scopes=VERTEX_SCOPES)
        if not _vertex_creds.valid:
            _vertex_creds.refresh(google.auth.transport.requests.Request())
    except google.auth.exceptions.GoogleAuthError as e:
        raise LLMError(f"Vertex AI 로그인 정보 없음 또는 토큰 발급 실패: {type(e).__name__}", kind="auth") from e

    if not _vertex_project:
        raise LLMError("Vertex AI 프로젝트를 모릅니다. GOOGLE_CLOUD_PROJECT를 넣거나 gcloud로 ADC를 다시 만드세요",
                       kind="auth")
    return OpenAI(base_url=VERTEX_URL.format(project=_vertex_project), api_key=_vertex_creds.token,
                  timeout=TIMEOUT_SEC, max_retries=0)


def _vertex_thinking() -> dict | None:
    """VERTEX_THINKING_BUDGET이 있으면 Gemini의 생각(thinking) 토큰 상한을 요청에 붙인다. 없으면 None(모델 기본값).

    09-29 평가: Gemini 2.5 Flash는 답 전에 호출당 평균 1,863토큰을 생각에 써서 정상 질문 평균 10.1초였다
    (gpt-4o-mini 3.3초). 0이면 생각을 끈다. 실측 1회: 생각 597 → 0토큰, 5.3초 → 1.1초.
    OpenAI 형식의 reasoning_effort="none"은 Vertex가 400으로 거부해서(high·low·max·medium·minimal만 받음)
    Google 전용 칸 thinking_config를 쓴다. 이 SDK 호출에서는 extra_body 안에 한 겹 더 extra_body로 넣어야
    Vertex에 전달된다 (Vertex AI "OpenAI 라이브러리 사용" 문서 형식, 09-29 실측으로 확인).
    """
    budget = os.environ.get("VERTEX_THINKING_BUDGET")
    if budget is None or budget == "":
        return None
    return {"extra_body": {"google": {"thinking_config": {"thinking_budget": int(budget)}}}}


class _DeadlineExceeded(Exception):
    """_create_with_deadline이 TIMEOUT_SEC 안에 답을 못 받았을 때. _call_once가 LLMError(kind=timeout)로 바꾼다."""


def _create_with_deadline(client: OpenAI, kwargs: dict, extra_body: dict | None):
    """요청 하나를 별도 스레드에서 보내고, 최대 TIMEOUT_SEC초만 기다린다 (10-05).

    왜 SDK timeout만으로 안 되나: httpx timeout은 연결·읽기 구간별 상한이라 "한 번에 이만큼 조용하면" 끊는다.
    OpenRouter는 비스트리밍 요청에서 모델이 생각하는 동안 연결을 살려 두는 신호를 계속 보내서 읽기 상한이 안 걸린다
    (실측: 60초 설정인데 78초, 한 대화 턴 152초). 그래서 전체 시간(wall-clock)을 우리가 직접 잰다.
    스레드는 죽일 수 없어서 시간이 지나면 버려 두고(daemon) 기다리기만 멈춘다. 버린 요청은 SDK timeout이나
    제공사 쪽에서 끝나는 대로 사라진다. 예외는 그대로 다시 올려 _call_once의 기존 처리를 탄다.
    """
    box: dict = {}

    def run():
        try:
            box["resp"] = client.chat.completions.create(**kwargs, extra_body=extra_body)
        except BaseException as e:  # 스레드 밖에서 다시 올린다
            box["error"] = e

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(TIMEOUT_SEC)
    if worker.is_alive():
        raise _DeadlineExceeded()
    if "error" in box:
        raise box["error"]
    return box["resp"]


def _call_once(kwargs: dict) -> LLMResult:
    """OpenRouter 또는 Vertex AI를 딱 한 번 부른다. 실패는 전부 LLMError로 바꿔서 올린다."""
    model = kwargs["model"]
    is_vertex = model.startswith(VERTEX_PREFIX)
    if is_vertex:
        client = _vertex_client()
        # Vertex는 "google/gemini-2.5-flash"처럼 앞머리 없는 이름을 받는다
        kwargs = {**kwargs, "model": model.removeprefix(VERTEX_PREFIX)}
        extra_body = _vertex_thinking()  # 아래 provider 옵션은 OpenRouter 전용이라 보내지 않는다
    else:
        client = _client()
        # require_parameters: 요청에 쓴 기능(구조화 출력, tool)을 지원하는 제공사로만 보낸다.
        # OpenRouter의 모델 단위 "지원" 표시는 제공사 합계라, 이게 없으면 미지원 제공사로 조용히 넘어갈 수 있다 (09-23 조사).
        extra_body = {"provider": {"require_parameters": True}}

    start = time.monotonic()
    try:
        resp = _create_with_deadline(client, kwargs, extra_body)
    except _DeadlineExceeded:
        # 시간 상한에 닿았다. 다시 부르지 않는다 (RETRYABLE_CODES 주석). code가 없어 retryable도 False다
        raise LLMError(f"{model}: {TIMEOUT_SEC:g}초 안에 답이 없음",
                       latency_ms=int((time.monotonic() - start) * 1000), kind="timeout") from None
    except openai.APIStatusError as e:  # HTTP 4xx·5xx로 온 실패
        raise LLMError(f"{model}: HTTP {e.status_code} {e.message}", code=e.status_code,
                       latency_ms=int((time.monotonic() - start) * 1000), kind=_status_kind(e.status_code)) from e
    except openai.APIConnectionError as e:  # 연결 실패·타임아웃. 다시 부르지 않는다 (위 RETRYABLE_CODES 주석)
        raise LLMError(f"{model}: 연결 실패 {type(e).__name__}",
                       latency_ms=int((time.monotonic() - start) * 1000), kind="connection") from e
    latency_ms = int((time.monotonic() - start) * 1000)

    # OpenRouter는 제공사가 실패하면 HTTP 200 안에 choices 없이 error만 담아 보낼 때가 있다 (09-23 스모크 테스트).
    # 그대로 두면 choices[0]에서 TypeError가 나서 원인이 가려지므로, 에러 내용과 코드를 그대로 올린다.
    if not resp.choices:
        error = (resp.model_extra or {}).get("error") or {}
        raise LLMError(f"{model}: 응답에 choices 없음, error={error}", code=error.get("code"), latency_ms=latency_ms,
                       kind="no_choices")

    # Gemini(Vertex)는 생각(reasoning) 토큰으로 한도를 다 쓰면 message 없이 finish_reason=length만 준다
    # (09-29 실패 훈련 judge_truncated). 그대로 읽으면 AttributeError로 죽고, 라우터는 LLMError만 받으니 500이 났다.
    # 빈 답으로 받으면 _ask_json이 finish_reason을 보고 truncated로 올리고, 라우터가 재시도·failed로 처리한다
    msg = resp.choices[0].message or SimpleNamespace(content=None, tool_calls=None)
    # id: 도구 결과를 돌려줄 때 어느 호출의 결과인지 짝짓는 값 (role=tool 메시지의 tool_call_id, 10-02 후속 질문 도구)
    calls = [{"id": c.id, "name": c.function.name, "arguments": c.function.arguments} for c in (msg.tool_calls or [])]
    usage = resp.usage
    completion_tokens = usage.completion_tokens if usage else None
    # Vertex는 생각(reasoning) 토큰을 completion_tokens에 넣지 않고 completion_tokens_details에 따로 준다
    # (09-28 curl: prompt 11 + completion 1 + reasoning 33 = total 45). 요금은 생각 토큰도 출력으로 받으므로
    # 더해 둔다. 안 더하면 Langfuse가 모델 가격표로 계산한 비용이 실제보다 낮게 나온다.
    # OpenRouter는 OpenAI 방식대로 이미 포함해서 주므로 더하지 않는다
    if is_vertex and completion_tokens is not None:
        details = getattr(usage, "completion_tokens_details", None)
        completion_tokens += getattr(details, "reasoning_tokens", None) or 0
    return LLMResult(
        content=msg.content,
        tool_calls=calls,
        model=resp.model,
        provider=getattr(resp, "provider", None),  # OpenRouter 전용 필드라 SDK 타입에는 없다
        request_id=resp.id,
        prompt_tokens=usage.prompt_tokens if usage else None,
        completion_tokens=completion_tokens,  # 생각 토큰 포함 (위 주석)
        cached_tokens=getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", None) if usage else None,
        # OpenRouter 전용 필드라 SDK 타입에는 없다. 요청 옵션 없이 매 응답에 들어온다 (OpenRouter Usage Accounting 문서, 09-28 확인)
        cost=getattr(usage, "cost", None) if usage else None,
        latency_ms=latency_ms,
        finish_reason=getattr(resp.choices[0], "finish_reason", None),
    )


def _status_kind(status: int) -> str:
    """HTTP 상태 코드를 LLMError.kind로 바꾼다."""
    if status == 429:
        return "rate_limited"
    if status >= 500:
        return "overloaded"
    if status in (401, 403):
        return "auth"
    return "bad_request"


def chat(
    messages: list[dict],
    *,
    model: str | None = None,
    response_format: dict | None = None,
    tools: list[dict] | None = None,
    tool_choice: str | None = None,
    max_tokens: int | None = None,
) -> LLMResult:
    """OpenRouter에 묻고 답을 돌려준다. 429·502·503이면 잠깐 쉬고 한 번 더 묻는다. 출력 검증은 아직 안 한다.

    Args:
        messages: [{"role": "system"|"user"|..., "content": ...}]
        model: 생략하면 LLM_MODEL
        response_format: 구조화 출력. {"type": "json_schema", "json_schema": {...}}
        tools: tool 정의 목록 (OpenAI 형식)
        tool_choice: "none"이면 도구를 주되 부르지 말고 답하라는 뜻. 도구 호출 상한에 닿았을 때 쓴다 (_ask_json)
        max_tokens: 출력 상한

    Raises:
        LLMError: 재시도해도 안 되거나, 다시 불러도 소용없는 실패(400·401 등)
    """
    model = model or os.environ.get("LLM_MODEL")
    if not model:
        raise LLMError("LLM_MODEL이 없습니다", kind="not_configured")
    kwargs: dict = {"model": model, "messages": messages}
    if response_format:
        kwargs["response_format"] = response_format
    if tools:
        kwargs["tools"] = tools
    if tool_choice:
        kwargs["tool_choice"] = tool_choice
    if max_tokens:
        kwargs["max_tokens"] = max_tokens

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = _call_once(kwargs)
            result.attempts = attempt
            # 1명당 하루 토큰 한도에 쌓는다 (services/quota.py, docs/specs/token-quota.md). 이 요청은 끝까지 답하고 다음 요청부터 막는다
            quota.add((result.prompt_tokens or 0) + (result.completion_tokens or 0))
            return result
        except LLMError as e:
            if not e.retryable or attempt == MAX_ATTEMPTS:
                raise
            logger.warning("llm %s 실패(code %s), %.1f초 뒤 재시도 %d/%d",
                           kwargs["model"], e.code, RETRY_WAIT_SEC, attempt + 1, MAX_ATTEMPTS)
            time.sleep(RETRY_WAIT_SEC)
    raise AssertionError("unreachable")  # 마지막 시도는 위에서 return 또는 raise된다


# ── 2층 판정 judge() ─────────────────────────────────────────────
# SDD 4.1 7단계: 신호·통관·여유 일수를 받아 verdict·reasons·conflicts·actions·answer를 받는다.
# 자료는 코드가 미리 다 모아서 준다. LLM이 도구를 부르지 않는다 (09-27 결정, SDD 4.1 방식).

JUDGE_PROMPT = "marvia-judge"  # Langfuse 프롬프트 이름 (SDD 5.6 표)
SKILL_DIR = Path(__file__).resolve().parents[3] / "skills"  # 레포 루트의 skills/. Dockerfile도 같은 자리에 복사한다

# 구조화 출력 스키마. Pydantic에서 자동으로 뽑지 않고 손으로 적은 이유: strict 모드는 minItems 같은
# 키워드를 받지 않는 제공사가 있어서, 09-23 스모크 테스트에서 통과한 모양(scripts/smoke_llm.py)을 그대로 따른다.
# 모양은 아래 JudgeOutput과 같아야 한다. 받은 뒤 JudgeOutput으로 한 번 더 검사한다.
JUDGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "reasons", "conflicts", "actions", "answer", "customs", "table_disagree"],  # strict 모드는 모든 칸이 required
    "properties": {
        # null = 판정 보류. 위치가 아예 없을 때 등 (skills/cargo-verdict "코드가 낸 되묻기·보류·실패 결과")
        "verdict": {"type": ["string", "null"], "enum": ["fine", "watch", "act", None]},
        "reasons": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["rule", "value", "triggered"],
                "properties": {
                    "rule": {"type": "string", "description": "신호 id (rules.md)"},
                    "value": {"type": "string"},
                    "triggered": {"type": "boolean"},
                },
            },
        },
        "conflicts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["signals", "chosen", "why"],
                "properties": {
                    "signals": {"type": "array", "items": {"type": "string"}},
                    # 믿은 출처는 근거 카드의 출처 이름 중 하나여야 한다 (V6). 목록을 주지 않았더니 Gemini가
                    # "해수부 입항 예정" 같은 설명을 써서 act가 맞는데도 V6로 3번 탈락했다 (09-29 평가 B04·B09, Langfuse 확인).
                    # 목록은 계약 C1 Evidence.source에서 가져온다. 여기에 따로 적으면 둘이 어긋날 수 있다
                    "chosen": {"type": "string", "enum": list(get_args(Evidence.model_fields["source"].annotation)),
                               "description": "믿은 출처"},
                    "why": {"type": "string"},
                },
            },
        },
        "actions": {"type": "array", "items": {"type": "string"}},
        "answer": {"type": "string", "description": "사용자에게 보여 줄 한국어 두세 문장"},
        # 통관 단계 해설 (PRD 6.1 LLM 몫, skills/customs-stages). 통관 정보가 없으면 null
        "customs": {
            "anyOf": [
                {
                    "type": "object",
                    "additionalProperties": False,
                    # needs_broker는 코드가 정해 입력으로 준다 (10-01, signals.needs_broker). LLM은 쓰지 않는다
                    "required": ["plain_explanation", "next_stage"],
                    "properties": {
                        "plain_explanation": {"type": "string"},
                        "next_stage": {"type": ["string", "null"]},
                    },
                },
                {"type": "null"},
            ]
        },
        # 표 등급이 이 경우에 틀렸다고 볼 때 그 이유 (09-30 D7). 응답에 쓰지 않고 기록만 한다. 동의하면 null
        "table_disagree": {"type": ["string", "null"]},
    },
}


class CustomsExplanation(BaseModel):
    """LLM이 쓴 통관 해설. 단계 이름·코드·이력과 관세사 필요 여부는 코드 값을 쓰고, 여기서는 설명 둘만 받는다 (C1 CustomsInfo).
    예전 녹화 답(evals/fixtures/replay)에 needs_broker 칸이 남아 있어도 무시된다 (pydantic 기본값: 모르는 칸 무시)."""

    plain_explanation: str
    next_stage: str | None


class JudgeOutput(BaseModel):
    """LLM이 낸 판정. 필드 타입은 계약 C1(schemas/agent.py)의 것을 그대로 쓴다."""

    verdict: Verdict | None
    reasons: list[Reason]
    conflicts: list[Conflict]
    actions: list[str]
    answer: str
    customs: CustomsExplanation | None
    table_disagree: str | None = None  # 기록만 한다 (services/verdict.py). 녹화 답·베이스라인은 없어도 된다


@dataclass
class LLMAnswer:
    """judge()·pick_vessel()·answer_follow_up()의 결과. 검사를 통과한 출력과 함께
    트레이스에 남길 값(모델·토큰·지연·프롬프트 버전)을 들고 다닌다 (SDD 5.11)."""

    output: BaseModel  # 함수마다 JudgeOutput·PickOutput·FollowUpOutput
    llm: LLMResult
    prompt_version: str
    # LLM이 부른 도구와 결과 [{"name", "arguments", "result"}]. 후속 질문만 쓴다 (10-02). 라우터가 근거 카드로 붙인다
    tool_calls: list[dict] = field(default_factory=list)


# 호출마다 넣을 Skill 폴더 (09-30 결정). 전에는 모든 호출에 Skill 전부(약 6,600자, 판정 입력의 약 70%)를 넣었다.
# 각 호출이 받는 자료를 기준으로, 그 자료를 읽는 데 필요한 Skill만 넣는다. 넣는 Skill은 여전히 통째로다 (RAG 아님)
# 폴더 안의 *.md를 모두 넣는다: SKILL.md(도메인 지식·설명법)와 rules.md(코드가 읽는 재료와 그 뜻) (10-01 Skill 구조)
#   ais-reliability  AIS 값 읽는 법(오류 사례, 출처 우선순위), 신호 7종 기준
#   customs-stages   통관 단계 목록(rules.md)과 해설법
#   port-busan       부두 이름 뜻, 하역 장소 문장, 부산 기준값
#   cargo-verdict    등급 판정 표(rules.md), 등급 뜻·결과 설명법·되묻기와 실패 결과 설명법 (10-01 신설)
AIS, CUSTOMS, PORT, VERDICT = "ais-reliability", "customs-stages", "port-busan", "cargo-verdict"
ALL_SKILLS = (AIS, CUSTOMS, PORT, VERDICT)
JUDGE_SKILLS = (AIS, CUSTOMS, VERDICT)  # 신호 읽기 · 통관 해설 · 등급 설명. 판정 입력에 부두 · 하역 장소가 없어 부두 Skill은 안 넣는다
PICK_SKILLS = (AIS,)                    # 동명 선박 · 후보 판단. 통관 · 부두 · 등급은 쓰지 않는다
FOLLOW_UP_SKILLS = ALL_SKILLS           # 이전 응답 전체(등급 · 통관 · 하역 장소 · 되묻기 문구 포함)를 근거로 답하므로 전부
GRADE_SKILLS = (CUSTOMS,)               # 통관 해설 채점은 통관 단계 목록(customs-stages/rules.md)만 기준으로 한다 (평가 때만)


def skills_reference(folders: tuple[str, ...] = ALL_SKILLS, prompt_name: str | None = None) -> str:
    """검증 V9·V10(validate.py)이 "답에 써도 되는 낱말"의 출처로 쓰는 원문: LLM이 받은 Skill 문서와 지시문 (10-01).
    지시문 낱말을 넣는 이유: gpt-4o-mini가 판정 지시문 첫 줄의 "cargo"를 한국어 답에 섞어 판정 출력 228개 중 19개가
    V9에 걸렸다. 지시문에 있는 낱말은 주입이 끼워 넣은 표식이 아니다."""
    return _skills_text(folders) + ("\n\n" + get_prompt(prompt_name).text if prompt_name else "")


def _skills_text(folders: tuple[str, ...] = ALL_SKILLS) -> str:
    """고른 Skill 폴더의 .md를 파일 이름과 함께 이어 붙인다. RAG 없이 통째로 넣는다 (CLAUDE.md)."""
    parts = []
    for path in sorted(p for folder in folders for p in (SKILL_DIR / folder).rglob("*.md")):
        # Windows 문제: relative_to()를 그대로 문자열로 쓰면 Windows에서 "ais-reliability\SKILL.md"처럼 역슬래시가 된다.
        # 그러면 LLM이 보는 파일 이름이 OS마다 달라지고 test_judge.py::test_system_has_prompt_and_all_skills가 Windows에서만 깨진다.
        # as_posix()로 어느 OS에서든 "/"로 맞춘다 (Docker·Mac은 원래 "/"라 동작 변화 없음)
        parts.append(f"# 파일: skills/{path.relative_to(SKILL_DIR).as_posix()}\n\n{path.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)


# 판정 LLM 입력에서 뺄 통관 칸. B/L(bl_masked)·MRN·조회 시각 외에, 10-06에 붙은 포워더·선사·컨테이너 번호도 뺀다:
# 판정에 쓰이지 않고(프롬프트·평가 결과를 그대로 두려고), 컨테이너 번호는 B/L처럼 화물을 특정하는 번호라 LLM에 줄 수 없다.
# 포워더·선사 이름은 채팅 에이전트가 받는다 (services/chat.py _cargo_summary).
# 품명(goods_name, 10-06 오후)도 판정에 쓰이지 않아 뺀다. 채팅 에이전트만 받는다
JUDGE_CUSTOMS_EXCLUDE = {"bl_masked", "mrn", "fetched_at", "forwarder_name", "carrier_name", "container_no", "goods_name"}


def _judge_input(signals: SignalSet, customs: CustomsRecord | None, days_margin: int | None,
                 trusted_eta: datetime | None = None, sale_due_date: date | None = None,
                 table_verdict: str | None = None, verdict_mode: str | None = None) -> str:
    """LLM에 넘길 자료를 JSON 문자열로 만든다. B/L 번호(bl_masked)와 MRN은 판정에 필요 없어 뺀다 (CLAUDE.md, SDD 3.5).

    날짜는 한국 시각으로 준다 (09-29 D8). 전에는 여유 일수 숫자만 줘서 "언제 와요?"에 날짜로 답하지 못했고,
    사용자가 말한 판매일을 근거에 없는 숫자로 보고 검증(V7)이 막기도 했다 (평가 F06 "9월 23일"). 판매일이 없으면 null이다 (선택 입력, 09-29 결정).
    calc_eta는 남은 거리 ÷ 현재 속도로 코드가 계산한 대략값이다. 참고용이라 판정 근거로 쓰지 않게 지시문에 적는다.
    table_verdict·verdict_mode (09-30 D7, services/verdict.py): 코드가 판정 표로 낸 등급과, LLM이 그 등급을
    그대로 써야 하는지(fixed) 표 이상에서 고를 수 있는지(raise_only, 회색 지대)를 알려 준다.
    needs_broker (10-01): 관세사가 봐야 하는 단계인지 코드가 정한 값. LLM은 이 값에 맞춰 설명만 한다. 통관 정보가 없으면 null.
    """
    data = {
        "table_verdict": table_verdict,
        "verdict_mode": verdict_mode,
        "signals": [s.model_dump() for s in signals.signals],
        "freshness": signals.freshness,
        "distance_nm": signals.distance_nm,
        "trusted_eta": _kst(trusted_eta),
        "sale_due_date": sale_due_date.isoformat() if sale_due_date else None,
        "calc_eta": _kst(signals.calc_eta),
        "days_margin": days_margin,
        "customs": _clean_customs(customs.model_dump(mode="json", exclude=JUDGE_CUSTOMS_EXCLUDE)) if customs else None,
        "needs_broker": needs_broker(customs.stage_name) if customs and customs.stage_name else None,
    }
    return json.dumps(data, ensure_ascii=False)


STAGE_SUSPECT = "(단계 이름 확인 필요)"  # 주입 모양 단계명 대신 LLM에 넘기는 글자 (_clean_customs)


def _clean_customs(data: dict) -> dict:
    """통관 단계명(UNI-PASS 외부 글자)이 주입 모양이면 LLM에 넘기기 전에 바꾼다 (SDD 7절, 10-01).
    단계명은 외부에서 온 글자라 주입이 들어올 수 있는 길이다. 판정 LLM이 그 문장을 보지 않게 한다 (예방 조치).
    화면의 근거 카드에는 원래 글자가 그대로 있다. 여기서 바꾸는 것은 LLM 입력뿐이다."""
    if guard.looks_like_injection(data.get("stage_name")):
        data["stage_name"] = STAGE_SUSPECT
    for stage in data.get("stage_history") or []:
        if guard.looks_like_injection(stage.get("name")):
            stage["name"] = STAGE_SUSPECT
    return data


def _kst(moment: datetime | None) -> str | None:
    """시각을 한국 시각 "YYYY-MM-DD HH:MM"으로. 근거 카드(services/evidence.py)와 같은 모양이라 V7 대조가 맞는다."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(KST).strftime("%Y-%m-%d %H:%M")


def _loose_json(content: str | None, output_model: type[BaseModel]) -> str | None:
    """도구 라운드에서 모델이 response_format 없이 낸 본문을 output_model JSON으로 읽는다. 읽히면 깨끗한 JSON 문자열, 아니면 None.

    ```json 코드 울타리와 앞뒤 공백만 벗긴다. 그 이상은 하지 않는다: 여기서 못 읽으면 _ask_json이
    response_format을 붙여 한 번 더 묻는 쪽이 더 믿을 만하다 (10-05).
    """
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0].strip()
    try:
        output_model.model_validate_json(text)
    except ValidationError:
        return None
    return text


def _ask_json(prompt_name: str, user_content: str, schema_name: str, schema: dict,
              output_model: type[BaseModel], model: str | None, feedback: str | None = None,
              skills: tuple[str, ...] = ALL_SKILLS, tools: list[dict] | None = None,
              run_tool: Callable[[str, dict], dict] | None = None, context: str | None = None) -> LLMAnswer:
    """여러 함수가 같이 쓰는 한 번의 문답. 지시문(Langfuse) + skills 문서를 system에, 자료를 user에 넣고
    구조화 출력으로 받은 JSON을 output_model로 검사한다.
    skills는 넣을 Skill 폴더다 (JUDGE_SKILLS 등). 빈 튜플이면 넣지 않는다: 판단 기준이 필요 없는 호출(서류 칸 옮겨 적기)용.
    tools·run_tool: LLM이 직접 부를 도구 목록(OpenAI 형식)과, 부른 도구를 실제로 실행하는 함수 (10-02, 후속 질문만).
    run_tool(이름, 인자)는 도구 결과 dict를 돌려준다. 부른 기록은 LLMAnswer.tool_calls에 담는다.
    context: 로그인 사용자의 기억 블록(<user_cargo>·<user_memory>, services/memory.compose_blocks). 판정·후속 질문만 쓴다.
    순서는 지시문 + Skill(system, 고정) → 기억 블록 → 이번 자료 (docs/specs/memory.md 읽기 흐름 2). 고정된 앞부분이
    제공사 캐시에 걸리게 하고, 이번 자료(user_content)는 녹화 답 재생의 대조 키라 섞지 않고 따로 보낸다.

    Raises:
        LLMError: 호출 실패, 또는 답이 JSON이 아니거나 모양이 output_model과 다를 때.
                  내용 규칙(V1~V7) 검사와 재시도는 C-7 validate.py가 맡는다.
    """
    if replay.replay_enabled() and not (model or os.environ.get("LLM_MODEL")):
        return _replay_answer(prompt_name, user_content, output_model)
    prompt = get_prompt(prompt_name)
    system = f"{prompt.text}\n\n{_skills_text(skills)}" if skills else prompt.text
    messages = [{"role": "system", "content": system}]
    if context:
        messages.append({"role": "user", "content": context})
    messages.append({"role": "user", "content": user_content})
    if feedback:
        # 검증 위반을 붙여 다시 묻는 경우 (C-7). 코드가 쓴 지시라 자료(user_content)와 섞지 않고 따로 보낸다
        messages.append({"role": "user", "content": f"Your previous answer broke these rules. Answer again in the same JSON format and fix them:\n{feedback}"})
    # 트레이스 입력은 코드가 모은 자료(user_content)만. 지시문·skills 전문은 길고 매번 같아서 빼고 prompt_version으로 가린다
    # 기억 블록은 가리지 않고 그대로 남긴다 (10-02 결정 8: 운영자가 보는 기록. DB 줄은 탈퇴·삭제 때 지운다)
    generation = start_generation(prompt_name, f"{context}\n\n{user_content}" if context else user_content, prompt.source)
    response_format = {"type": "json_schema", "json_schema": {"name": schema_name, "strict": True, "schema": schema}}
    called: list[dict] = []
    try:
        # 도구가 없으면 한 번 묻고 끝난다 (판정·배 고르기 등, 지금까지와 같음: response_format을 붙인 한 번의 호출).
        # 도구가 있으면(후속 질문·채팅 에이전트, 10-02) LLM이 도구를 부르는 동안 결과를 돌려주며 다시 묻는다. MAX_TOOL_ROUNDS번 부른 뒤에는
        # tool_choice="none"으로 더 부르지 말고 답하게 한다. 같은 도구를 끝없이 부르는 것을 막는 상한이다 (가이드 Tool trajectory)
        # 도구를 고를 기회가 있는 라운드에는 response_format을 붙이지 않는다 (10-05 실측): deepseek-v4-flash(OpenRouter)는
        # strict json_schema가 같이 오면 도구를 한 번도 안 부르고 JSON만 낸다. 빼면 바로 맞는 도구를 부른다.
        # 대신 도구를 안 부르고 낸 본문을 JSON으로 읽어 보고, 안 읽히면 같은 대화에 response_format + tool_choice="none"으로 한 번 더 묻는다
        for round_no in range(MAX_TOOL_ROUNDS + 1):
            last_round = round_no == MAX_TOOL_ROUNDS
            if tools and not last_round:
                result = chat(messages, model=model, tools=tools, tool_choice=None)
                if not (run_tool and result.tool_calls):
                    parsed = _loose_json(result.content, output_model)
                    if parsed is not None:
                        result.content = parsed  # 코드 울타리·공백을 벗긴 JSON 본문. 아래 검사가 그대로 읽는다
                    else:
                        # 도구 목록은 그대로 둔다: 기록에 role=tool 메시지가 있으면 제공사가 tools 없는 요청을 거부할 수 있다
                        result = chat(messages, model=model, response_format=response_format, tools=tools,
                                      tool_choice="none")
                    break
            else:
                result = chat(messages, model=model, response_format=response_format, tools=tools or None,
                              tool_choice="none" if (tools and last_round) else None)
            if not (tools and run_tool and result.tool_calls) or last_round:
                break
            messages.append({"role": "assistant", "content": result.content, "tool_calls": [
                {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}}
                for c in result.tool_calls]})
            for c in result.tool_calls:
                try:
                    arguments = json.loads(c["arguments"] or "{}")
                except ValueError:
                    arguments = None
                if isinstance(arguments, dict):
                    output = run_tool(c["name"], arguments)
                else:  # 인자가 JSON이 아니면 도구를 부르지 않고 실패를 돌려준다. 모델이 고쳐 다시 부를 수 있다
                    output = {"error": {"code": "bad_arguments", "message": "arguments must be a JSON object", "retryable": False}}
                called.append({"name": c["name"], "arguments": arguments, "result": output})
                # 도구 결과는 자료다. 지시로 읽지 않는다는 규칙은 프롬프트에 있다 (marvia-follow-up "Tools" 절)
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(output, ensure_ascii=False)})
    except LLMError as e:
        end_generation(generation, None, prompt.version, error=str(e))
        raise
    cut_retried = False  # 끊긴 답을 다시 받은 적이 있나. 한 번만 다시 받는다 (10-06)
    while True:
        try:
            output = output_model.model_validate_json(result.content or "")
            break
        except ValidationError as e:
            if result.finish_reason is None and not cut_retried:
                # 10-06 실측: 서류 판독에서 HTTP 200인데 스트림이 JSON 중간(`{"vessel":`)에서 끊기고 finish_reason도 None인 답이
                # 두 번 왔다. 정상 종료(stop)나 토큰 한도(length) 신호가 없는 답은 모델이 끝까지 쓰지 못한 것이라, 같은 대화로
                # 한 번 더 묻는다. chat()은 이 경우를 재시도하지 않으므로(RETRYABLE_CODES는 상태 코드만 본다) 여기서 한다.
                # length는 다시 물어도 같은 한도에 닿으므로 건드리지 않고, 형식이 틀린 stop 답은 프롬프트 문제라 아래에서 올린다
                cut_retried = True
                logger.warning("llm %s 답이 끊김(finish_reason 없음), %.1f초 뒤 한 번 더 묻는다", result.model, RETRY_WAIT_SEC)
                time.sleep(RETRY_WAIT_SEC)  # 같은 대기 시간을 쓴다
                previous = result
                try:
                    result = chat(messages, model=model, response_format=response_format, tools=tools or None,
                                  tool_choice="none" if tools else None)
                except LLMError as call_error:
                    end_generation(generation, previous, prompt.version, output=previous.content, error=str(call_error))
                    raise
                result.attempts += previous.attempts  # Langfuse retry_count에 이 재시도도 센다 (end_generation: attempts - 1)
                continue
            # 어느 칸이 왜 틀렸는지만 적는다. LLM이 쓴 본문은 다시 붙이지 않는다 (트레이스 output에는 남는다)
            detail = "; ".join(f"{'.'.join(str(p) for p in err['loc']) or 'root'}: {err['msg']}" for err in e.errors()[:5])
            # 토큰 한도에서 잘린 답(finish_reason=length)은 모양이 틀린 답과 해결책이 다르다. 잘림은 한도를 늘리거나
            # 생각(reasoning)을 줄여야 하고, 모양 오류는 프롬프트를 고쳐야 한다. 그래서 kind를 나눈다
            kind = "truncated" if result.finish_reason == "length" else "bad_format"
            error = LLMFormatError(f"{result.model}: {schema_name} JSON 모양이 다름 ({e.error_count()}건, {kind})",
                                   f"Your answer did not match the JSON format. {detail}", kind=kind)
            end_generation(generation, result, prompt.version, output=result.content, error=str(error))
            raise error from e
    end_generation(generation, result, prompt.version, output=output.model_dump(mode="json"))
    return LLMAnswer(output=output, llm=result, prompt_version=prompt.version, tool_calls=called)


# ── LLM 녹화 답 재생 (09-29 결정) ─────────────────────────────
# 채점자가 키 없이 데모 3건을 돌리게 하는 장치다 (SDD 6.1, CLAUDE.md "REPLAY_MODE=true면 키 없이").
# REPLAY_MODE이고 LLM_MODEL이 비어 있을 때만 탄다. LLM_MODEL이 있으면 재생 모드에서도 진짜 LLM을 부른다.
# 녹화 파일: evals/fixtures/replay/llm/<프롬프트 이름>.json. 실제 모델로 데모 입력을 한 번 돌려 받은 답이다.
# 녹화 답은 그 입력에만 맞다. 입력이 다르면(판매일을 다르게 넣는 등) 녹화 답을 쓰지 않고 LLMError를 낸다.
# 틀린 답을 그럴듯하게 보여 주는 것보다, 라우터가 평소처럼 "판정 없이 partial"로 끝나는 편이 정직하다.

REPLAY_LLM_DIR = "llm"  # replay.REPLAY_DIR 아래 폴더. 평가 실행기가 REPLAY_DIR를 바꿔 끼워도 같이 따라간다


def _replay_matches(expected: dict, data: dict) -> bool:
    """녹화의 match 칸이 이번 입력과 같은가. signals는 {신호 id: 상태}로 줄여서 비교한다 (값·거리는 시각에 따라 조금씩 달라진다)."""
    for key, value in expected.items():
        actual = data.get(key)
        if key == "signals":
            actual = {s["id"]: s["state"] for s in actual or []}
        if actual != value:
            return False
    return True


def _replay_answer(prompt_name: str, user_content: str, output_model: type[BaseModel]) -> LLMAnswer:
    """녹화 파일에서 이번 입력에 맞는 답을 찾아 돌려준다. 없으면 키가 없을 때와 같은 LLMError (kind=not_configured).

    Langfuse 트레이스는 남기지 않는다. 모델을 부르지 않았고, 키 없는 데모라 보낼 곳도 없다.
    """
    # REPLAY_DIR는 부를 때 읽는다. 평가 실행기가 문항마다 바꿔 끼운다
    path = replay.REPLAY_DIR / REPLAY_LLM_DIR / f"{prompt_name}.json"
    # 녹화가 없는 프롬프트(선박 선택, 서류 칸 옮겨 적기 등)는 입력을 읽지 않고 바로 끝낸다. 서류 글자처럼 JSON이 아닌 입력도 있다
    if path.is_file():
        data = json.loads(user_content)
        for recording in json.loads(path.read_text(encoding="utf-8")):
            if _replay_matches(recording["match"], data):
                output = output_model.model_validate(recording["output"])
                return LLMAnswer(output=output, llm=LLMResult(content=None, model=f"replay/{recording['model']}"),
                                 prompt_version="replay")
    raise LLMError(f"REPLAY_MODE: {prompt_name} 녹화 답 중 이번 입력에 맞는 것이 없습니다", kind="not_configured")


def judge(
    signals: SignalSet,
    customs: CustomsRecord | None,
    days_margin: int | None,
    *,
    model: str | None = None,
    feedback: str | None = None,
    trusted_eta: datetime | None = None,
    sale_due_date: date | None = None,
    table_verdict: str | None = None,
    verdict_mode: str | None = None,
    memory: str | None = None,
) -> LLMAnswer:
    """2층 판정. output은 JudgeOutput. 자료는 코드가 모은 신호·통관·여유 일수·날짜 (SDD 4.1 7단계, 09-29 D8).
    feedback은 출력 검증(C-7) 위반 내용이다. 주면 위반을 고쳐 다시 답하라고 붙인다 (SDD 5.7 재시도).
    memory: 로그인 사용자의 기억 블록 (docs/specs/memory.md). 데이터일 뿐이고 등급은 지금처럼 판정 표가 정한다."""
    return _ask_json(JUDGE_PROMPT, _judge_input(signals, customs, days_margin, trusted_eta, sale_due_date,
                                                table_verdict, verdict_mode),
                     "judge", JUDGE_SCHEMA, JudgeOutput, model, feedback=feedback, skills=JUDGE_SKILLS, context=memory)


# ── 선박 선택 pick_vessel() ─────────────────────────────────────
# SDD 5.5: 후보 2척 이상일 때만 부른다. confidence high만 confirmed, 나머지는 uncertain (판정은 identify.py가 한다).

PICK_PROMPT = "marvia-pick-vessel"
PICK_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["choice", "confidence", "reasons_per_candidate"],
    "properties": {
        "choice": {"type": ["integer", "null"], "description": "고른 배의 MMSI. 애매하면 null"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "reasons_per_candidate": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["mmsi", "reason"],
                "properties": {"mmsi": {"type": "integer"}, "reason": {"type": "string"}},
            },
        },
    },
}


class CandidateReason(BaseModel):
    mmsi: int
    reason: str


class PickOutput(BaseModel):
    choice: int | None
    confidence: Literal["high", "medium", "low"]
    reasons_per_candidate: list[CandidateReason]


def _hours_since(then: datetime, now: datetime) -> float:
    """then부터 now까지 몇 시간 지났나 (소수 한 자리). 시간대가 없으면 UTC로 본다."""
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return round((now - then).total_seconds() / 3600, 1)


def pick_vessel(
    candidates: list[VesselCandidate],
    customs: CustomsRecord,
    voyage_no: str | None = None,
    forwarder_eta: date | None = None,
    *,
    model: str | None = None,
    now: datetime | None = None,
) -> LLMAnswer:
    """후보 여럿 중 이 화물의 배를 고른다. output은 PickOutput.

    후보에 없는 MMSI를 고르면 LLMError다. 없는 배로 확정하는 것을 막는다 (PRD 6.1 오확정 방지).
    now는 테스트에서 시각을 고정할 때만 넘긴다.
    """
    now = now or datetime.now(timezone.utc)
    data = {
        # 통관 정보는 식별에 쓰는 네 칸만. B/L·MRN은 넘기지 않는다 (CLAUDE.md)
        "customs": {"ship_name": customs.ship_name, "ship_nat": customs.ship_nat,
                    "voyage": customs.voyage, "entry_date": customs.entry_date.isoformat() if customs.entry_date else None},
        # 마지막 수신 후 경과 시간은 코드가 계산해 붙인다. LLM은 지금 시각을 몰라서 수신 시각만 주면
        # 1시간 전 신호를 "오래됐다"고 읽었다 (09-27 스모크 테스트). freshness를 코드가 정하는 원칙과 같다 (CLAUDE.md)
        "candidates": [
            {**c.model_dump(mode="json"), "hours_since_last": _hours_since(c.last_time, now)} for c in candidates
        ],
        "user_voyage_no": voyage_no,
        "user_forwarder_eta": forwarder_eta.isoformat() if forwarder_eta else None,
    }
    answer = _ask_json(PICK_PROMPT, json.dumps(data, ensure_ascii=False), "pick_vessel", PICK_SCHEMA, PickOutput, model,
                       skills=PICK_SKILLS)
    choice = answer.output.choice
    if choice is not None and choice not in {c.mmsi for c in candidates}:
        raise LLMError(f"{answer.llm.model}: 후보에 없는 MMSI {choice}를 골랐음")
    return answer


# ── 후속 질문 answer_follow_up() ────────────────────────────────
# C-9: 근거 범위 밖 질문은 거절한다 ("비트코인 시세" 거절이 완료 기준).

FOLLOW_UP_PROMPT = "marvia-follow-up"
FOLLOW_UP_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["in_scope", "answer"],
    "properties": {
        "in_scope": {"type": "boolean", "description": "판정 결과·근거 안에서 답할 수 있는 질문인가"},
        "answer": {"type": "string"},
    },
}


class FollowUpOutput(BaseModel):
    in_scope: bool
    answer: str


# 컨테이너 번호 토큰 (10-06 결정, CLAUDE.md "컨테이너 번호는 B/L처럼 LLM에 원문을 넘기지 않는다").
# 컨테이너 번호도 화물을 특정하는 번호라 LLM은 [CNTR1], [CNTR2] 번호표만 본다. 화면에 나가는 답에서는 코드가 원래 번호로 되돌린다
CONTAINER_TOKEN = re.compile(r"\[CNTR\d+\]")


def container_tokens(container_no: str | None) -> dict[str, str]:
    """컨테이너 번호 문자열(여러 개면 ', '로 이음)을 {"[CNTR1]": 번호, "[CNTR2]": 번호}로 만든다. 없으면 빈 dict.

    왜 한 함수인가: LLM에 넘기는 쪽(answer_follow_up)과 답을 되돌리는 쪽(routers/agent.py _follow_up)이 같은 번호표를
    써야 해서, 둘 다 이 함수로 같은 값(response.customs.container_no)에서 다시 만든다. 순서가 같으면 번호표도 같다.
    같은 번호가 두 번 나오면 하나로 본다."""
    numbers = list(dict.fromkeys(n.strip() for n in (container_no or "").split(", ") if n.strip()))
    return {f"[CNTR{i}]": number for i, number in enumerate(numbers, start=1)}


def hide_containers(value, tokens: dict[str, str]):
    """dict·list 안 모든 글자에서 컨테이너 번호를 번호표로 바꾼다. 통관 칸뿐 아니라 근거 카드 값, 지난 답(answer)에
    번호가 섞여 있어도 LLM에는 안 가게 하는 안전망이다 (지난 후속 답은 화면용으로 되돌린 번호를 담은 채 저장된다)."""
    if isinstance(value, str):
        for token, number in tokens.items():
            value = value.replace(number, token)
        return value
    if isinstance(value, dict):
        return {k: hide_containers(v, tokens) for k, v in value.items()}
    if isinstance(value, list):
        return [hide_containers(v, tokens) for v in value]
    return value


def restore_containers(text: str, tokens: dict[str, str]) -> str:
    """답 글자 속 [CNTR1]을 원래 컨테이너 번호로 되돌린다. 화면에만 가는 글자에 쓴다 (LLM에는 되돌린 글이 안 간다).
    모르는 번호표(LLM이 지어낸 [CNTR9])는 그대로 둔다."""
    return CONTAINER_TOKEN.sub(lambda m: tokens.get(m.group(0), m.group(0)), text)


def answer_follow_up(question: str, response: AgentResponse, *, model: str | None = None,
                     feedback: str | None = None, tools: list[dict] | None = None,
                     run_tool: Callable[[str, dict], dict] | None = None, memory: str | None = None) -> LLMAnswer:
    """이미 나온 판정(response)에 대한 후속 질문에 답한다. output은 FollowUpOutput.

    질문은 사용자 자유 입력이라 데이터로만 넘긴다 (SDD 7절 신뢰 경계). 300자 제한은 AgentRequest가 이미 건다.
    feedback: 앞 답이 검증 규칙(V1·V7)을 어겼을 때 어긴 내용. judge()와 같은 방식으로 다시 묻는다 (09-29, 평가 F06)

    AIS 목적지 원문(shipfinder dest 근거 카드)은 빼고 넘긴다 (SDD 7절, 10-01). 아무 배나 AIS에 쓸 수 있는 글자라
    "지금부터 너는 ~" 같은 역할 재설정 문장이 들어올 수 있다. 판정 LLM처럼 코드가 destcode로 계산한
    dest_changed 신호 카드만 남긴다. 화면의 근거 카드에는 그대로 있다 (여기서 빼는 것은 LLM 입력뿐).

    tools·run_tool (10-02, D9 B안): 지난 결과에 없는 지금 값(현재 위치·남은 거리·입항 기록)을 물으면 LLM이
    읽기 전용 MCP 도구를 직접 골라 부른다. 목록은 mcp_client.read_only_tools(), 실행은 routers/agent.py가 /mcp로 한다.
    판정 흐름(judge)은 지금처럼 코드가 도구를 부른다.
    memory: 로그인 사용자의 기억 블록 (docs/specs/memory.md 읽기 흐름). judge()와 같은 자리에 넣는다.

    컨테이너 번호는 원문을 넘기지 않고 [CNTR1] 번호표로 바꿔 준다 (10-06 결정). LLM은 번호표를 그대로 답에 쓰고,
    사용자에게 가는 문장에서는 라우터가 원래 번호로 되돌린다 (container_tokens, restore_containers).
    """
    # customs_detail(UNI-PASS 처리 이력 원문)은 화면 전용이라 LLM에 넘기지 않는다. 중량·관세법인명 등이 들어 있다 (docs/specs/customs-detail.md)
    # 통관 칸 중 컨테이너 번호는 B/L처럼 화물을 특정하는 번호라 원문을 주지 않는다 (10-06 점검). 칸을 빼지 않고 아래에서 [CNTR1]
    # 번호표로 바꾼다: "컨테이너 번호 뭐야?"에 LLM이 번호표로 답하면 라우터가 화면에서만 원래 번호로 되돌린다 (10-06 정운 결정).
    # 포워더·선사 이름은 남긴다. "포워더가 어디야" 같은 후속 질문에 답하는 재료다 (10-06 점검)
    result = response.model_dump(mode="json", exclude={"trace_id", "vessel_candidates", "customs_detail"})
    result["evidence"] = [e for e in result.get("evidence") or []
                          if not (e["source"] == "shipfinder" and e["field"] == "dest")]
    # 컨테이너 번호는 번호표로만 (10-06). customs.container_no는 [CNTR1], [CNTR2]가 되고, 다른 칸(근거 카드 값, 지난 답)에
    # 같은 번호가 있어도 같은 번호표로 바뀐다. 되돌리는 쪽은 routers/agent.py _follow_up (같은 container_tokens로 다시 만든다)
    tokens = container_tokens(response.customs.container_no if response.customs else None)
    if tokens:
        result = hide_containers(result, tokens)
        question = hide_containers(question, tokens)  # 사용자가 질문에 이 화물의 컨테이너 번호를 직접 써도 번호표로만 간다
    # 품명(10-06 오후)은 해외 화주가 적하목록에 쓴 글자라 주입 모양이면 뺀다 (chat._cargo_summary와 같은 예방 조치)
    if result.get("customs") and guard.looks_like_injection(result["customs"].get("goods_name")):
        result["customs"]["goods_name"] = None
    data = {"result": result, "question": question}
    return _ask_json(FOLLOW_UP_PROMPT, json.dumps(data, ensure_ascii=False), "follow_up",
                     FOLLOW_UP_SCHEMA, FollowUpOutput, model, feedback=feedback, skills=FOLLOW_UP_SKILLS,
                     tools=tools, run_tool=run_tool, context=memory)


# ── 서류 칸 뽑기 extract_doc_fields() ────────────────────────────
# docs/specs/document-extract.md 4단계: OCR 글자에서 6칸을 옮겨 적는다. 판단은 하지 않는다.
# 10-02 결정 6: B/L 조건 세 칸(원본 B/L·은행 지시식·운임 + 인코텀즈)과 화물 인도 연락처(회사·역할·회사 전화)도 읽는다.
# 조건은 고르기라 근거 글(*_text)을 글자 그대로 같이 받고, 그 글이 서류에 있는지 코드가 본다 (doc_ocr.check_conditions).
# B/L 번호는 코드(doc_ocr.take_bl)가 먼저 뽑아 [BL]로 가린 글자만 받는다 (CLAUDE.md).
# 옮긴 값이 글자에 실제로 있는지는 doc_ocr.check_fields가 검사한다.

DOC_EXTRACT_PROMPT = "marvia-doc-extract"
DOC_EXTRACT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    # strict 모드는 모든 칸이 required
    "required": ["vessel", "voyage", "eta", "pol", "pod", "item", "etd", "doc_kind",
                 "original_bl", "original_bl_text", "to_order_bank", "to_order_bank_text",
                 "freight_term", "freight_term_text", "incoterm", "contact_company", "contact_role", "contact_phone"],
    "properties": {
        "vessel": {"type": ["string", "null"]},
        "voyage": {"type": ["string", "null"]},
        "eta": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
        "pol": {"type": ["string", "null"]},
        "pod": {"type": ["string", "null"]},
        "item": {"type": ["string", "null"]},
        "etd": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
        "doc_kind": {"type": ["string", "null"], "enum": ["bl", "arrival_notice", None]},
        "original_bl": {"type": ["string", "null"], "enum": ["required", "surrendered", None]},
        "original_bl_text": {"type": ["string", "null"]},
        "to_order_bank": {"type": ["boolean", "null"]},
        "to_order_bank_text": {"type": ["string", "null"]},
        "freight_term": {"type": ["string", "null"], "enum": ["prepaid", "collect", None]},
        "freight_term_text": {"type": ["string", "null"]},
        "incoterm": {"type": ["string", "null"], "enum": ["CIF", "FOB", "CFR", None]},
        "contact_company": {"type": ["string", "null"]},
        "contact_role": {"type": ["string", "null"], "enum": ["포워더", "관세사", "수출자", "판매처", None]},
        "contact_phone": {"type": ["string", "null"]},
    },
}


class DocFieldsOutput(BaseModel):
    vessel: str | None
    voyage: str | None
    eta: str | None  # 모양 검사는 doc_ocr.check_fields가 한다. 여기서 date로 바꾸면 틀린 모양이 형식 오류로 바뀌어 원인이 가려진다
    pol: str | None
    pod: str | None
    item: str | None
    # 10-02 결정 6. 기본값 None: 이 칸이 생기기 전 모양의 답(테스트·녹화)도 읽힌다. 값 검사는 doc_ocr.check_conditions
    doc_kind: str | None = None           # bl / arrival_notice. 거래처 출처(B/L·A/N)를 정하는 데만 쓴다
    original_bl: str | None = None        # required / surrendered
    original_bl_text: str | None = None   # 위 값의 근거로 서류에서 그대로 옮긴 글
    to_order_bank: bool | None = None     # 수하인이 "TO ORDER OF ... BANK"인가
    to_order_bank_text: str | None = None
    freight_term: str | None = None       # prepaid / collect
    freight_term_text: str | None = None
    incoterm: str | None = None           # CIF / FOB / CFR
    contact_company: str | None = None    # 화물 인도 연락처 회사 (개인 이름 아님)
    contact_role: str | None = None       # 포워더 / 관세사 / 수출자 / 판매처
    contact_phone: str | None = None      # 회사·부서 전화 (개인 휴대폰 아님)
    # 10-06 출항일 YYYY-MM-DD (A/N의 ETD, B/L의 Shipped on board). 기본값 None: 프롬프트가 Langfuse에 등록되기 전이라
    # LLM이 이 칸을 모르거나 null로 두어도 읽힌다. 모양·서류 속 존재·eta와의 순서 검사는 doc_ocr.check_fields
    etd: str | None = None


def extract_doc_fields(masked_text: str, *, model: str | None = None) -> LLMAnswer:
    """B/L을 가린 OCR 글자에서 선명·항차·ETA·선적항·양하항·품명과 B/L 조건·연락처를 옮겨 적는다. output은 DocFieldsOutput.

    OCR 글자는 사용자 서류라 데이터로만 넘긴다 (SDD 7절 신뢰 경계, 프롬프트에도 명시).
    """
    return _ask_json(DOC_EXTRACT_PROMPT, masked_text, "doc_extract", DOC_EXTRACT_SCHEMA, DocFieldsOutput, model,
                     skills=())


# ── 기억 뽑기 write_memory() ─────────────────────────────────
# docs/specs/memory.md 쓰기 흐름 4: 메모장을 다시 쓰지 않고 줄 단위 명령만 받는다. 검사·적용은 services/memory.py.
# 입력은 가린 B/L, 이번 판정 한 줄, 사용자 문장(B/L은 [BL1]), 번호 있는 메모장. B/L 원본은 넘기지 않는다 (CLAUDE.md).

MEMORY_PROMPT = "marvia-memory-write"
_NULLABLE_TEXT = {"type": ["string", "null"]}
MEMORY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["ops"],
    "properties": {
        "ops": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                # strict 모드는 모든 칸이 required. 명령마다 안 쓰는 칸은 null (프롬프트에 적는다)
                "required": ["op", "id", "section", "kind", "fields", "field", "value"],
                "properties": {
                    "op": {"type": "string", "enum": ["add", "update", "delete", "set_cargo", "noop"]},
                    "id": _NULLABLE_TEXT,
                    "section": {"type": ["string", "null"], "enum": ["about", "cargo", None]},
                    "kind": {"type": ["string", "null"],
                             "enum": ["preference", "schedule", "contact", "worry", "todo", None]},
                    "fields": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["text", "done", "cycle", "task", "company", "role", "duty", "phone", "source"],
                        "properties": {
                            "text": _NULLABLE_TEXT, "done": {"type": ["boolean", "null"]},
                            "cycle": _NULLABLE_TEXT, "task": _NULLABLE_TEXT, "company": _NULLABLE_TEXT,
                            "role": _NULLABLE_TEXT, "duty": _NULLABLE_TEXT, "phone": _NULLABLE_TEXT,
                            "source": _NULLABLE_TEXT,
                        },
                    },
                    "field": {"type": ["string", "null"], "enum": ["sale_due_date", "forwarder_eta", "label", None]},
                    "value": _NULLABLE_TEXT,
                },
            },
        },
    },
}


class MemoryFields(BaseModel):
    """명령의 칸 값. 종류마다 쓰는 칸이 다르고 나머지는 null. 어느 칸이 허용되는지는 services/memory.py가 본다."""

    text: str | None = None
    done: bool | None = None
    cycle: str | None = None
    task: str | None = None
    company: str | None = None
    role: str | None = None
    duty: str | None = None
    phone: str | None = None
    source: str | None = None


class MemoryOp(BaseModel):
    op: Literal["add", "update", "delete", "set_cargo", "noop"]
    id: str | None = None
    section: str | None = None
    kind: str | None = None
    fields: MemoryFields | None = None
    field: str | None = None
    value: str | None = None


class MemoryOpsOutput(BaseModel):
    ops: list[MemoryOp]


def write_memory(content: str, *, model: str | None = None) -> LLMAnswer:
    """기억 뽑기. output은 MemoryOpsOutput. content는 services/memory.writer_input이 만든 JSON 글자.

    모델은 MEMORY_MODEL(.env). 없으면 LLMError(not_configured)이고 부르는 쪽이 조용히 건너뛴다 (10-02 결정 10).
    판단 기준 Skill은 넣지 않는다. 메모장 종류·칸 규칙은 프롬프트에 있고 코드가 다시 검사한다.
    """
    model = model or os.environ.get("MEMORY_MODEL")
    if not model:
        raise LLMError("MEMORY_MODEL이 없습니다", kind="not_configured")
    return _ask_json(MEMORY_PROMPT, content, "memory_write", MEMORY_SCHEMA, MemoryOpsOutput, model, skills=())


# ── 대화 제목 make_chat_title() ─────────────────────────────
# 대화 목록(10-06 결정)의 제목. 첫 사용자 말을 코드가 B/L을 [BL1]로 가린 글만 받는다 (CLAUDE.md, B/L 원본은 LLM에 안 간다).
# 결과 검사(한 줄·길이·주입 모양)와 실패 시 대신 쓸 제목은 services/conversations.py가 맡는다.

TITLE_PROMPT = "marvia-chat-title"
TITLE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title"],
    "properties": {"title": {"type": "string"}},
}


class TitleOutput(BaseModel):
    title: str


def make_chat_title(masked_text: str, *, model: str | None = None) -> LLMAnswer:
    """대화 제목 짓기. output은 TitleOutput. masked_text는 mask_bls를 거친 첫 사용자 말이다.

    값싼 모델을 쓰려고 기억 뽑기와 같은 MEMORY_MODEL(.env)을 쓴다. 없으면 LLMError(not_configured)이고
    부르는 쪽이 첫 말 앞 글자로 대신한다. 판단 기준 Skill은 넣지 않는다.
    """
    model = model or os.environ.get("MEMORY_MODEL")
    if not model:
        raise LLMError("MEMORY_MODEL이 없습니다", kind="not_configured")
    return _ask_json(TITLE_PROMPT, masked_text, "chat_title", TITLE_SCHEMA, TitleOutput, model, skills=())


# ── 통관 해설 채점 grade_customs() ─────────────────────────────
# 평가 전용 LLM-as-judge (SDD 5.12 customs_explanation, 가이드 평가 4축 ④ "생성 모델 ≠ 판정 모델").
# 서비스 요청에서는 부르지 않는다. evals/judge.py가 평가 실행 때만 부른다.
# 판정 LLM이 쓴 통관 해설(단계 뜻 · 다음 단계 · 관세사 필요 여부)을 customs-stages Skill(단계 목록은 rules.md customs_stages) 기준으로 0/1 채점한다.

JUDGE_EVAL_PROMPT = "marvia-judge-eval"  # Langfuse 프롬프트 이름 (SDD 5.6 표)
GRADE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["score", "reason"],
    "properties": {
        # 정수 enum은 Gemini 구조화 출력이 지원하지 않아 빈 {}가 온다 (10-01, 채점 모델을 gemini-2.5-flash로 바꿀 때 확인).
        # 0/1 범위는 GradeOutput(Literal[0, 1])이 검사한다
        "score": {"type": "integer", "description": "지시문의 다섯 조건을 모두 지키면 1, 하나라도 어기면 0"},
        "reason": {"type": "string", "description": "어긴 조건 번호와 이유 한 줄. 다 지키면 pass"},
    },
}


class GradeOutput(BaseModel):
    score: Literal[0, 1]
    reason: str


def grade_customs(customs: dict, *, model: str | None = None) -> LLMAnswer:
    """통관 해설 하나를 채점한다. output은 GradeOutput. 모델은 EVAL_GRADER_MODEL(.env, 계약 C8).

    customs: AgentResponse.customs를 dict로 (stage_name · plain_explanation · next_stage · needs_broker).
    채점 모델은 판정 모델과 다른 회사여야 한다. 같은 모델은 자기 답을 후하게 채점한다(자기 선호 편향).
    그 확인은 부르는 쪽(evals/judge.py)이 한다. 해설 문장은 채점할 데이터로만 넘긴다 (지시문 마지막 줄).
    """
    model = model or os.environ.get("EVAL_GRADER_MODEL")
    if not model:
        raise LLMError("EVAL_GRADER_MODEL이 없습니다", kind="not_configured")
    data = {key: customs.get(key) for key in ("stage_name", "plain_explanation", "next_stage", "needs_broker")}
    return _ask_json(JUDGE_EVAL_PROMPT, json.dumps(data, ensure_ascii=False), "grade", GRADE_SCHEMA, GradeOutput, model,
                     skills=GRADE_SKILLS)


# ── 자연어 입력 라우팅 route_chat(), 항구 고르기 match_ports() ──────────
# docs/specs/chat-search.md. 검색 폼 대신 문장 하나를 받는다. LLM은 의도와 칸만 고르고 실행은 코드(services/chat.py)가 한다.
# B/L은 코드가 [BL1]처럼 가린 뒤에만 넘어온다 (CLAUDE.md). Skill 문서는 넣지 않는다(판단 기준이 필요 없는 분류).

CHAT_ROUTE_PROMPT = "marvia-chat-route"
CHAT_ROUTE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["intent", "bl_ref", "bl_type", "sale_due_date", "question", "place", "place_label", "days", "reply"],
    "properties": {
        "intent": {"type": "string", "enum": ["cargo", "follow_up", "vessel_search", "other"]},
        "bl_ref": {"type": ["string", "null"]},
        "bl_type": {"type": ["string", "null"], "enum": ["MASTER", "HOUSE", None]},
        "sale_due_date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
        "question": {"type": ["string", "null"]},
        "place": {"type": ["string", "null"]},
        "place_label": {"type": ["string", "null"]},
        "days": {"type": ["integer", "null"]},
        "reply": {"type": "string"},
    },
}


class ChatRouteOutput(BaseModel):
    intent: Literal["cargo", "follow_up", "vessel_search", "other"]
    bl_ref: str | None
    bl_type: Literal["MASTER", "HOUSE"] | None
    sale_due_date: str | None  # 모양 검사는 services/chat.py가 한다
    question: str | None
    place: str | None
    place_label: str | None = None  # 답에 쓸 이름. 사용자가 쓴 말 그대로 (예: 중국)
    days: int | None
    reply: str


def route_chat(masked_message: str, bl_refs: list[str], has_current_cargo: bool, today: str, *,
               model: str | None = None) -> LLMAnswer:
    """가린 문장을 의도 하나와 칸으로 나눈다. output은 ChatRouteOutput. 칸 값은 services/chat.py가 다시 검사한다."""
    data = {"message": masked_message, "bl_refs": bl_refs, "has_current_cargo": has_current_cargo, "today": today}
    return _ask_json(CHAT_ROUTE_PROMPT, json.dumps(data, ensure_ascii=False), "chat_route", CHAT_ROUTE_SCHEMA,
                     ChatRouteOutput, model, skills=())


# ── 채팅 에이전트 chat_agent() (10-05 결정) ──────────────────────────
# route_chat은 문장을 의도 하나로 나누고 끝났다. 그래서 네 의도에 안 맞는 실무 질문("포워더가 항차 번호를 안 줘")은
# 전부 고정 안내로 갔고, 한 문장에 조회 둘이 필요한 일("상하이에서 오는 배 중 제일 먼저 오는 배 지금 어디야")도 못 했다 (10-05 실측 대화).
# chat_agent는 LLM이 도구를 골라 부르고, 결과를 보고 다음 도구를 또 고른다 (_ask_json의 도구 루프, 상한 MAX_TOOL_ROUNDS).
# 도구 목록과 실행은 services/chat.py가 준다: 화물 조회·화물 질문·입항 선박 검색 + 읽기 전용 MCP 도구.
# 등급·여유 일수는 지금처럼 코드가 정한다. B/L은 가린 토큰만 온다 (CLAUDE.md).
# Skill 문서를 통째로 넣는다: 도구가 필요 없는 실무 질문은 이 문서 안에서만 답하게 한다 (RAG 아님).

CHAT_AGENT_PROMPT = "marvia-chat-agent"
CHAT_AGENT_SKILLS = ALL_SKILLS  # 되묻기 설명법(cargo-verdict), 통관 단계, AIS, 부두를 모두 물을 수 있다
# 도구 없이 답할 때의 근거 칸 (10-05 실측): 실무 질문 답에 Skill 문서에 없는 조언("판매처에 문의", "A/N에 B/L 번호가 보통 적혀 있다")이
# 섞여 나왔는데, 숫자·영문·옮긴 낱말만 보는 V7·V9·V10으로는 못 잡았다. 그래서 답의 종류(answer_kind)와 근거 문장(skill_quote)을 받는다.
#   skill: Skill 문서로 답했다. skill_quote는 그 답을 받치는 Skill 문서 원문 한 조각이고, 코드가 원문에 그대로 있는지 본다 (validate V14)
#   not_in_skills: 수입 화물 질문이지만 Skill 문서에 없다. 코드가 고정 문구를 쓴다 (chat.NOT_IN_SKILLS)
#   unrelated: 수입 화물과 상관없는 말. 코드가 고정 안내를 쓴다 (chat.OTHER_REPLY)
#   tool: 도구를 불렀고 그 결과를 받은 뒤의 답. 도구 없이 tool을 내면 코드가 도구를 부르라고 다시 묻는다 (chat._agent).
#     따로 둔 이유 (10-05 실측): 도구를 쓴 답을 unrelated + 빈 reply로 내게 했을 때 도구를 안 부른 답과 코드가 구별하지 못했다.
#     같은 날 진단에서 deepseek-v4-flash(OpenRouter)는 strict response_format을 붙이면 도구를 전혀 부르지 않고 이 모양만 냈다
#     (붙이지 않으면 search_arrivals·ask_cargo를 바로 불렀다). 그 문제는 _ask_json 쪽이고, 여기서는 tool을 낸 답을 코드가 알아보게만 한다
# 도구를 쓴 답이면 근거 칸은 보지 않는다. 종류를 잘못 골라도 결과는 고정 문구 중 하나라 지어낸 조언이 화면에 가지 않는다
#   web: 웹 검색 도구(chat.WEB_TOOL)로 받은 결과로 답했다 (10-05 결정). skill_quote는 웹 검색 결과 원문 한 조각이고,
#     코드가 가져온 웹 글에 그대로 있는지 본다 (V14와 같은 방식, chat._web_violations)
#   general: 3층 (10-05 결정). 교과서 수준의 일반 해운 설명(용어 뜻, 일반 절차)을 모델 지식으로 답했다. 근거 조각 없이 내보내되
#     숫자·세액·특정 화물·배 이야기는 안 되고 코드가 짧은 고정 꼬리표를 붙인다 (chat.GENERAL_TAG, chat._agent). 검사는 V7·V9(허용 용어 확장)·V10·V13
#   unrelated: 이제 한 문장짜리 직접 답을 낼 수 있다 (날짜·"마르비아가 뭐야?" 같은 잡담). 검사에 걸리면 고정 안내로 바뀐다
#   clarify: 사용자가 쓴 식별자(예: TEST41)가 B/L 번호인지 배 이름인지 모르겠다 (10-05 실측). 코드가 고정 문장으로 되묻는다
#     (chat.clarify_reply). reply는 비운다: LLM 글은 화면에 가지 않고 식별자도 코드가 문장에서 직접 뽑는다
# help·greeting: 사용법 질문과 인사. 문장은 services/chat.py가 고정 문구로 낸다 (10-05 결정)
CHAT_AGENT_KINDS = ("tool", "skill", "web", "general", "not_in_skills", "unrelated", "clarify", "help", "greeting")
CHAT_AGENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reply", "answer_kind", "skill_quote", "watch_cue"],
    "properties": {
        "reply": {"type": "string"},
        "answer_kind": {"type": "string", "enum": list(CHAT_AGENT_KINDS)},
        "skill_quote": {"type": "string"},
        "watch_cue": {"type": "boolean"},
    },
}


class ChatAgentOutput(BaseModel):
    reply: str  # 화면에 내보내기 전에 services/chat.py가 검사한다
    # 기본값은 도구를 쓴 답(두 칸을 보지 않음)과 예전 녹화 답이 그대로 읽히게 둔 것이다. 실제 호출은 strict 스키마라 늘 채워 온다
    answer_kind: Literal["tool", "skill", "web", "general", "not_in_skills", "unrelated", "clarify", "help", "greeting"] = "unrelated"
    skill_quote: str = ""  # answer_kind가 skill이면 Skill 문서, web이면 웹 검색 결과 원문 그대로의 한 조각
    # 사용자 말에 걱정·기한 압박이 묻어 있나 (10-06 결정 "먼저 제안"). 신호일 뿐이다: 제안할지는 services/chat.py가 정한다.
    # 기본값 False는 예전 녹화 답이 그대로 읽히게 둔 것이다 (실제 호출은 strict 스키마라 늘 채워 온다)
    watch_cue: bool = False


def chat_agent(masked_message: str, bl_refs: list[str], has_current_cargo: bool, today: str, history: list[dict],
               tools: list[dict], run_tool: Callable[[str, dict], dict], *, model: str | None = None,
               feedback: str | None = None) -> LLMAnswer:
    """가린 문장과 최근 대화를 받아 도구를 골라 쓰고 답 한 칸을 낸다. output은 ChatAgentOutput.

    history: [{"role": "user"|"assistant", "text": 가린 글}]. 자료일 뿐이다 (프롬프트 Trust boundary).
    부른 도구와 결과는 LLMAnswer.tool_calls에 담긴다. 답 문장 검사는 services/chat.py가 한다.
    feedback: 앞 답이 검사에 걸렸을 때 걸린 내용. 이때는 tools를 비워 부른다 (같은 도구를 두 번 실행하지 않게).
    """
    data = {"message": masked_message, "bl_refs": bl_refs, "history": history,
            "has_current_cargo": has_current_cargo, "today": today}
    return _ask_json(CHAT_AGENT_PROMPT, json.dumps(data, ensure_ascii=False), "chat_agent", CHAT_AGENT_SCHEMA,
                     ChatAgentOutput, model, feedback=feedback, skills=CHAT_AGENT_SKILLS, tools=tools, run_tool=run_tool)


# ── 웹 검색 web_search() (10-05 결정) ──────────────────────────────
# 채팅 에이전트의 좁은 웹 검색 도구가 쓴다 (services/chat.py WEB_TOOL). Skill 문서가 못 받치는 실무 질문(B/L 번호 찾는 곳, 포워더 확인,
# A/N 뜻)에만 쓰고, 판정·특정 화물·세액·통관 가능 여부에는 쓰지 않는다 (PRD 4절). 그 제한은 chat.py가 건다. 여기는 검색 호출만 한다.
# OpenRouter 웹 플러그인을 engine=exa로 쓴다 (10-05 실측, 계정은 ZDR 제한이 있음):
#   - engine 기본값(네이티브)은 Gemini의 구글 검색이라 출처가 vertexaisearch 리다이렉트 주소이고 원문이 안 온다. 검증할 글이 없어 못 쓴다
#   - firecrawl은 ZDR 계정에서 400으로 막힌다
#   - exa는 응답 annotations(url_citation)에 실제 주소·제목·가져온 원문(content)을 준다 -> 이것이 "가져온 웹 글"이다
# 검색을 시키는 모델의 답 본문은 버린다 (max_tokens=16). 웹 글 속 지시가 모델을 움직여도 그 출력은 어디에도 안 쓰인다.
# 에이전트가 읽는 것은 annotations의 글뿐이고, 그 글은 자료로만 간다 (프롬프트 Trust boundary)
WEB_RESULTS = 3          # 한 번에 받는 결과 수. 비용(결과당 과금)과 에이전트 입력 길이를 같이 줄인다
WEB_TEXT_CHARS = 1500    # 결과 하나에서 에이전트에 주는 글자 수 상한 (exa가 주는 길이가 대체로 이 안이다)
WEB_QUERY_CHARS = 120    # 검색어 길이 상한
WEB_FALLBACK_MODEL = "google/gemini-3.5-flash-lite"  # LLM_MODEL이 vertex/ 모델이면 OpenRouter 웹 플러그인을 못 쓴다. 그때 검색 호출만 이 모델로 한다
WEB_BLOCKED_TOKENS = ("[BL", "[MRN")  # 가린 B/L·MRN 토큰이 든 검색어는 밖으로 안 나간다 (CLAUDE.md: B/L은 LLM·외부에 안 넘긴다)


def web_search(query: str) -> list[dict]:
    """검색어 하나로 웹을 검색해 [{"title", "url", "text"}]를 돌려준다 (최대 WEB_RESULTS개). 결과가 없으면 빈 목록.

    검색어는 가린 문장에서 만든 것이어야 하고, 호출하는 쪽(chat.py)이 B/L 토큰·MRN·주입 모양을 먼저 거른다. 여기서도 B/L·MRN 토큰은 한 번 더 막는다.
    TIMEOUT_SEC 전체 시간 상한은 일반 호출과 같다 (_create_with_deadline). 키가 없으면 LLMError. 실패는 전부 LLMError다.
    """
    query = (query or "").strip()
    if not query or len(query) > WEB_QUERY_CHARS or any(t in query.upper() for t in WEB_BLOCKED_TOKENS):
        raise LLMError("web_search: 검색어가 비었거나 너무 길거나 B/L·MRN 토큰이 들어 있음", kind="bad_query")
    model = os.environ.get("LLM_MODEL") or WEB_FALLBACK_MODEL
    if model.startswith(VERTEX_PREFIX):
        model = WEB_FALLBACK_MODEL
    start = time.monotonic()
    # 검색도 요청 트레이스에 generation으로 남긴다 (10-05): 비용(약 $0.008)과 결과가 Langfuse에서 안 보였다.
    # 검색어는 위에서 B/L·MRN 토큰을 막은 가린 문장이다. 트레이스 실패는 검색을 막지 않는다 (start/end가 삼킨다)
    generation = start_generation("web_search", query)
    resp = None
    try:
        resp = _create_with_deadline(
            _client(),
            {"model": model, "messages": [{"role": "user", "content": query}], "max_tokens": 16},
            {"plugins": [{"id": "web", "engine": "exa", "max_results": WEB_RESULTS}], "provider": {"require_parameters": True}})
    except LLMError as e:  # 키 없음 등 _client()가 올린 것. 열어 둔 기록을 닫는다
        end_web_search(generation, None, model=model, error=str(e))
        raise
    except _DeadlineExceeded:
        end_web_search(generation, None, model=model, error=f"timeout after {TIMEOUT_SEC:g}s")
        raise LLMError(f"web_search: {TIMEOUT_SEC:g}초 안에 답이 없음", kind="timeout") from None
    except openai.APIStatusError as e:  # ZDR 거부 등. 메시지는 키를 담지 않는다
        end_web_search(generation, None, model=model, error=f"HTTP {e.status_code} {e.message}")
        raise LLMError(f"web_search: HTTP {e.status_code} {e.message}", code=e.status_code, kind=_status_kind(e.status_code)) from e
    except openai.APIConnectionError as e:
        end_web_search(generation, None, model=model, error=f"connection {type(e).__name__}")
        raise LLMError(f"web_search: 연결 실패 {type(e).__name__}", kind="connection") from e
    if not resp.choices:
        end_web_search(generation, None, resp.usage, model, error="no_choices")
        raise LLMError("web_search: 응답에 choices 없음", kind="no_choices")
    message = resp.choices[0].message
    notes = getattr(message, "annotations", None) or (getattr(message, "model_extra", None) or {}).get("annotations") or []
    found, seen = [], set()
    for note in notes:
        note = note if isinstance(note, dict) else note.model_dump()
        cite = note.get("url_citation") or {}
        url, text = str(cite.get("url") or ""), str(cite.get("content") or "").strip()
        if not url.startswith(("http://", "https://")) or not text or url in seen:
            continue
        seen.add(url)
        found.append({"title": str(cite.get("title") or url)[:120], "url": url, "text": text[:WEB_TEXT_CHARS]})
    logger.info("web_search results=%d latency_ms=%d cost=%s", len(found), int((time.monotonic() - start) * 1000),
                getattr(resp.usage, "cost", None) if resp.usage else None)
    found = found[:WEB_RESULTS]
    end_web_search(generation, found, resp.usage, getattr(resp, "model", None) or model)
    # 웹 검색도 하루 토큰 한도에 쌓는다. chat()을 거치지 않는 호출이라 여기서 따로 더한다 (services/quota.py, docs/specs/token-quota.md).
    # 검색 결과가 입력에 붙으므로 prompt_tokens가 작지 않다. usage가 없으면 0으로 본다
    usage = resp.usage
    quota.add((getattr(usage, "prompt_tokens", 0) or 0) + (getattr(usage, "completion_tokens", 0) or 0) if usage else 0)
    return found


PORT_MATCH_PROMPT = "marvia-port-match"
PORT_MATCH_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["ports"],
    "properties": {"ports": {"type": "array", "items": {"type": "string"}}},
}


class PortMatchOutput(BaseModel):
    ports: list[str]


def match_ports(place: str, ports: list[str], *, model: str | None = None) -> LLMAnswer:
    """place에 있는 항구를 주어진 목록 안에서만 고른다 (pick_vessel처럼 고르기만). 목록 밖 이름은 코드가 버린다."""
    data = {"place": place, "ports": ports}
    return _ask_json(PORT_MATCH_PROMPT, json.dumps(data, ensure_ascii=False), "port_match", PORT_MATCH_SCHEMA,
                     PortMatchOutput, model, skills=())
