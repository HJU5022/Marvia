"""LLM 호출은 이 파일 하나로 모읍니다 (작업 C-6, SDD 1.1).

라우터나 UI 코드가 openai를 직접 import하지 않게 하세요.
3차에서 이 파일 내부만 갈아끼우면 나머지는 그대로 돌아갑니다.

여기서 책임지는 것:
  - 출력 형식 검사 (Pydantic)          ← judge()가 JSON 모양만 본다. 내용 7규칙은 C-7 validate.py
  - 실패 시 재시도와 폴백, 라우팅       ← 재시도 1회만 있음. 폴백·라우팅·요청당 시간 예산은 TODO
  - Langfuse 트레이스 남기기            ← _ask_json()이 호출마다 generation 하나 (observability/langfuse.py, SDD 5.11)

지금 있는 것:
  chat()   OpenRouter(또는 Vertex AI)에 한 번 묻는다. 과부하·한도(503·429)면 한 번 더 묻는다
  judge()            2층 판정. 프롬프트(Langfuse) + skills/ 문서 + 코드가 모은 자료를 주고 판정 JSON을 받는다 (SDD 4.1 7단계, 5.6)
  pick_vessel()      이름 같은 후보가 여럿일 때 어느 배인지 고른다 (SDD 5.5, C-5)
  answer_follow_up() 판정 뒤 후속 질문에 근거 안에서만 답한다 (C-9)
  extract_doc_fields() 서류 사진 OCR 글자에서 선명·항차·ETA 등 6칸과 B/L 조건·연락처를 옮겨 적는다 (docs/specs/document-extract.md)
  write_memory()     조회·대화 뒤 메모장에 줄 단위 명령만 낸다. 적용은 services/account/memory.py가 한다 (docs/specs/memory.md)

모델 자리 (.env, 계약 C8):
  LLM_MODEL           서비스가 쓰는 모델. 위 네 함수 전부 (이름 바꿈, 전 MODEL_A)
  MEMORY_MODEL        기억 뽑기(write_memory)만. 비어 있으면 기억 뽑기를 건너뛴다 (계획 gpt-4o-mini)
  EVAL_COMPARE_MODEL  평가에서 비교할 두 번째 모델. run_eval --config c에서만 LLM_MODEL 자리에 들어간다 (전 MODEL_B)
  EVAL_GRADER_MODEL   평가 채점자. 통관 해설 채점(grade_customs)만. 채점받는 모델과 달라야 한다 (전 JUDGE_MODEL.
                      판정 함수 judge()와 헷갈려서 바꿈)

어디로 보내나 (모델 이름 앞머리로 가른다):
  "vertex/"로 시작   Vertex AI (GCP 크레딧). 예: LLM_MODEL=vertex/google/gemini-2.5-flash
                     키 대신 `gcloud auth application-default login` 로그인 정보(ADC)를 쓴다.
                     Cloud Run에서는 서비스 계정에 Vertex AI 사용자 권한이 있어야 한다
                     VERTEX_THINKING_BUDGET=0이면 Gemini가 생각 없이 바로 답한다. 비우면 모델 기본값 (_vertex_thinking)
  그 밖             OpenRouter. 예: LLM_MODEL=openai/gpt-4o-mini
  개발 중엔 크레딧(vertex/)으로 돌리고, 최종 테스트 때.env 한 줄만 되돌리려고 두 길을 같이 둔다.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import openai
from openai import OpenAI
from pydantic import BaseModel, ValidationError

from backend.app.clients import replay  # REPLAY_MODE 녹화 답 재생 (_replay_answer)
from backend.app.services.account import quota  # 1명당 하루 토큰 한도 (docs/specs/token-quota.md)
from backend.app.observability.langfuse import end_generation, get_prompt, start_generation
from backend.app.observability.logging import llm_usage_var, request_id_var  # 요청당 토큰 상한을 요청 안에서만 센다
from backend.app.schemas.agent import AgentResponse, VesselCandidate
from backend.app.schemas.customs import CustomsRecord
from backend.app.schemas.signals import SignalSet
from backend.app.services.judge import guard  # 통관 단계명 주입 거르기 (_clean_customs)
from backend.app.services.llm_config import (
    BASE_URL,
    CUT_FINISH_REASONS,
    MAX_ATTEMPTS,
    MAX_TOOL_ROUNDS,
    QUEUE_WAIT_SEC,
    RATE_LIMIT_ATTEMPTS,
    RATE_LIMIT_MAX_WAIT_SEC,
    REPLAY_LLM_DIR,
    VERTEX_PREFIX,
    VERTEX_SCOPES,
    VERTEX_URL,
)
from backend.app.services.llm_types import LLMAnswer, LLMError, LLMFormatError, LLMResult, _DeadlineExceeded
from backend.app.services.llm_schemas import (
    CHAT_AGENT_PROMPT,
    CHAT_AGENT_SCHEMA,
    CHAT_ROUTE_PROMPT,
    CHAT_ROUTE_SCHEMA,
    ChatAgentOutput,
    ChatRouteOutput,
    DOC_EXTRACT_PROMPT,
    DOC_EXTRACT_SCHEMA,
    DocFieldsOutput,
    FOLLOW_UP_PROMPT,
    FOLLOW_UP_SCHEMA,
    FollowUpOutput,
    GRADE_SCHEMA,
    GradeOutput,
    JUDGE_EVAL_PROMPT,
    JUDGE_PROMPT,
    JUDGE_SCHEMA,
    JudgeOutput,
    MEMORY_PROMPT,
    MEMORY_SCHEMA,
    MemoryOpsOutput,
    PICK_PROMPT,
    PICK_SCHEMA,
    PORT_MATCH_PROMPT,
    PORT_MATCH_SCHEMA,
    PickOutput,
    PortMatchOutput,
    TITLE_PROMPT,
    TITLE_SCHEMA,
    TitleOutput,
)
from backend.app.services.llm_support import (
    _hours_since,
    _judge_input,
    _loose_json,
    _replay_matches,
    _status_kind,
    _summed,
    _vertex_thinking,
    container_tokens,
    hide_containers,
)

TIMEOUT_SEC = 60.0  # 호출 하나가 요청 전체 시간을 다 먹지 않게 하는 상한. p95 실측 뒤 조정

RETRY_WAIT_SEC = 2.0  # 과부하는 잠깐 뒤 풀리는 경우가 많다. 실측 전 임시값

logger = logging.getLogger(__name__)


def _client() -> OpenAI:
    # 키는 호출할 때 읽는다. import 시점에.env가 아직 안 읽혔을 수 있어서 (clients/*.py와 같은 방식).
    # max_retries=0: openai SDK는 기본으로 몰래 2번 재시도한다. 재시도는 아래 chat()이 한 곳에서만 한다.
    # 키가 없으면 KeyError로 서버가 500을 내는 대신 LLMError로 올린다. 라우터가 판정 없이 partial로 돌려준다
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
    로그인 정보가 없거나 토큰을 못 받으면 _client()와 같이 LLMError로 올린다 (partial 경로).
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


def _create_with_deadline(client: OpenAI, kwargs: dict, extra_body: dict | None, timeout: float | None = None):
    """요청 하나를 별도 스레드에서 보내고, 최대 TIMEOUT_SEC초만 기다린다.

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
    worker.join(timeout or TIMEOUT_SEC)  # timeout: 호출마다 정하는 짧은 상한 (기억 뽑기 10초). 없으면 TIMEOUT_SEC
    if worker.is_alive():
        raise _DeadlineExceeded()
    if "error" in box:
        raise box["error"]
    return box["resp"]


