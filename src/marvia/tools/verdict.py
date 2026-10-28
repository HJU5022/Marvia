"""판정 네 칸(등급·단계·일정·확신) 중 등급·확신·일정 세 칸을 코드로 정한다 (설계 7.1).

하지 않는 일: 신호 계산(위치 끊김 등은 계획 3에서 선박 위치 조회와 함께 만든다),
단계 칸(UNI-PASS 단계 이름에서 정한다, 계획 3).
기준값과 신호 목록은 rules/verdict.yaml에서 읽는다.
v1의 D7(회색 지대에서 LLM이 등급을 올림)은 없앴다 (설계 결정 3).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel

from marvia.tools.rules import load_rules

# [왜] 코드 값은 영어로 두고 화면 이름은 표 하나에서만 바꾼다. 이름을 바꿔도 코드와 테스트는 그대로다
Grade = Literal["fine", "watch", "alert", "act"]
Confidence = Literal["sure", "partial", "unknown"]
Schedule = Literal["on_time", "concern", "delayed", "overdue"]

GRADE_LABEL: dict[Grade, str] = {"fine": "순항", "watch": "주의", "alert": "경계", "act": "긴급"}
CONFIDENCE_LABEL: dict[Confidence, str] = {"sure": "확실", "partial": "부분", "unknown": "불명"}
SCHEDULE_LABEL: dict[Schedule, str] = {
    "on_time": "정시",
    "concern": "우려",
    "delayed": "지연",
    "overdue": "초과",
}


class Signal(BaseModel):
    """신호 하나. triggered=켜짐, clear=꺼짐, unknown=판단 불가(데이터가 없어 모름)."""

    id: str
    state: Literal["triggered", "clear", "unknown"]
    value: str = ""  # 관측값. dest_changed면 바뀐 목적지 코드나 broken·empty


def _input_error(signal: Signal, rules: dict) -> bool:
    """배의 실제 상태가 아니라 AIS 입력 오류일 수 있는 신호인가."""
    # [왜] 항해 상태는 선원이 손으로 넣는 값이라 틀리기 쉽다. 실제 움직임은 속도·위치 신호가 따로 본다
    if signal.id in rules["input_error_signals"]:
        return True
    # [왜] 목적지 글자가 깨지거나 빈 것은 배가 다른 곳으로 가는 게 아니라 입력이 잘못된 것일 수 있다
    return signal.id == "dest_changed" and signal.value in rules["input_error_dest_values"]


def _on(signals: list[Signal], rules: dict) -> set[str]:
    """켜진 신호 이름. 입력 오류로 보이는 신호는 뺀다."""
    return {s.id for s in signals if s.state == "triggered" and not _input_error(s, rules)}


def grade(signals: list[Signal], margin_days: int | None) -> Grade:
    """등급. margin_days는 판매 예정일까지 남은 일수이고, 판매일을 모르면 None."""
    rules = load_rules("verdict")
    on = _on(signals, rules)
    # [주의] verdict.yaml 어느 목록에도 없는 신호는 켜져도 세지 않는다.
    #        신호 이름을 새로 만들면 yaml에도 넣는다
    margin_passed = margin_days is not None and margin_days < 0
    margin_short = margin_days is not None and margin_days < rules["margin_alert_days"]
    watch_count = len(on & set(rules["watch_signals"]))

    # [왜] 위험한 등급부터 본다. 하나라도 걸리면 그 등급으로 끝난다
    if on & set(rules["act_signals"]) or margin_passed:
        return "act"
    if on & set(rules["alert_signals"]) or margin_short or watch_count >= rules["watch_to_alert_count"]:
        return "alert"
    if watch_count:
        return "watch"
    # [왜] unknown은 켜진 것으로 세지 않는다. 모르는 것은 확신 칸이 따로 드러낸다
    return "fine"


def confidence(signals: list[Signal], identified: bool, has_source: bool) -> Confidence:
    """확신. identified=화물을 확정했나, has_source=위치나 통관 정보 중 하나라도 있나."""
    if not identified or not has_source:
        return "unknown"
    rules = load_rules("verdict")
    if any(s.state == "unknown" for s in signals):
        return "partial"
    # [왜] 입력 오류 신호는 등급을 올리지 않는 대신 "이 판단은 덜 믿을 만하다"는 표시로 쓴다
    if any(s.state == "triggered" and _input_error(s, rules) for s in signals):
        return "partial"
    return "sure"


def schedule(
    signals: list[Signal],
    margin_days: int | None,
    first_eta: datetime | None,
    trusted_eta: datetime | None,
) -> Schedule:
    """일정. first_eta=처음 알던 도착 예정, trusted_eta=지금 믿는 도착 예정."""
    rules = load_rules("verdict")
    if margin_days is not None and margin_days < 0:
        return "overdue"
    # [주의] 두 ETA를 모두 알 때만 지연을 판단한다. 하나라도 모르면 이 줄은 건너뛴다
    if first_eta and trusted_eta and trusted_eta - first_eta >= timedelta(days=rules["delay_days"]):
        return "delayed"
    if _on(signals, rules) & set(rules["schedule_concern_signals"]):
        return "concern"
    return "on_time"
