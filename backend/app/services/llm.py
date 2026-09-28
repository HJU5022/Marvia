"""LLM 호출은 이 파일 하나로 모읍니다 (작업 C-6, SDD 1.1).

라우터나 UI 코드가 openai를 직접 import하지 않게 하세요.
3차에서 이 파일 내부만 갈아끼우면 나머지는 그대로 돌아갑니다.

여기서 책임지는 것:
  - 출력 형식 검사 (Pydantic)          ← judge()가 JSON 모양만 본다. 내용 7규칙은 C-7 validate.py
  - 실패 시 재시도와 폴백, 라우팅       ← 재시도 1회만 있음. 폴백·라우팅·요청당 시간 예산은 TODO (09-23 결정)
  - Langfuse 트레이스 남기기            ← _ask_json()이 호출마다 generation 하나 (observability/langfuse.py, SDD 5.11)

지금 있는 것:
  chat()   OpenRouter에 한 번 묻는다. 과부하·한도(503·429)면 한 번 더 묻는다
  judge()            2층 판정. 프롬프트(Langfuse) + skills/ 문서 + 코드가 모은 자료를 주고 판정 JSON을 받는다 (SDD 4.1 7단계, 5.6)
  pick_vessel()      이름 같은 후보가 여럿일 때 어느 배인지 고른다 (SDD 5.5, C-5)
  answer_follow_up() 판정 뒤 후속 질문에 근거 안에서만 답한다 (C-9)

모델 자리 (.env, 계약 C8):
  MODEL_A     싼 모델. 대화+판단 기본
  MODEL_B     강한 모델. 어려운 건 + 비전
  JUDGE_MODEL 평가 때만. A·B와 다른 회사
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

import openai
from openai import OpenAI
from pydantic import BaseModel, ValidationError

from backend.app.observability.langfuse import end_generation, get_prompt, start_generation
from backend.app.schemas.agent import AgentResponse, Conflict, Reason, VesselCandidate, Verdict
from backend.app.schemas.customs import CustomsRecord
from backend.app.schemas.signals import SignalSet

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
    cost: float | None = None           # OpenRouter가 응답 usage.cost에 준 실제 금액 (크레딧 = USD). 무료 모델은 0


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
    # 키가 없으면 KeyError로 서버가 500을 내는 대신 LLMError로 올린다. 라우터가 판정 없이 partial로 돌려준다 (09-23 결정)
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise LLMError("OPENROUTER_API_KEY가 없습니다")
    return OpenAI(base_url=BASE_URL, api_key=key, timeout=TIMEOUT_SEC, max_retries=0)


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
    except openai.APIConnectionError as e:  # 연결 실패·타임아웃. 다시 부르지 않는다 (위 RETRYABLE_CODES 주석)
        raise LLMError(f"{model}: 연결 실패 {type(e).__name__}",
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
        # OpenRouter 전용 필드라 SDK 타입에는 없다. 요청 옵션 없이 매 응답에 들어온다 (OpenRouter Usage Accounting 문서, 09-28 확인)
        cost=getattr(usage, "cost", None) if usage else None,
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
    model = model or os.environ.get("MODEL_A")
    if not model:
        raise LLMError("MODEL_A가 없습니다")
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
    "required": ["verdict", "reasons", "conflicts", "actions", "answer", "customs"],  # strict 모드는 모든 칸이 required
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
                    "chosen": {"type": "string", "description": "믿은 출처"},
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


@dataclass
class LLMAnswer:
    """judge()·pick_vessel()·answer_follow_up()의 결과. 검사를 통과한 출력과 함께
    트레이스에 남길 값(모델·토큰·지연·프롬프트 버전)을 들고 다닌다 (SDD 5.11)."""

    output: BaseModel  # 함수마다 JudgeOutput·PickOutput·FollowUpOutput
    llm: LLMResult
    prompt_version: str


def _skills_text() -> str:
    """skills/ 아래 .md 전부를 파일 이름과 함께 이어 붙인다. RAG 없이 통째로 넣는다 (CLAUDE.md)."""
    parts = []
    for path in sorted(SKILL_DIR.rglob("*.md")):
        # Windows 문제: relative_to()를 그대로 문자열로 쓰면 Windows에서 "ais-reliability\SKILL.md"처럼 역슬래시가 된다.
        # 그러면 LLM이 보는 파일 이름이 OS마다 달라지고 test_judge.py::test_system_has_prompt_and_all_skills가 Windows에서만 깨진다.
        # as_posix()로 어느 OS에서든 "/"로 맞춘다 (Docker·Mac은 원래 "/"라 동작 변화 없음)
        parts.append(f"# 파일: skills/{path.relative_to(SKILL_DIR).as_posix()}\n\n{path.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)


def _judge_input(signals: SignalSet, customs: CustomsRecord | None, days_margin: int | None) -> str:
    """LLM에 넘길 자료를 JSON 문자열로 만든다. B/L 번호(bl_masked)와 MRN은 판정에 필요 없어 뺀다 (CLAUDE.md, SDD 3.5)."""
    data = {
        "signals": [s.model_dump() for s in signals.signals],
        "freshness": signals.freshness,
        "distance_nm": signals.distance_nm,
        "calc_eta": signals.calc_eta.isoformat() if signals.calc_eta else None,
        "days_margin": days_margin,
        "customs": customs.model_dump(mode="json", exclude={"bl_masked", "mrn", "fetched_at"}) if customs else None,
    }
    return json.dumps(data, ensure_ascii=False)


def _ask_json(prompt_name: str, user_content: str, schema_name: str, schema: dict,
              output_model: type[BaseModel], model: str | None, feedback: str | None = None) -> LLMAnswer:
    """세 함수가 같이 쓰는 한 번의 문답. 지시문(Langfuse) + skills 문서를 system에, 자료를 user에 넣고
    구조화 출력으로 받은 JSON을 output_model로 검사한다.

    Raises:
        LLMError: 호출 실패, 또는 답이 JSON이 아니거나 모양이 output_model과 다를 때.
                  내용 규칙(V1~V7) 검사와 재시도는 C-7 validate.py가 맡는다.
    """
    prompt = get_prompt(prompt_name)
    messages = [
        {"role": "system", "content": f"{prompt.text}\n\n{_skills_text()}"},
        {"role": "user", "content": user_content},
    ]
    if feedback:
        # 검증 위반을 붙여 다시 묻는 경우 (C-7). 코드가 쓴 지시라 자료(user_content)와 섞지 않고 따로 보낸다
        messages.append({"role": "user", "content": f"Your previous answer broke these rules. Answer again in the same JSON format and fix them:\n{feedback}"})
    # 트레이스 입력은 코드가 모은 자료(user_content)만. 지시문·skills 전문은 길고 매번 같아서 빼고 prompt_version으로 가린다
    generation = start_generation(prompt_name, user_content)
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
        error = LLMError(f"{result.model}: {schema_name} JSON 모양이 다름 ({e.error_count()}건)")
        end_generation(generation, result, prompt.version, output=result.content, error=str(error))
        raise error from e
    end_generation(generation, result, prompt.version, output=output.model_dump(mode="json"))
    return LLMAnswer(output=output, llm=result, prompt_version=prompt.version)


def judge(
    signals: SignalSet,
    customs: CustomsRecord | None,
    days_margin: int | None,
    *,
    model: str | None = None,
    feedback: str | None = None,
) -> LLMAnswer:
    """2층 판정. output은 JudgeOutput. 자료는 코드가 모은 신호·통관·여유 일수 (SDD 4.1 7단계).
    feedback은 출력 검증(C-7) 위반 내용이다. 주면 위반을 고쳐 다시 답하라고 붙인다 (SDD 5.7 재시도)."""
    return _ask_json(JUDGE_PROMPT, _judge_input(signals, customs, days_margin), "judge", JUDGE_SCHEMA, JudgeOutput, model,
                     feedback=feedback)


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
    answer = _ask_json(PICK_PROMPT, json.dumps(data, ensure_ascii=False), "pick_vessel", PICK_SCHEMA, PickOutput, model)
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


def answer_follow_up(question: str, response: AgentResponse, *, model: str | None = None) -> LLMAnswer:
    """이미 나온 판정(response)에 대한 후속 질문에 답한다. output은 FollowUpOutput.

    질문은 사용자 자유 입력이라 데이터로만 넘긴다 (SDD 7절 신뢰 경계). 300자 제한은 AgentRequest가 이미 건다.
    """
    data = {
        "result": response.model_dump(mode="json", exclude={"trace_id", "vessel_candidates"}),
        "question": question,
    }
    return _ask_json(FOLLOW_UP_PROMPT, json.dumps(data, ensure_ascii=False), "follow_up",
                     FOLLOW_UP_SCHEMA, FollowUpOutput, model)
