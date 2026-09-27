"""LLM 호출은 이 파일 하나로 모읍니다 (작업 C-6, SDD 1.1).

라우터나 UI 코드가 openai를 직접 import하지 않게 하세요.
3차에서 이 파일 내부만 갈아끼우면 나머지는 그대로 돌아갑니다.

여기서 책임지는 것:
  - 출력 계약 검증 (Pydantic)          ← TODO
  - 실패 시 재시도와 폴백, 라우팅       ← 재시도 1회만 있음. 폴백·라우팅·요청당 시간 예산은 TODO (09-23 결정)
  - Langfuse 트레이스 남기기            ← TODO (D3)

지금 있는 것: chat() 하나. OpenRouter에 묻고, 과부하·한도(503·429)면 한 번 더 묻는다.

모델 자리 (.env, 계약 C8):
  MODEL_A     싼 모델. 대화+판단 기본
  MODEL_B     강한 모델. 어려운 건 + 비전
  JUDGE_MODEL 평가 때만. A·B와 다른 회사
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field

import openai
from openai import OpenAI

# OpenRouter는 OpenAI와 같은 요청 형식을 받는다. 그래서 openai SDK에 주소만 바꿔 쓴다 (requirements.txt 주석).
BASE_URL = "https://openrouter.ai/api/v1"
TIMEOUT_SEC = 60.0  # 호출 하나가 요청 전체 시간을 다 먹지 않게 하는 상한. p95 실측 뒤 조정

# 재시도는 횟수가 아니라 요청당 시간 예산으로 정하기로 했다 (09-23 결정). 예산 숫자가 정해지기 전까지는
# 최초 1회 + 재시도 1회만 한다. 3회씩 돌리면 사용자가 너무 오래 기다린다.
MAX_ATTEMPTS = 2
RETRY_WAIT_SEC = 2.0  # 과부하는 잠깐 뒤 풀리는 경우가 많다. 실측 전 임시값
# 다시 불러 볼 만한 것: 한도 초과(429), 제공사 과부하·게이트웨이(502·503).
# 09-23 스모크 테스트에서 nemotron 무료가 503 provider_overloaded를 5번 중 3번 냈다.
# 타임아웃은 넣지 않는다. 60초를 한 번 더 기다리면 시간 예산을 넘는다.
RETRYABLE_CODES = {429, 502, 503}

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


class LLMError(Exception):
    """OpenRouter가 답 대신 에러를 준 경우. code가 RETRYABLE_CODES면 chat()이 한 번 더 부른다."""

    def __init__(self, message: str, code: int | None = None, latency_ms: int = 0):
        super().__init__(message)
        self.code = code
        self.latency_ms = latency_ms

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE_CODES


def _client() -> OpenAI:
    # 키는 호출할 때 읽는다. import 시점에 .env가 아직 안 읽혔을 수 있어서 (clients/*.py와 같은 방식).
    # max_retries=0: openai SDK는 기본으로 몰래 2번 재시도한다. 재시도는 아래 chat()이 한 곳에서만 한다.
    return OpenAI(base_url=BASE_URL, api_key=os.environ["OPENROUTER_API_KEY"], timeout=TIMEOUT_SEC, max_retries=0)


def _call_once(kwargs: dict) -> LLMResult:
    """OpenRouter를 딱 한 번 부른다. 실패는 전부 LLMError로 바꿔서 올린다."""
    model = kwargs["model"]
    # require_parameters: 요청에 쓴 기능(구조화 출력, tool)을 지원하는 제공사로만 보낸다.
    # OpenRouter의 모델 단위 "지원" 표시는 제공사 합계라, 이게 없으면 미지원 제공사로 조용히 넘어갈 수 있다 (09-23 조사).
    extra_body = {"provider": {"require_parameters": True}}

    start = time.monotonic()
    try:
        resp = _client().chat.completions.create(**kwargs, extra_body=extra_body)
    except openai.APIStatusError as e:  # HTTP 4xx·5xx로 온 실패
        raise LLMError(f"{model}: HTTP {e.status_code} {e.message}", code=e.status_code,
                       latency_ms=int((time.monotonic() - start) * 1000)) from e
    latency_ms = int((time.monotonic() - start) * 1000)

    # OpenRouter는 제공사가 실패하면 HTTP 200 안에 choices 없이 error만 담아 보낼 때가 있다 (09-23 스모크 테스트).
    # 그대로 두면 choices[0]에서 TypeError가 나서 원인이 가려지므로, 에러 내용과 코드를 그대로 올린다.
    if not resp.choices:
        error = (resp.model_extra or {}).get("error") or {}
        raise LLMError(f"{model}: 응답에 choices 없음, error={error}", code=error.get("code"), latency_ms=latency_ms)

    msg = resp.choices[0].message
    calls = [{"name": c.function.name, "arguments": c.function.arguments} for c in (msg.tool_calls or [])]
    usage = resp.usage
    return LLMResult(
        content=msg.content,
        tool_calls=calls,
        model=resp.model,
        provider=getattr(resp, "provider", None),  # OpenRouter 전용 필드라 SDK 타입에는 없다
        request_id=resp.id,
        prompt_tokens=usage.prompt_tokens if usage else None,
        completion_tokens=usage.completion_tokens if usage else None,
        latency_ms=latency_ms,
    )


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
        model: 생략하면 MODEL_A
        response_format: 구조화 출력. {"type": "json_schema", "json_schema": {...}}
        tools: tool 정의 목록 (OpenAI 형식)
        max_tokens: 출력 상한

    Raises:
        LLMError: 재시도해도 안 되거나, 다시 불러도 소용없는 실패(400·401 등)
    """
    kwargs: dict = {"model": model or os.environ["MODEL_A"], "messages": messages}
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
