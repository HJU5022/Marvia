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


def scrub(value: Any) -> Any:
    """값 안의 모든 글에서 번호를 가린 새 값. dict·list·tuple·set·pydantic·dataclass·Send를 걸어 다닌다."""
    if isinstance(value, str):
        return scrub_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, dict):
        return {scrub(key): scrub(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [scrub(item) for item in value]
    if isinstance(value, Send):
        # [왜] Send 묶음(조회 갈래 하나)의 arg에 실제 번호와 가림 표가 통째로 든다 (R-039)
        return {"send": value.node, "arg": scrub(value.arg)}
    if isinstance(value, BaseModel):
        # [왜] 메시지·화물 결과(CargoIdentity)·Evidence는 pydantic이다. 칸을 하나씩 걸어 다닌다
        return scrub(dict(value))
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        # [주의] dataclasses.asdict는 값을 깊이 복사해 잠금 같은 객체에서 죽는다. 칸을 직접 읽는다
        return {field.name: scrub(getattr(value, field.name)) for field in dataclasses.fields(value)}
    # [주의] 모르는 객체(날짜, 예외, 도구 실행 정보 등)는 글로 바꿔 가린다. 원래 객체를 그대로 내보내지 않는다
    return scrub_text(str(value))