def _call_once(kwargs: dict) -> LLMResult:
    """OpenRouter 또는 Vertex AI를 딱 한 번 부른다. 실패는 전부 LLMError로 바꿔서 올린다."""
    kwargs = dict(kwargs)
    timeout = kwargs.pop("_timeout", None)  # chat(timeout=)이 실어 둔 호출별 시간 상한. API에는 보내지 않는다
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
        # OpenRouter의 모델 단위 "지원" 표시는 제공사 합계라, 이게 없으면 미지원 제공사로 조용히 넘어갈 수 있다.
        extra_body = {"provider": {"require_parameters": True}}

    start = time.monotonic()
    try:
        # 호출별 상한이 없으면 예전 모양 그대로 부른다 (테스트가 세 인자 가짜로 바꿔 끼운다)
        resp = _create_with_deadline(client, kwargs, extra_body, **({"timeout": timeout} if timeout else {}))
    except _DeadlineExceeded:
        # 시간 상한에 닿았다. 다시 부르지 않는다 (RETRYABLE_CODES 주석). code가 없어 retryable도 False다
        raise LLMError(f"{model}: {(timeout or TIMEOUT_SEC):g}초 안에 답이 없음",
                       latency_ms=int((time.monotonic() - start) * 1000), kind="timeout") from None
    except openai.APIStatusError as e:  # HTTP 4xx·5xx로 온 실패
        raise LLMError(f"{model}: HTTP {e.status_code} {e.message}", code=e.status_code,
                       latency_ms=int((time.monotonic() - start) * 1000), kind=_status_kind(e.status_code),
                       retry_after=_retry_after(e)) from e
    except openai.APIConnectionError as e:  # 연결 실패·타임아웃. 다시 부르지 않는다 (위 RETRYABLE_CODES 주석)
        raise LLMError(f"{model}: 연결 실패 {type(e).__name__}",
                       latency_ms=int((time.monotonic() - start) * 1000), kind="connection") from e
    latency_ms = int((time.monotonic() - start) * 1000)

    # OpenRouter는 제공사가 실패하면 HTTP 200 안에 choices 없이 error만 담아 보낼 때가 있다 (스모크 테스트).
    # 그대로 두면 choices[0]에서 TypeError가 나서 원인이 가려지므로, 에러 내용과 코드를 그대로 올린다.
    if not resp.choices:
        error = (resp.model_extra or {}).get("error") or {}
        raise LLMError(f"{model}: 응답에 choices 없음, error={error}", code=error.get("code"), latency_ms=latency_ms,
                       kind="no_choices")

    # Gemini(Vertex)는 생각(reasoning) 토큰으로 한도를 다 쓰면 message 없이 finish_reason=length만 준다
    # (실패 훈련 judge_truncated). 그대로 읽으면 AttributeError로 죽고, 라우터는 LLMError만 받으니 500이 났다.
    # 빈 답으로 받으면 _ask_json이 finish_reason을 보고 truncated로 올리고, 라우터가 재시도·failed로 처리한다
    msg = resp.choices[0].message or SimpleNamespace(content=None, tool_calls=None)
    # id: 도구 결과를 돌려줄 때 어느 호출의 결과인지 짝짓는 값 (role=tool 메시지의 tool_call_id, 후속 질문 도구)
    # extra_content: Vertex의 Gemini 3.x가 도구 호출마다 붙여 주는 thought_signature({"google": {"thought_signature":...}}).
    # 도구 결과를 돌려줄 때 그대로 되돌려 보내야 한다. 없으면 HTTP 400 "missing a thought_signature" (실험 첫 실행에서 확인).
    # SDK 타입에는 없는 칸이라 model_extra에서 읽는다. 없는 제공사(OpenRouter 등)는 None이고 요청에 넣지 않는다
    calls = [{"id": c.id, "name": c.function.name, "arguments": c.function.arguments,
              "extra_content": (getattr(c, "model_extra", None) or {}).get("extra_content")} for c in (msg.tool_calls or [])]
    usage = resp.usage
    completion_tokens = usage.completion_tokens if usage else None
    # Vertex는 생각(reasoning) 토큰을 completion_tokens에 넣지 않고 completion_tokens_details에 따로 준다
    # (curl: prompt 11 + completion 1 + reasoning 33 = total 45). 요금은 생각 토큰도 출력으로 받으므로
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
        # OpenRouter 전용 필드라 SDK 타입에는 없다. 요청 옵션 없이 매 응답에 들어온다 (OpenRouter Usage Accounting 문서)
        cost=getattr(usage, "cost", None) if usage else None,
        latency_ms=latency_ms,
        finish_reason=getattr(resp.choices[0], "finish_reason", None),
    )


