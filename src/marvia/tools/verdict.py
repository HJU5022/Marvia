"""신호 → 등급(fine·watch·act) 판정 표 (설계 7.1).
v1 verdict.py의 표 부분만 옮겼고, 회색 지대에서 LLM이 등급을 올리던 D7은 없앴다 (설계 결정 3)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from marvia.tools.rules import load_rules

Grade = Literal["fine", "watch", "act"]
LABEL: dict[Grade, str] = {"fine": "순항", "watch": "주의", "act": "긴급"}


class Signal(BaseModel):
    """신호 하나. state가 triggered일 때만 켜진 것으로 센다. unknown은 켜진 것이 아니다."""

    id: str
    state: Literal["triggered", "clear", "unknown"]
    value: str = ""


def _ignored(signal: Signal, rules: dict) -> bool:
    """AIS 입력 오류일 수 있어 세지 않는 신호인가 (verdict.yaml ignore_*)."""
    if signal.id in rules["ignore_signals"]:
        return True
    return signal.id == "dest_changed" and signal.value in rules["ignore_dest_values"]


def table_verdict(signals: list[Signal], margin_days: int | None) -> Grade:
    """판정 표. margin_days는 판매 예정일까지 여유 일수이고, 모르면 None."""
    rules = load_rules("verdict")
    on = {s.id for s in signals if s.state == "triggered" and not _ignored(s, rules)}
    short = margin_days is not None and margin_days < rules["margin_act_days"]
    if not on:
        return "watch" if short else "fine"
    if on & set(rules["act_signals"]):
        return "act"
    return "act" if short else "watch"
