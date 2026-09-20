"""LLM 호출은 이 파일 하나로 모은다. (SDD 5절 1단계, 8절 프롬프트)

라우터나 화면 코드가 openai 를 직접 import 하지 않게 한다. 3차에서 이 파일 내부만 갈아끼우면
나머지는 그대로 돌아간다.

여기서 책임지는 것:
  - 출력 계약 검증 (schemas/slots.py 의 Slots)
  - 실패 시 재시도와 대형 모델 승격 (SDD 5절 1단계 "실패 시")
  - Langfuse 트레이스와 프롬프트 (SDD 8절). 프롬프트를 코드에 문자열로 두지 않는다

소형 모델(GGUF)은 아직 없다 (backend/app/models/ 비어 있음, finetune/ 결과물 대기).
SDD 8절이 "소형 (GGUF) 또는 대형 폴백"을 허용하므로 그때까지는 대형 모델로 추출한다.
어느 모델로 돌았는지는 Result.model_small / routed_to 로 드러난다.
"""
from __future__ import annotations

import json
import os
from typing import Any

from pydantic import ValidationError

from backend.app.observability import langfuse
from backend.app.schemas.slots import Preset, Slots
from backend.app.services import costs as cost_guards

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
SLOT_PROMPT = "converge/slot-extract"

# SDD 9절 MODEL_LARGE 와 같은 값을 본다
DEFAULT_LARGE = "anthropic/claude-sonnet-5"


# 마지막 호출에 쓴 모델·프롬프트 버전. Result 를 만들 때(6·8단계) 쓴다
_last_meta: dict[str, Any] = {}


def last_meta() -> dict[str, Any]:
    return dict(_last_meta)


class LlmUnavailable(RuntimeError):
    """키가 없어 LLM 을 부를 수 없다. 파이프라인이 failed 로 답하게 한다."""


def _client() -> Any:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise LlmUnavailable("OPENROUTER_API_KEY 가 없습니다")
    from openai import AsyncOpenAI  # 지연 import: 키 없는 테스트가 이 파일을 건드리지 않게

    return AsyncOpenAI(api_key=key, base_url=OPENROUTER_BASE_URL)


def model_large() -> str:
    return os.environ.get("MODEL_LARGE", DEFAULT_LARGE)


def model_small() -> str | None:
    """소형 모델 id. 없으면 None.

    SDD 8절의 소형 모델은 로컬 GGUF(MODEL_SMALL_PATH)다. 그 서빙이 아직 붙지 않았으므로,
    OpenRouter 로 대신 돌려 볼 수 있게 MODEL_SMALL 도 본다. 둘 다 없으면 처음부터 대형으로 간다.
    GGUF 서빙이 들어오면 이 함수만 "로컬 모델 핸들"을 돌려주게 바꾼다.
    """
    return os.environ.get("MODEL_SMALL") or None


def attempt_models() -> list[str]:
    """시도 순서 (SDD 5절 1단계 "스키마 위반 시 재시도 1회 → 대형 모델 승격").

      소형이 있으면  [소형, 소형, 대형]   같은 모델로 한 번 더 → 그래도 어기면 대형으로 승격
      소형이 없으면  [대형, 대형]        승격할 곳이 없으니 재시도까지만
    """
    small = model_small()
    large = model_large()
    if small and small != large:
        return [small, small, large]
    return [large, large]


def _fill(prompt: str, text: str, previous: Slots | None, preset: Preset | None) -> str:
    """Langfuse 프롬프트의 {{변수}} 를 채운다.

    Langfuse 의 compile 을 쓰지 않고 직접 채우는 이유: 변수 세 개뿐이고, 값이 비었을 때
    "없음"으로 적어 모델이 빈 자리를 지어내지 않게 하려는 것이다.
    """
    return (
        prompt.replace("{{previous_slots}}", previous.model_dump_json() if previous else "없음")
        .replace("{{preset_hint}}", preset or "없음")
        .replace("{{text}}", text)
    )


