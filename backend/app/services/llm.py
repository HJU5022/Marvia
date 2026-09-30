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
  extract_doc_fields() 서류 사진 OCR 글자에서 선명·항차·ETA 등 6칸을 옮겨 적는다 (docs/specs/document-extract.md)

모델 자리 (.env, 계약 C8):
  LLM_MODEL           서비스가 쓰는 모델. 위 네 함수 전부 (09-30 이름 바꿈, 전 MODEL_A)
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
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, get_args

import openai
from openai import OpenAI
from pydantic import BaseModel, ValidationError

from backend.app.clients import replay  # REPLAY_MODE 녹화 답 재생 (_replay_answer)
from backend.app.observability.langfuse import end_generation, get_prompt, start_generation
from backend.app.schemas.agent import AgentResponse, Conflict, Evidence, Reason, VesselCandidate, Verdict
from backend.app.schemas.customs import CustomsRecord
from backend.app.schemas.signals import SignalSet
from backend.app.services.evidence import KST  # 판정 입력의 날짜를 근거 카드와 같은 한국 시각으로 (09-29 D8)

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
    tool_calls: list[dict] = field(default_factory=list)  # [{"name": ..., "arguments": "<JSON 문자열>"}]
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
      connection    연결 실패·시간 초과          no_choices  200인데 답 없이 error만 옴
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
        resp = client.chat.completions.create(**kwargs, extra_body=extra_body)
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
    calls = [{"name": c.function.name, "arguments": c.function.arguments} for c in (msg.tool_calls or [])]
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
    max_tokens: int | None = None,
) -> LLMResult:
    """OpenRouter에 묻고 답을 돌려준다. 429·502·503이면 잠깐 쉬고 한 번 더 묻는다. 출력 검증은 아직 안 한다.

    Args:
        messages: [{"role": "system"|"user"|..., "content": ...}]
        model: 생략하면 LLM_MODEL
        response_format: 구조화 출력. {"type": "json_schema", "json_schema": {...}}
        tools: tool 정의 목록 (OpenAI 형식)
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
    if max_tokens:
        kwargs["max_tokens"] = max_tokens

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = _call_once(kwargs)
            result.attempts = attempt
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
        # null = 판정 보류. 위치가 아예 없을 때 등 (skills/ais-reliability 되묻기 조건)
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
                    "required": ["plain_explanation", "next_stage", "needs_broker"],
                    "properties": {
                        "plain_explanation": {"type": "string"},
                        "next_stage": {"type": ["string", "null"]},
                        "needs_broker": {"type": "boolean"},
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
    """LLM이 쓴 통관 해설. 단계 이름·코드·이력은 코드 값(CustomsRecord)을 쓰고, 여기서는 설명 셋만 받는다 (C1 CustomsInfo)."""

    plain_explanation: str
    next_stage: str | None
    needs_broker: bool


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


# 호출마다 넣을 Skill 폴더 (09-30 결정). 전에는 모든 호출에 4개 전부(약 6,600자, 판정 입력의 약 70%)를 넣었다.
# 각 호출이 받는 자료를 기준으로, 그 자료를 읽는 데 필요한 Skill만 넣는다. 넣는 Skill은 여전히 통째로다 (RAG 아님)
AIS, CUSTOMS, PORT = "ais-reliability", "customs-stages", "port-busan"
ALL_SKILLS = (AIS, CUSTOMS, PORT)
JUDGE_SKILLS = (AIS, CUSTOMS)       # 신호 · 판정 표 · 통관 해설. 판정 입력에 부두 · 하역 장소가 없어 부두 Skill은 안 넣는다
PICK_SKILLS = (AIS,)                # 동명 선박 · 후보 판단. 통관 · 부두는 쓰지 않는다
FOLLOW_UP_SKILLS = ALL_SKILLS       # 이전 응답 전체(통관 · 하역 장소 포함)를 근거로 답하므로 전부
GRADE_SKILLS = (CUSTOMS,)           # 통관 해설 채점은 통관 단계 표만 기준으로 한다 (평가 때만)


def _skills_text(folders: tuple[str, ...] = ALL_SKILLS) -> str:
    """고른 Skill 폴더의 .md를 파일 이름과 함께 이어 붙인다. RAG 없이 통째로 넣는다 (CLAUDE.md)."""
    parts = []
    for path in sorted(p for folder in folders for p in (SKILL_DIR / folder).rglob("*.md")):
        # Windows 문제: relative_to()를 그대로 문자열로 쓰면 Windows에서 "ais-reliability\SKILL.md"처럼 역슬래시가 된다.
        # 그러면 LLM이 보는 파일 이름이 OS마다 달라지고 test_judge.py::test_system_has_prompt_and_all_skills가 Windows에서만 깨진다.
        # as_posix()로 어느 OS에서든 "/"로 맞춘다 (Docker·Mac은 원래 "/"라 동작 변화 없음)
        parts.append(f"# 파일: skills/{path.relative_to(SKILL_DIR).as_posix()}\n\n{path.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)


def _judge_input(signals: SignalSet, customs: CustomsRecord | None, days_margin: int | None,
                 trusted_eta: datetime | None = None, sale_due_date: date | None = None,
                 table_verdict: str | None = None, verdict_mode: str | None = None) -> str:
    """LLM에 넘길 자료를 JSON 문자열로 만든다. B/L 번호(bl_masked)와 MRN은 판정에 필요 없어 뺀다 (CLAUDE.md, SDD 3.5).

    날짜는 한국 시각으로 준다 (09-29 D8). 전에는 여유 일수 숫자만 줘서 "언제 와요?"에 날짜로 답하지 못했고,
    사용자가 말한 판매일을 근거에 없는 숫자로 보고 검증(V7)이 막기도 했다 (평가 F06 "9월 23일"). 판매일이 없으면 null이다 (선택 입력, 09-29 결정).
    calc_eta는 남은 거리 ÷ 현재 속도로 코드가 계산한 대략값이다. 참고용이라 판정 근거로 쓰지 않게 지시문에 적는다.
    table_verdict·verdict_mode (09-30 D7, services/verdict.py): 코드가 판정 표로 낸 등급과, LLM이 그 등급을
    그대로 써야 하는지(fixed) 표 이상에서 고를 수 있는지(raise_only, 회색 지대)를 알려 준다.
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
        "customs": customs.model_dump(mode="json", exclude={"bl_masked", "mrn", "fetched_at"}) if customs else None,
    }
    return json.dumps(data, ensure_ascii=False)


