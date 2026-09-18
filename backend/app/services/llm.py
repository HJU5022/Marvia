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

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
SLOT_PROMPT = "converge/slot-extract"

# 소형 모델이 없을 때 추출에 쓰는 모델. SDD 9절 MODEL_LARGE 와 같은 값을 본다
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


def _parse(raw: str) -> Slots:
    """모델 출력에서 JSON 을 꺼내 Slots 로 검증한다. 어긋나면 ValidationError 가 위로 올라간다."""
    body = raw.strip()
    if body.startswith("```"):  # ```json ... ``` 로 감싸 오는 모델이 있다
        body = body.split("```")[1]
        body = body[4:] if body.startswith("json") else body
    start, end = body.find("{"), body.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"JSON 을 찾지 못했습니다: {raw[:200]!r}")
    return Slots.model_validate(json.loads(body[start : end + 1]))


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
    model = model_large()
    filled = _fill(prompt, text, previous, preset)

    last_error: Exception | None = None
    for attempt in (1, 2):
        messages = [{"role": "user", "content": filled}]
        if attempt == 2 and last_error is not None:
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
        try:
            slots = _parse(raw)
        except (ValidationError, ValueError, json.JSONDecodeError) as e:
            last_error = e
            continue
        # 사용자가 프리셋을 골랐으면 그 값이 우선이다 (SDD 2절 AgentRequest.preset)
        if preset and not slots.out_of_scope and slots.preset != preset:
            slots = slots.model_copy(update={"preset": preset})
        # Result.model_small / prompt_version 은 6단계에서 함께 채운다. 그때 이 값을 쓰려면
        # 반환형을 (Slots, 모델, 프롬프트 버전) 으로 넓힌다 (SDD 4절)
        _last_meta.update({"model": model, "prompt_version": version, "attempts": attempt})
        return slots

    raise last_error if last_error else RuntimeError("슬롯 추출에 실패했습니다")