def _retry_after(e: openai.APIStatusError) -> float | None:
    """429 응답의 Retry-After 헤더를 초로 읽는다. 없거나 숫자가 아니면 None (HTTP 날짜 형식은 쓰지 않는다)."""
    try:
        value = e.response.headers.get("retry-after") if e.response is not None else None
        return float(value) if value else None
    except (TypeError, ValueError):
        return None


# 서버 전체 동시 호출 상한(큐잉). LLM_MAX_CONCURRENCY가 처음 읽힐 때 한 번 만든다. 값이 없거나 0이면 None(줄 없음)
_queue: threading.BoundedSemaphore | None = None
_queue_size: int | None = None
_queue_lock = threading.Lock()


def _llm_queue() -> threading.BoundedSemaphore | None:
    """LLM_MAX_CONCURRENCY만큼 자리가 있는 줄을 돌려준다. 설정이 바뀌면(테스트) 새로 만든다."""
    global _queue, _queue_size
    try:
        size = int(os.environ.get("LLM_MAX_CONCURRENCY") or 0)
    except ValueError:
        size = 0
    with _queue_lock:
        if size != _queue_size:
            _queue, _queue_size = (threading.BoundedSemaphore(size) if size > 0 else None), size
        return _queue


def _request_token_cap() -> int | None:
    """요청당 토큰 상한(MAX_TOKENS_PER_REQUEST, .env). 비우거나 0이면 None(상한 없음). ADR 0018에서 칸만 있던 값이다."""
    try:
        cap = int(os.environ.get("MAX_TOKENS_PER_REQUEST") or 0)
    except ValueError:
        return None
    return cap if cap > 0 else None


def _request_usage() -> dict | None:
    """지금 처리 중인 HTTP 요청의 사용량 dict(미들웨어가 요청마다 새로 만든다). 요청 밖(스크립트·평가·테스트)은 None.

    요청 밖에서도 기본값 dict가 있지만 모든 호출이 함께 쓰는 하나라서, 거기에 쌓으면 평가 실행기가 상한에 걸린다.
    그래서 request_id가 있는 요청 안에서만 센다.
    """
    return llm_usage_var.get() if request_id_var.get() else None


def _call_queued(kwargs: dict) -> LLMResult:
    """줄(LLM_MAX_CONCURRENCY)에 서서 자리를 얻은 뒤 _call_once를 부른다. QUEUE_WAIT_SEC 안에 자리가 안 나면 queue_full."""
    queue = _llm_queue()
    if queue is None:
        return _call_once(kwargs)
    if not queue.acquire(timeout=QUEUE_WAIT_SEC):
        raise LLMError(f"{kwargs['model']}: 동시 호출 상한에서 {QUEUE_WAIT_SEC:g}초 넘게 기다림", kind="queue_full")
    try:
        return _call_once(kwargs)
    finally:
        queue.release()