def _kst(moment: datetime | None) -> str | None:
    """시각을 한국 시각 "YYYY-MM-DD HH:MM"으로. 근거 카드(services/evidence.py)와 같은 모양이라 V7 대조가 맞는다."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(KST).strftime("%Y-%m-%d %H:%M")


def _ask_json(prompt_name: str, user_content: str, schema_name: str, schema: dict,
              output_model: type[BaseModel], model: str | None, feedback: str | None = None,
              skills: tuple[str, ...] = ALL_SKILLS) -> LLMAnswer:
    """여러 함수가 같이 쓰는 한 번의 문답. 지시문(Langfuse) + skills 문서를 system에, 자료를 user에 넣고
    구조화 출력으로 받은 JSON을 output_model로 검사한다.
    skills는 넣을 Skill 폴더다 (JUDGE_SKILLS 등). 빈 튜플이면 넣지 않는다: 판단 기준이 필요 없는 호출(서류 칸 옮겨 적기)용.

    Raises:
        LLMError: 호출 실패, 또는 답이 JSON이 아니거나 모양이 output_model과 다를 때.
                  내용 규칙(V1~V7) 검사와 재시도는 C-7 validate.py가 맡는다.
    """
    if replay.replay_enabled() and not (model or os.environ.get("LLM_MODEL")):
        return _replay_answer(prompt_name, user_content, output_model)
    prompt = get_prompt(prompt_name)
    system = f"{prompt.text}\n\n{_skills_text(skills)}" if skills else prompt.text
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]
    if feedback:
        # 검증 위반을 붙여 다시 묻는 경우 (C-7). 코드가 쓴 지시라 자료(user_content)와 섞지 않고 따로 보낸다
        messages.append({"role": "user", "content": f"Your previous answer broke these rules. Answer again in the same JSON format and fix them:\n{feedback}"})
    # 트레이스 입력은 코드가 모은 자료(user_content)만. 지시문·skills 전문은 길고 매번 같아서 빼고 prompt_version으로 가린다
    generation = start_generation(prompt_name, user_content, prompt.source)
    try:
        result = chat(
            messages,
            model=model,
            response_format={"type": "json_schema", "json_schema": {"name": schema_name, "strict": True, "schema": schema}},
        )
    except LLMError as e:
        end_generation(generation, None, prompt.version, error=str(e))
        raise
    try:
        output = output_model.model_validate_json(result.content or "")
    except ValidationError as e:
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
    return LLMAnswer(output=output, llm=result, prompt_version=prompt.version)


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
) -> LLMAnswer:
    """2층 판정. output은 JudgeOutput. 자료는 코드가 모은 신호·통관·여유 일수·날짜 (SDD 4.1 7단계, 09-29 D8).
    feedback은 출력 검증(C-7) 위반 내용이다. 주면 위반을 고쳐 다시 답하라고 붙인다 (SDD 5.7 재시도)."""
    return _ask_json(JUDGE_PROMPT, _judge_input(signals, customs, days_margin, trusted_eta, sale_due_date,
                                                table_verdict, verdict_mode),
                     "judge", JUDGE_SCHEMA, JudgeOutput, model, feedback=feedback, skills=JUDGE_SKILLS)


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


def answer_follow_up(question: str, response: AgentResponse, *, model: str | None = None,
                     feedback: str | None = None) -> LLMAnswer:
    """이미 나온 판정(response)에 대한 후속 질문에 답한다. output은 FollowUpOutput.

    질문은 사용자 자유 입력이라 데이터로만 넘긴다 (SDD 7절 신뢰 경계). 300자 제한은 AgentRequest가 이미 건다.
    feedback: 앞 답이 검증 규칙(V1·V7)을 어겼을 때 어긴 내용. judge()와 같은 방식으로 다시 묻는다 (09-29, 평가 F06)
    """
    data = {
        "result": response.model_dump(mode="json", exclude={"trace_id", "vessel_candidates"}),
        "question": question,
    }
    return _ask_json(FOLLOW_UP_PROMPT, json.dumps(data, ensure_ascii=False), "follow_up",
                     FOLLOW_UP_SCHEMA, FollowUpOutput, model, feedback=feedback, skills=FOLLOW_UP_SKILLS)


# ── 서류 칸 뽑기 extract_doc_fields() ────────────────────────────
# docs/specs/document-extract.md 4단계: OCR 글자에서 6칸을 옮겨 적는다. 판단은 하지 않는다.
# B/L 번호는 코드(doc_ocr.take_bl)가 먼저 뽑아 [BL]로 가린 글자만 받는다 (CLAUDE.md).
# 옮긴 값이 글자에 실제로 있는지는 doc_ocr.check_fields가 검사한다.

DOC_EXTRACT_PROMPT = "marvia-doc-extract"
DOC_EXTRACT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["vessel", "voyage", "eta", "pol", "pod", "item"],  # strict 모드는 모든 칸이 required
    "properties": {
        "vessel": {"type": ["string", "null"]},
        "voyage": {"type": ["string", "null"]},
        "eta": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
        "pol": {"type": ["string", "null"]},
        "pod": {"type": ["string", "null"]},
        "item": {"type": ["string", "null"]},
    },
}


class DocFieldsOutput(BaseModel):
    vessel: str | None
    voyage: str | None
    eta: str | None  # 모양 검사는 doc_ocr.check_fields가 한다. 여기서 date로 바꾸면 틀린 모양이 형식 오류로 바뀌어 원인이 가려진다
    pol: str | None
    pod: str | None
    item: str | None


def extract_doc_fields(masked_text: str, *, model: str | None = None) -> LLMAnswer:
    """B/L을 가린 OCR 글자에서 선명·항차·ETA·선적항·양하항·품명을 옮겨 적는다. output은 DocFieldsOutput.

    OCR 글자는 사용자 서류라 데이터로만 넘긴다 (SDD 7절 신뢰 경계, 프롬프트에도 명시).
    """
    return _ask_json(DOC_EXTRACT_PROMPT, masked_text, "doc_extract", DOC_EXTRACT_SCHEMA, DocFieldsOutput, model,
                     skills=())


# ── 통관 해설 채점 grade_customs() ─────────────────────────────
# 평가 전용 LLM-as-judge (SDD 5.12 customs_explanation, 가이드 평가 4축 ④ "생성 모델 ≠ 판정 모델").
# 서비스 요청에서는 부르지 않는다. evals/judge.py가 평가 실행 때만 부른다.
# 판정 LLM이 쓴 통관 해설(단계 뜻 · 다음 단계 · 관세사 필요 여부)을 customs-stages Skill 표 기준으로 0/1 채점한다.

JUDGE_EVAL_PROMPT = "marvia-judge-eval"  # Langfuse 프롬프트 이름 (SDD 5.6 표)
GRADE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["score", "reason"],
    "properties": {
        "score": {"type": "integer", "enum": [0, 1], "description": "지시문의 다섯 조건을 모두 지키면 1"},
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