def _parse_json_block(raw: str) -> dict[str, Any]:
    """모델 출력에서 JSON 객체를 꺼낸다. judge.py 도 같은 파서를 쓴다."""
    body = raw.strip()
    if body.startswith("```"):  # ```json ... ``` 로 감싸 오는 모델이 있다
        body = body.split("```")[1]
        body = body[4:] if body.startswith("json") else body
    start, end = body.find("{"), body.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"JSON 을 찾지 못했습니다: {raw[:200]!r}")
    return json.loads(body[start : end + 1])


# 1인칭을 부르는 말. 모델이 문장 그대로 "저", "제가" 로 뽑아 오면 화면과 결과 표에 그대로 나온다.
# 사람 이름 자리라 한 가지로 맞춘다. 프롬프트에도 "나" 로 두라고 적었지만 모델이 자주 어긴다.
_FIRST_PERSON = {"저", "제", "제가", "저는", "나는", "본인", "me", "I"}
FIRST_PERSON_NAME = "나"


def normalize_names(slots: Slots) -> Slots:
    """1인칭 표기를 "나" 하나로 맞춘다. pickup 이 그 사람을 가리키면 그것도 같이 바꾼다."""
    renamed = {p.name: FIRST_PERSON_NAME for p in slots.participants if p.name.strip() in _FIRST_PERSON}
    if not renamed:
        return slots
    participants = [
        p.model_copy(
            update={
                "name": renamed.get(p.name, p.name),
                "pickup": renamed.get(p.pickup, p.pickup) if p.pickup else p.pickup,
            }
        )
        for p in slots.participants
    ]
    return slots.model_copy(update={"participants": participants})


def _parse(raw: str) -> Slots:
    """모델 출력을 Slots 로 검증한다. 어긋나면 ValidationError 가 위로 올라간다."""
    return Slots.model_validate(_parse_json_block(raw))


async def extract_slots(
    text: str,
    previous: Slots | None = None,
    preset: Preset | None = None,
) -> Slots:
    """문장 → Slots. 스키마를 어기면 한 번 더 시도한다 (SDD 5절 1단계).

    재시도 때는 무엇이 틀렸는지 모델에 붙여 준다. 그래도 어기면 예외를 올리고, 파이프라인이 failed 로 답한다.
    """
    prompt, version = langfuse.get_prompt(SLOT_PROMPT)
    client = _client()
    filled = _fill(prompt, text, previous, preset)
    models = attempt_models()

    last_error: Exception | None = None
    for attempt, model in enumerate(models, start=1):
        messages = [{"role": "user", "content": filled}]
        if attempt > 1 and last_error is not None:
            messages.append(
                {
                    "role": "user",
                    "content": f"방금 출력이 형식을 어겼습니다: {last_error}. 형식을 지켜 JSON 만 다시 출력하세요.",
                }
            )
        res = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0,
            response_format={"type": "json_object"},
            extra_body={"usage": {"include": True}},
        )
        raw = res.choices[0].message.content or ""
        usage = getattr(res, "usage", None)
        tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0)
        tokens_out = int(getattr(usage, "completion_tokens", 0) or 0)
        try:
            slots = _parse(raw)
        except (ValidationError, ValueError, json.JSONDecodeError) as e:
            last_error = e
            continue
        slots = normalize_names(slots)
        # 사용자가 프리셋을 골랐으면 그 값이 우선이다 (SDD 2절 AgentRequest.preset)
        if preset and not slots.out_of_scope and slots.preset != preset:
            slots = slots.model_copy(update={"preset": preset})
        # Result.model_small / prompt_version 은 6단계에서 함께 채운다. 그때 이 값을 쓰려면
        # 반환형을 (Slots, 모델, 프롬프트 버전) 으로 넓힌다 (SDD 4절)
        _last_meta.update(
            {
                "model": model,
                "prompt_version": version,
                "attempts": attempt,
                "escalated": model == model_large() and attempt > 1 and models[0] != model_large(),
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cost_usd": cost_guards.estimate_cost_usd(model, tokens_in, tokens_out),
            }
        )
        return slots

    raise last_error if last_error else RuntimeError("슬롯 추출에 실패했습니다")
