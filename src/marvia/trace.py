"""트레이스(콜백·Langfuse)로 나가는 값에서 화물 번호를 가린다 (설계 12절, done 3.9 문: R-010·R-022·R-039).

하지 않는 일: 트레이서 연결. Langfuse 키가 없어 연결은 미뤘다. scrub은 Langfuse 클라이언트의 mask= 훅 모양
(값 하나를 받아 가린 값을 돌려준다)이라 연결할 때 그대로 끼운다.
[왜] 상태 없이 글 모양으로 찾는다. 콜백에는 그 대화의 가림 표가 오지 않고, 번호는 노드 입력·출력,
     도구 결과, Send 묶음, 도구 안에서 부른 서브그래프, 답 어디에든 들 수 있다.
[주의] 번호처럼 생긴 다른 글(8자 이상 영문·숫자 덩어리)도 함께 가린다. 트레이스에서는 덜 가리는 것보다 낫다.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from langgraph.types import Send
from pydantic import BaseModel

from marvia.identify.parse import find_spans

MASK = "[가림]"


def scrub_text(text: str) -> str:
    """글 속 번호 후보 덩어리(identify.parse.find_spans와 같은 규칙)를 모두 MASK로 바꾼다."""
    pieces: list[str] = []
    last = 0
    for span in find_spans(text):
        pieces += [text[last : span.start], MASK]
        last = span.end
    return "".join(pieces) + text[last:]


def scrub(data: Any, **_: Any) -> Any:
    """값 안의 모든 글에서 번호를 가린 새 값. dict·list·tuple·set·pydantic·dataclass·Send를 걸어 다닌다.

    [왜] 인자 이름이 data이고 나머지 키워드는 받아 버린다. Langfuse 클라이언트가 mask(data=...)로 부른다.
    """
    return _walk(data, set())


def _key(key: Any, taken: dict) -> Any:
    """dict 키를 가린다. 글이 아닌 키는 글로 바꿔 가리고, 가린 뒤 겹치는 키는 번호를 붙여 값을 잃지 않는다."""
    if isinstance(key, (int, float, bool)) or key is None:
        return key
    masked = _text_of(key)
    unique, n = masked, 1
    while unique in taken:
        n += 1
        unique = f"{masked}#{n}"
    return unique


def _text_of(value: Any) -> str:
    """str()이 죽는 객체는 통째로 MASK."""
    try:
        return scrub_text(str(value))
    except Exception:  # noqa: BLE001  [왜] 가리는 길이 값 하나 때문에 죽으면 트레이스 칸 전체가 빈다
        return MASK


def _walk(value: Any, active: set[int]) -> Any:
    if isinstance(value, str):
        return scrub_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    # [왜] 자기 자신을 품은 값은 걷던 길 위에 다시 나오면 MASK로 끊는다 (같은 값이 두 곳에 있는 것은 괜찮다)
    if id(value) in active:
        return MASK
    active = active | {id(value)}
    if isinstance(value, dict):
        out: dict = {}
        for key, item in value.items():
            out[_key(key, out)] = _walk(item, active)
        return out
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_walk(item, active) for item in value]
    if isinstance(value, Send):
        # [왜] Send 묶음(조회 갈래 하나)의 arg에 실제 번호와 가림 표가 통째로 든다 (R-039)
        return {"send": value.node, "arg": _walk(value.arg, active)}
    if isinstance(value, BaseModel):
        # [왜] 메시지·화물 결과(CargoIdentity)·Evidence는 pydantic이다. 칸을 하나씩 걸어 다닌다
        return _walk(dict(value), active)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        # [주의] dataclasses.asdict는 값을 깊이 복사해 잠금 같은 객체에서 죽는다. 칸을 직접 읽는다
        return {field.name: _walk(getattr(value, field.name), active) for field in dataclasses.fields(value)}
    # [주의] 모르는 객체(날짜, 예외, 도구 실행 정보 등)는 글로 바꿔 가린다. 원래 객체를 그대로 내보내지 않는다
    return _text_of(value)