def chat(
    messages: list[dict],
    *,
    model: str | None = None,
    response_format: dict | None = None,
    tools: list[dict] | None = None,
    tool_choice: str | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
) -> LLMResult:
    """OpenRouter에 묻고 답을 돌려준다. 출력 검증은 아직 안 한다.

    실패 처리 (가이드 원칙 2, llm_config 주석):
      500·502·503   RETRY_WAIT_SEC 쉬고 한 번 더 (최초 포함 MAX_ATTEMPTS번)
      429           2초 → 4초처럼 늘려 가며(Retry-After가 있으면 그 값, 상한 RATE_LIMIT_MAX_WAIT_SEC) RATE_LIMIT_ATTEMPTS번까지.
                    그래도 429면 LLM_FALLBACK_MODEL로 한 번 더
      동시 호출      LLM_MAX_CONCURRENCY 자리만큼만 나가고 나머지는 줄을 선다 (_call_queued)
      요청당 비용    이 요청이 쓴 토큰이 MAX_TOKENS_PER_REQUEST에 닿았으면 부르지 않고 request_budget으로 올린다

    Args:
        messages: [{"role": "system"|"user"|..., "content":...}]
        model: 생략하면 LLM_MODEL
        response_format: 구조화 출력. {"type": "json_schema", "json_schema": {...}}
        tools: tool 정의 목록 (OpenAI 형식)
        tool_choice: "none"이면 도구를 주되 부르지 말고 답하라는 뜻. 도구 호출 상한에 닿았을 때 쓴다 (_ask_json)
        max_tokens: 출력 상한
        timeout: 이 호출만의 전체 시간 상한(초). 없으면 TIMEOUT_SEC (기억 뽑기가 10초로 줄여 쓴다)

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
    if timeout:
        kwargs["_timeout"] = timeout  # _call_once가 꺼낸다

    # 요청당 비용 상한: 이 요청이 이미 상한만큼 썼으면 더 부르지 않는다. 부르는 쪽은 LLMError를 받아
    # 판정 표 폴백·규칙 답 같은 기존 부분 응답 경로로 간다 (판정은 코드 표가 정하므로 등급은 나간다)
    usage, cap = _request_usage(), _request_token_cap()
    if usage is not None and cap and usage.get("request_tokens", 0) >= cap:
        raise LLMError(f"{model}: 이 요청의 토큰 {usage.get('request_tokens', 0)}개가 요청당 상한 {cap}개에 닿음",
                       kind="request_budget")

    attempt = 0
    wait = RETRY_WAIT_SEC
    while True:
        attempt += 1
        try:
            result = _call_queued(kwargs)
            result.attempts = attempt
            tokens = (result.prompt_tokens or 0) + (result.completion_tokens or 0)
            # 1명당 하루 토큰 한도에 쌓는다 (services/account/quota.py, docs/specs/token-quota.md). 이 요청은 끝까지 답하고 다음 요청부터 막는다
            quota.add(tokens)
            if usage is not None:
                usage["request_tokens"] = usage.get("request_tokens", 0) + tokens  # 요청당 상한용 누계
            return result
        except LLMError as e:
            rate_limited = e.code == 429
            limit = RATE_LIMIT_ATTEMPTS if rate_limited else MAX_ATTEMPTS
            if e.retryable and attempt < limit:
                # 429는 제공사가 알려 준 시간을 따르고, 없으면 기다리는 시간을 두 배씩 늘린다. 둘 다 상한을 둔다
                delay = min(getattr(e, "retry_after", None) or wait, RATE_LIMIT_MAX_WAIT_SEC) if rate_limited else RETRY_WAIT_SEC
                logger.warning("llm %s 실패(code %s), %.1f초 뒤 재시도 %d/%d",
                               kwargs["model"], e.code, delay, attempt + 1, limit)
                time.sleep(delay)
                if rate_limited:
                    wait *= 2
                continue
            fallback = os.environ.get("LLM_FALLBACK_MODEL")
            if rate_limited and fallback and fallback != kwargs["model"]:
                # 같은 모델이 계속 한도에 막히면 다른 모델로 한 번만 돌린다. 결과의 model 칸과 Langfuse에 바뀐 모델이 남는다
                logger.warning("llm %s 레이트 리밋 계속, 대체 모델 %s로 한 번 더", kwargs["model"], fallback)
                kwargs = {**kwargs, "model": fallback}
                continue
            raise


# ── 2층 판정 judge() ─────────────────────────────────────────────
# SDD 4.1 7단계: 신호·통관·여유 일수를 받아 verdict·reasons·conflicts·actions·answer를 받는다.
# 자료는 코드가 미리 다 모아서 준다. LLM이 도구를 부르지 않는다 (SDD 4.1 방식).

SKILL_DIR = Path(__file__).resolve().parents[3] / "skills"  # 레포 루트의 skills/. Dockerfile도 같은 자리에 복사한다


# 호출마다 넣을 Skill 폴더. 전에는 모든 호출에 Skill 전부(약 6,600자, 판정 입력의 약 70%)를 넣었다.
# 각 호출이 받는 자료를 기준으로, 그 자료를 읽는 데 필요한 Skill만 넣는다. 넣는 Skill은 여전히 통째로다 (RAG 아님)
# 폴더 안의 *.md를 모두 넣는다: SKILL.md(도메인 지식·설명법)와 rules.md(코드가 읽는 재료와 그 뜻) (Skill 구조)
#   ais-reliability  AIS 값 읽는 법(오류 사례, 출처 우선순위), 신호 7종 기준
#   customs-stages   통관 단계 목록(rules.md)과 해설법
#   port-busan       부두 이름 뜻, 하역 장소 문장, 부산 기준값
#   cargo-verdict    등급 판정 표(rules.md), 등급 뜻·결과 설명법·되묻기와 실패 결과 설명법 (신설)
#   import-basics    수입 실무 기초(B/L 번호 찾는 곳, 포워더 확인, A/N 같은 낱말). 웹 검색을 없애고 고정 문서로 옮겼다 (docs/adr/0020).
#                    채팅 답과 후속 질문에만 넣는다. 판정(JUDGE)·후보 판단(PICK)·채점(GRADE)에는 넣지 않아 판정 입력이 그대로다
AIS, CUSTOMS, PORT, VERDICT = "ais-reliability", "customs-stages", "port-busan", "cargo-verdict"
IMPORT = "import-basics"
ALL_SKILLS = (AIS, CUSTOMS, PORT, VERDICT)
JUDGE_SKILLS = (AIS, CUSTOMS, VERDICT)  # 신호 읽기 · 통관 해설 · 등급 설명. 판정 입력에 부두 · 하역 장소가 없어 부두 Skill은 안 넣는다
PICK_SKILLS = (AIS,)                    # 동명 선박 · 후보 판단. 통관 · 부두 · 등급은 쓰지 않는다
FOLLOW_UP_SKILLS = ALL_SKILLS + (IMPORT,)  # 이전 응답 전체(등급 · 통관 · 하역 장소 · 되묻기 문구 포함)를 근거로 답하므로 전부, 수입 실무 기초까지
GRADE_SKILLS = (CUSTOMS,)               # 통관 해설 채점은 통관 단계 목록(customs-stages/rules.md)만 기준으로 한다 (평가 때만)


def skills_reference(folders: tuple[str, ...] = ALL_SKILLS, prompt_name: str | None = None) -> str:
    """검증 V9·V10(validate.py)이 "답에 써도 되는 낱말"의 출처로 쓰는 원문: LLM이 받은 Skill 문서와 지시문.
    지시문 낱말을 넣는 이유: gpt-4o-mini가 판정 지시문 첫 줄의 "cargo"를 한국어 답에 섞어 판정 출력 228개 중 19개가
    V9에 걸렸다. 지시문에 있는 낱말은 주입이 끼워 넣은 표식이 아니다."""
    return _skills_text(folders) + ("\n\n" + get_prompt(prompt_name).text if prompt_name else "")


def _skills_text(folders: tuple[str, ...] = ALL_SKILLS) -> str:
    """고른 Skill 폴더의.md를 파일 이름과 함께 이어 붙인다. RAG 없이 통째로 넣는다 (CLAUDE.md)."""
    parts = []
    for path in sorted(p for folder in folders for p in (SKILL_DIR / folder).rglob("*.md")):
        # Windows 문제: relative_to()를 그대로 문자열로 쓰면 Windows에서 "ais-reliability\SKILL.md"처럼 역슬래시가 된다.
        # 그러면 LLM이 보는 파일 이름이 OS마다 달라지고 test_judge.py::test_system_has_prompt_and_all_skills가 Windows에서만 깨진다.
        # as_posix()로 어느 OS에서든 "/"로 맞춘다 (Docker·Mac은 원래 "/"라 동작 변화 없음)
        parts.append(f"# 파일: skills/{path.relative_to(SKILL_DIR).as_posix()}\n\n{path.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)


def _ask_json(prompt_name: str, user_content: str, schema_name: str, schema: dict,
              output_model: type[BaseModel], model: str | None, feedback: str | None = None,
              skills: tuple[str, ...] = ALL_SKILLS, tools: list[dict] | None = None,
              run_tool: Callable[[str, dict], dict] | None = None, context: str | None = None,
              timeout: float | None = None) -> LLMAnswer:
    """여러 함수가 같이 쓰는 한 번의 문답. 지시문(Langfuse) + skills 문서를 system에, 자료를 user에 넣고
    구조화 출력으로 받은 JSON을 output_model로 검사한다.
    skills는 넣을 Skill 폴더다 (JUDGE_SKILLS 등). 빈 튜플이면 넣지 않는다: 판단 기준이 필요 없는 호출(서류 칸 옮겨 적기)용.
    tools·run_tool: LLM이 직접 부를 도구 목록(OpenAI 형식)과, 부른 도구를 실제로 실행하는 함수 (후속 질문만).
    run_tool(이름, 인자)는 도구 결과 dict를 돌려준다. 부른 기록은 LLMAnswer.tool_calls에 담는다.
    context: 로그인 사용자의 기억 블록(<user_cargo>·<user_memory>, services/account/memory.compose_blocks). 판정·후속 질문만 쓴다.
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
    # 기억 블록은 가리지 않고 그대로 남긴다 (결정 8: 운영자가 보는 기록. DB 줄은 탈퇴·삭제 때 지운다)
    generation = start_generation(prompt_name, f"{context}\n\n{user_content}" if context else user_content, prompt.source)
    response_format = {"type": "json_schema", "json_schema": {"name": schema_name, "strict": True, "schema": schema}}
    called: list[dict] = []
    # 이번 생성에서 부른 chat() 결과 전부. 도구 고리는 chat()을 여러 번 부르는데 기록에 마지막 한 번만 남아
    # Langfuse 토큰·비용이 실제보다 적게 보였다. 끝낼 때 _summed로 합쳐 남긴다
    rounds: list[LLMResult] = []
    try:
        # 도구가 없으면 한 번 묻고 끝난다 (판정·배 고르기 등, 지금까지와 같음: response_format을 붙인 한 번의 호출).
        # 도구가 있으면(후속 질문·채팅 에이전트) LLM이 도구를 부르는 동안 결과를 돌려주며 다시 묻는다. MAX_TOOL_ROUNDS번 부른 뒤에는
        # tool_choice="none"으로 더 부르지 말고 답하게 한다. 같은 도구를 끝없이 부르는 것을 막는 상한이다 (가이드 Tool trajectory)
        # 도구를 고를 기회가 있는 라운드에는 response_format을 붙이지 않는다: deepseek-v4-flash(OpenRouter)는
        # strict json_schema가 같이 오면 도구를 한 번도 안 부르고 JSON만 낸다. 빼면 바로 맞는 도구를 부른다.
        # 대신 도구를 안 부르고 낸 본문을 JSON으로 읽어 보고, 안 읽히면 같은 대화에 response_format + tool_choice="none"으로 한 번 더 묻는다
        for round_no in range(MAX_TOOL_ROUNDS + 1):
            last_round = round_no == MAX_TOOL_ROUNDS
            if tools and not last_round:
                result = chat(messages, model=model, tools=tools, tool_choice=None, timeout=timeout)
                rounds.append(result)
                if not (run_tool and result.tool_calls):
                    parsed = _loose_json(result.content, output_model)
                    if parsed is not None:
                        result.content = parsed  # 코드 울타리·공백을 벗긴 JSON 본문. 아래 검사가 그대로 읽는다
                    else:
                        # 도구 목록은 그대로 둔다: 기록에 role=tool 메시지가 있으면 제공사가 tools 없는 요청을 거부할 수 있다
                        result = chat(messages, model=model, response_format=response_format, tools=tools,
                                      tool_choice="none", timeout=timeout)
                        rounds.append(result)
                    break
            else:
                result = chat(messages, model=model, response_format=response_format, tools=tools or None,
                              tool_choice="none" if (tools and last_round) else None, timeout=timeout)
                rounds.append(result)
            if not (tools and run_tool and result.tool_calls) or last_round:
                break
            messages.append({"role": "assistant", "content": result.content, "tool_calls": [
                {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]},
                 **({"extra_content": c["extra_content"]} if c.get("extra_content") else {})}  # Gemini 3.x thought_signature 되돌리기 (_call_once)
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
        # 앞 라운드에서 이미 쓴 토큰·비용은 남긴다. 한 번도 답을 못 받았으면 None (전과 같음)
        end_generation(generation, _summed(rounds) if rounds else None, prompt.version, error=str(e))
        raise
    result = _summed(rounds)  # 도구 라운드 합산 (main 점검)
    cut_retried = False  # 끊긴 답을 다시 받은 적이 있나. 한 번만 다시 받는다
    while True:
        try:
            output = output_model.model_validate_json(result.content or "")
            break
        except ValidationError as e:
            if result.finish_reason in CUT_FINISH_REASONS and not cut_retried:
                # 실측: 서류 판독에서 HTTP 200인데 스트림이 JSON 중간(`{"vessel":`)에서 끊기고 finish_reason도 None인 답이
                # 두 번 왔다. 정상 종료(stop)나 토큰 한도(length) 신호가 없는 답은 모델이 끝까지 쓰지 못한 것이라, 같은 대화로
                # 한 번 더 묻는다. chat()은 이 경우를 재시도하지 않으므로(RETRYABLE_CODES는 상태 코드만 본다) 여기서 한다.
                # length는 다시 물어도 같은 한도에 닿으므로 건드리지 않고, 형식이 틀린 stop 답은 프롬프트 문제라 아래에서 올린다
                # 평가 3회 실측: 판정 답 74번 중 4번이 finish_reason="error"·출력 토큰 0으로 JSON 중간에서 끊겼다(제공사 Google).
                # None만 보던 때는 이것이 bad_format(프롬프트 문제)으로 잘못 세져 라우터가 형식 오류 안내를 붙여 다시 물었다
                cut_retried = True
                logger.warning("llm %s 답이 끊김(finish_reason %s), %.1f초 뒤 한 번 더 묻는다",
                               result.model, result.finish_reason, RETRY_WAIT_SEC)
                time.sleep(RETRY_WAIT_SEC)  # 같은 대기 시간을 쓴다
                previous = result
                try:
                    again = chat(messages, model=model, response_format=response_format, tools=tools or None,
                                 tool_choice="none" if tools else None, timeout=timeout)
                except LLMError as call_error:
                    end_generation(generation, previous, prompt.version, output=previous.content, error=str(call_error))
                    raise
                # 다시 물은 답도 한 라운드로 더한다. 토큰·비용은 _summed가 모든 라운드를 합친다 (main과 합칠 때)
                rounds.append(again)
                summed = _summed(rounds)
                # 끊겨서 다시 물은 것은 Langfuse retry_count에도 센다 (end_generation: attempts - 1). _summed는 라운드 수를 재시도로 세지 않는다
                result = replace(summed, attempts=summed.attempts + 1)
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


# ── LLM 녹화 답 재생 ─────────────────────────────
# 채점자가 키 없이 데모 3건을 돌리게 하는 장치다 (SDD 6.1, CLAUDE.md "REPLAY_MODE=true면 키 없이").
# REPLAY_MODE이고 LLM_MODEL이 비어 있을 때만 탄다. LLM_MODEL이 있으면 재생 모드에서도 진짜 LLM을 부른다.
# 녹화 파일: evals/fixtures/replay/llm/<프롬프트 이름>.json. 실제 모델로 데모 입력을 한 번 돌려 받은 답이다.
# 녹화 답은 그 입력에만 맞다. 입력이 다르면(판매일을 다르게 넣는 등) 녹화 답을 쓰지 않고 LLMError를 낸다.
# 틀린 답을 그럴듯하게 보여 주는 것보다, 라우터가 평소처럼 "판정 없이 partial"로 끝나는 편이 정직하다.


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
    """2층 판정. output은 JudgeOutput. 자료는 코드가 모은 신호·통관·여유 일수·날짜 (SDD 4.1 7단계).
    feedback은 출력 검증(C-7) 위반 내용이다. 주면 위반을 고쳐 다시 답하라고 붙인다 (SDD 5.7 재시도).
    memory: 로그인 사용자의 기억 블록 (docs/specs/memory.md). 데이터일 뿐이고 등급은 지금처럼 판정 표가 정한다."""
    return _ask_json(JUDGE_PROMPT, _judge_input(signals, customs, days_margin, trusted_eta, sale_due_date,
                                                table_verdict, verdict_mode),
                     "judge", JUDGE_SCHEMA, JudgeOutput, model, feedback=feedback, skills=JUDGE_SKILLS, context=memory)


# ── 선박 선택 pick_vessel() ─────────────────────────────────────
# SDD 5.5: 후보 2척 이상일 때만 부른다. confidence high만 confirmed, 나머지는 uncertain (판정은 identify.py가 한다).


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
        # 1시간 전 신호를 "오래됐다"고 읽었다 (스모크 테스트). freshness를 코드가 정하는 원칙과 같다 (CLAUDE.md)
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


def answer_follow_up(question: str, response: AgentResponse, *, model: str | None = None,
                     feedback: str | None = None, tools: list[dict] | None = None,
                     run_tool: Callable[[str, dict], dict] | None = None, memory: str | None = None) -> LLMAnswer:
    """이미 나온 판정(response)에 대한 후속 질문에 답한다. output은 FollowUpOutput.

    질문은 사용자 자유 입력이라 데이터로만 넘긴다 (SDD 7절 신뢰 경계). 300자 제한은 AgentRequest가 이미 건다.
    feedback: 앞 답이 검증 규칙(V1·V7)을 어겼을 때 어긴 내용. judge()와 같은 방식으로 다시 묻는다 (평가 F06)

    AIS 목적지 원문(shipfinder dest 근거 카드)은 빼고 넘긴다 (SDD 7절). 아무 배나 AIS에 쓸 수 있는 글자라
    "지금부터 너는 ~" 같은 역할 재설정 문장이 들어올 수 있다. 판정 LLM처럼 코드가 destcode로 계산한
    dest_changed 신호 카드만 남긴다. 화면의 근거 카드에는 그대로 있다 (여기서 빼는 것은 LLM 입력뿐).

    tools·run_tool (D9 B안): 지난 결과에 없는 지금 값(현재 위치·남은 거리·입항 기록)을 물으면 LLM이
    읽기 전용 MCP 도구를 직접 골라 부른다. 목록은 mcp_client.read_only_tools(), 실행은 routers/agent.py가 /mcp로 한다.
    판정 흐름(judge)은 지금처럼 코드가 도구를 부른다.
    memory: 로그인 사용자의 기억 블록 (docs/specs/memory.md 읽기 흐름). judge()와 같은 자리에 넣는다.

    컨테이너 번호는 원문을 넘기지 않고 [CNTR1] 번호표로 바꿔 준다. LLM은 번호표를 그대로 답에 쓰고,
    사용자에게 가는 문장에서는 라우터가 원래 번호로 되돌린다 (container_tokens, restore_containers).
    """
    # customs_detail(UNI-PASS 처리 이력 원문)은 화면 전용이라 LLM에 넘기지 않는다. 중량·관세법인명 등이 들어 있다 (docs/specs/customs-detail.md)
    # 통관 칸 중 컨테이너 번호는 B/L처럼 화물을 특정하는 번호라 원문을 주지 않는다. 칸을 빼지 않고 아래에서 [CNTR1]
    # 번호표로 바꾼다: "컨테이너 번호 뭐야?"에 LLM이 번호표로 답하면 라우터가 화면에서만 원래 번호로 되돌린다.
    # 포워더·선사 이름은 남긴다. "포워더가 어디야" 같은 후속 질문에 답하는 재료다
    result = response.model_dump(mode="json", exclude={"trace_id", "vessel_candidates", "customs_detail"})
    result["evidence"] = [e for e in result.get("evidence") or []
                          if not (e["source"] == "shipfinder" and e["field"] == "dest")]
    # 컨테이너 번호는 번호표로만. customs.container_no는 [CNTR1], [CNTR2]가 되고, 다른 칸(근거 카드 값, 지난 답)에
    # 같은 번호가 있어도 같은 번호표로 바뀐다. 되돌리는 쪽은 routers/agent.py _follow_up (같은 container_tokens로 다시 만든다)
    tokens = container_tokens(response.customs.container_no if response.customs else None)
    if tokens:
        result = hide_containers(result, tokens)
        question = hide_containers(question, tokens)  # 사용자가 질문에 이 화물의 컨테이너 번호를 직접 써도 번호표로만 간다
    # 품명은 해외 화주가 적하목록에 쓴 글자라 주입 모양이면 뺀다 (chat._cargo_summary와 같은 예방 조치)
    if result.get("customs") and guard.looks_like_injection(result["customs"].get("goods_name")):
        result["customs"]["goods_name"] = None
    data = {"result": result, "question": question}
    return _ask_json(FOLLOW_UP_PROMPT, json.dumps(data, ensure_ascii=False), "follow_up",
                     FOLLOW_UP_SCHEMA, FollowUpOutput, model, feedback=feedback, skills=FOLLOW_UP_SKILLS,
                     tools=tools, run_tool=run_tool, context=memory)


# ── 서류 칸 뽑기 extract_doc_fields() ────────────────────────────
# docs/specs/document-extract.md 4단계: OCR 글자에서 6칸을 옮겨 적는다. 판단은 하지 않는다.
# B/L 조건 세 칸(원본 B/L·은행 지시식·운임 + 인코텀즈)과 화물 인도 연락처(회사·역할·회사 전화)도 읽는다.
# 조건은 고르기라 근거 글(*_text)을 글자 그대로 같이 받고, 그 글이 서류에 있는지 코드가 본다 (doc_ocr.check_conditions).
# B/L 번호는 코드(doc_ocr.take_bl)가 먼저 뽑아 [BL]로 가린 글자만 받는다 (CLAUDE.md).
# 옮긴 값이 글자에 실제로 있는지는 doc_ocr.check_fields가 검사한다.


def extract_doc_fields(masked_text: str, *, model: str | None = None) -> LLMAnswer:
    """B/L을 가린 OCR 글자에서 선명·항차·ETA·선적항·양하항·품명과 B/L 조건·연락처를 옮겨 적는다. output은 DocFieldsOutput.

    OCR 글자는 사용자 서류라 데이터로만 넘긴다 (SDD 7절 신뢰 경계, 프롬프트에도 명시).
    """
    return _ask_json(DOC_EXTRACT_PROMPT, masked_text, "doc_extract", DOC_EXTRACT_SCHEMA, DocFieldsOutput, model,
                     skills=())


# ── 기억 뽑기 write_memory() ─────────────────────────────────
# docs/specs/memory.md 쓰기 흐름 4: 메모장을 다시 쓰지 않고 줄 단위 명령만 받는다. 검사·적용은 services/account/memory.py.
# 입력은 가린 B/L, 이번 판정 한 줄, 사용자 문장(B/L은 [BL1]), 번호 있는 메모장. B/L 원본은 넘기지 않는다 (CLAUDE.md).


def write_memory(content: str, *, model: str | None = None, timeout: float | None = None) -> LLMAnswer:
    """기억 뽑기. output은 MemoryOpsOutput. content는 services/account/memory.writer_input이 만든 JSON 글자.

    모델은 MEMORY_MODEL(.env). 없으면 LLMError(not_configured)이고 부르는 쪽이 조용히 건너뛴다.
    판단 기준 Skill은 넣지 않는다. 메모장 종류·칸 규칙은 프롬프트에 있고 코드가 다시 검사한다.
    """
    model = model or os.environ.get("MEMORY_MODEL")
    if not model:
        raise LLMError("MEMORY_MODEL이 없습니다", kind="not_configured")
    return _ask_json(MEMORY_PROMPT, content, "memory_write", MEMORY_SCHEMA, MemoryOpsOutput, model, skills=(),
                     timeout=timeout)


# ── 대화 제목 make_chat_title() ─────────────────────────────
# 대화 목록의 제목. 첫 사용자 말을 코드가 B/L을 [BL1]로 가린 글만 받는다 (CLAUDE.md, B/L 원본은 LLM에 안 간다).
# 결과 검사(한 줄·길이·주입 모양)와 실패 시 대신 쓸 제목은 services/chat/conversations.py가 맡는다.


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
# docs/specs/chat-search.md. 검색 폼 대신 문장 하나를 받는다. LLM은 의도와 칸만 고르고 실행은 코드(services/chat/chat.py)가 한다.
# B/L은 코드가 [BL1]처럼 가린 뒤에만 넘어온다 (CLAUDE.md). Skill 문서는 넣지 않는다(판단 기준이 필요 없는 분류).


def route_chat(masked_message: str, bl_refs: list[str], has_current_cargo: bool, today: str, *,
               model: str | None = None) -> LLMAnswer:
    """가린 문장을 의도 하나와 칸으로 나눈다. output은 ChatRouteOutput. 칸 값은 services/chat/chat.py가 다시 검사한다."""
    data = {"message": masked_message, "bl_refs": bl_refs, "has_current_cargo": has_current_cargo, "today": today}
    return _ask_json(CHAT_ROUTE_PROMPT, json.dumps(data, ensure_ascii=False), "chat_route", CHAT_ROUTE_SCHEMA,
                     ChatRouteOutput, model, skills=())


# ── 채팅 에이전트 chat_agent() ──────────────────────────
# route_chat은 문장을 의도 하나로 나누고 끝났다. 그래서 네 의도에 안 맞는 실무 질문("포워더가 항차 번호를 안 줘")은
# 전부 고정 안내로 갔고, 한 문장에 조회 둘이 필요한 일("상하이에서 오는 배 중 제일 먼저 오는 배 지금 어디야")도 못 했다 (실측 대화).
# chat_agent는 LLM이 도구를 골라 부르고, 결과를 보고 다음 도구를 또 고른다 (_ask_json의 도구 루프, 상한 MAX_TOOL_ROUNDS).
# 도구 목록과 실행은 services/chat/chat.py가 준다: 화물 조회·화물 질문·입항 선박 검색 + 읽기 전용 MCP 도구.
# 등급·여유 일수는 지금처럼 코드가 정한다. B/L은 가린 토큰만 온다 (CLAUDE.md).
# Skill 문서를 통째로 넣는다: 도구가 필요 없는 실무 질문은 이 문서 안에서만 답하게 한다 (RAG 아님).

CHAT_AGENT_SKILLS = FOLLOW_UP_SKILLS  # 되묻기 설명법(cargo-verdict), 통관 단계, AIS, 부두, 수입 실무 기초(import-basics)를 모두 물을 수 있다


def chat_agent(masked_message: str, bl_refs: list[str], has_current_cargo: bool, today: str, history: list[dict],
               tools: list[dict], run_tool: Callable[[str, dict], dict], *, model: str | None = None,
               feedback: str | None = None, on_screen: dict | None = None, evidence: str | None = None) -> LLMAnswer:
    """가린 문장과 최근 대화를 받아 도구를 골라 쓰고 답 한 칸을 낸다. output은 ChatAgentOutput.

    on_screen: 화면에 지금 떠 있는 배들 {"vessel", "arrivals"}. services/chat/chat._masked_screen이 가리고 거른 자료다.
    자료일 뿐이다 (프롬프트 Trust boundary). 없으면 입력 JSON에 칸 자체를 넣지 않아 예전 입력과 같다.

    evidence: 이번 문장에서 앞서 부른 도구가 모은 근거 목록 글 (줄마다 [E1] 같은 id, services/chat/citations.evidence_prompt_block).
    도구 결과 안에도 같은 글이 evidence 칸으로 오지만, 다시 묻는 호출은 앞 도구 결과가 대화에 없어서 입력 자료로 다시 준다. 자료일 뿐이다. 없으면 칸 자체를 넣지 않는다.

    history: [{"role": "user"|"assistant", "text": 가린 글}]. 자료일 뿐이다 (프롬프트 Trust boundary).
    부른 도구와 결과는 LLMAnswer.tool_calls에 담긴다. 답 문장 검사는 services/chat/chat.py가 한다.
    feedback: 앞 답이 검사에 걸렸을 때 걸린 내용. 이때는 tools를 비워 부른다 (같은 도구를 두 번 실행하지 않게).
    """
    data = {"message": masked_message, "bl_refs": bl_refs, "history": history,
            "has_current_cargo": has_current_cargo, "today": today}
    if on_screen:
        data["on_screen"] = on_screen
    if evidence:
        data["evidence"] = evidence
    return _ask_json(CHAT_AGENT_PROMPT, json.dumps(data, ensure_ascii=False), "chat_agent", CHAT_AGENT_SCHEMA,
                     ChatAgentOutput, model, feedback=feedback, skills=CHAT_AGENT_SKILLS, tools=tools, run_tool=run_tool)


def match_ports(place: str, ports: list[str], *, model: str | None = None) -> LLMAnswer:
    """place에 있는 항구를 주어진 목록 안에서만 고른다 (pick_vessel처럼 고르기만). 목록 밖 이름은 코드가 버린다."""
    data = {"place": place, "ports": ports}
    return _ask_json(PORT_MATCH_PROMPT, json.dumps(data, ensure_ascii=False), "port_match", PORT_MATCH_SCHEMA,
                     PortMatchOutput, model, skills=())
