"""판정 묶음: 화물 사실·배 위치·입항 일정을 받아 판정 네 칸과 그 재료를 한 번에 낸다 (계획 8a, 설계 7.1).

하지 않는 일: 바깥 조회, 배 고르기, 답 글. 등급·확신·일정은 tools/verdict.py가, 신호는
tools/signals.py가 정한다.
여기는 그 둘을 잇고, 항만 값이나 조회 결과가 없을 때 "판정을 미루지 않고 확신을 낮추며 이유를 적는" 일만 한다.
[주의] 아직 그래프의 어느 노드도 이 함수를 부르지 않는다. 연결은 다음 계획이다
       (tests/test_vessel_base_not_wired.py).
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel

from marvia.identify.models import CargoFacts
from marvia.tools.ports import port
from marvia.tools.rules import load_rules
from marvia.tools.signals import compute
from marvia.tools.verdict import Confidence, Grade, Schedule, Signal, confidence, grade, schedule
from marvia.tools.vessel import PortSchedule, Position, TrackPoint, days_margin, trusted_eta


class Verdict(BaseModel):
    """판정 한 건. 숫자와 등급은 모두 코드가 냈다. notes는 rules/verdict.yaml notes의 이름이다."""

    # [주의] 등급과 일정은 None일 수 있다: 도착 시각을 알 출처가 하나도 없고 켜진 신호도 없으면
    #        "순항", "정시"라고 하지 않는다. 자료가 모자랄수록 등급이 좋아지면 안 된다
    grade: Grade | None
    confidence: Confidence
    schedule: Schedule | None
    stage: str | None  # 단계 칸: UNI-PASS 단계 이름
    signals: list[Signal]
    trusted_eta: datetime | None
    eta_source: str | None  # rules/verdict.yaml eta_priority의 이름
    margin_days: int | None
    notes: list[str]  # 확신을 낮춘 이유
    info: list[str] = []  # 확신을 낮추지 않는 참고 사실. rules/verdict.yaml info의 이름이다


def _port_note(facts: CargoFacts | None) -> str | None:
    if facts is None:
        return None
    if not facts.port_code:
        return "port_unknown"
    row = port(facts.port_code)
    if row is None:
        return "port_not_in_table"
    return None if row.verified else "port_unverified"


def judge(
    facts: CargoFacts | None,
    position: Position | None,
    plan: PortSchedule | None,
    *,
    now: datetime,
    sale_due: date | None = None,
    first_eta: datetime | None = None,
    forwarder_eta: date | None = None,
    history: list[TrackPoint] | None = None,
) -> Verdict:
    """판정 네 칸. sale_due=판매 예정일, first_eta=처음 알던 도착 예정, forwarder_eta=포워더가 알려 준 날."""
    rules = load_rules("verdict")
    signals = compute(facts, position, plan, now=now, history=history)
    eta, source = trusted_eta(position, plan, facts.port_code if facts else None, forwarder_eta)
    # [왜] 해수부의 입항 실적과 입항 예정은 배 위치와 무관한 신고다. 위치가 없어도 그 시각으로 센다.
    #      배 신호의 ETA나 포워더가 알려 준 날뿐인데 위치가 없으면 세지 않는다(그 값을 뒷받침할 것이 없다).
    #      v1은 위치가 없으면 늘 세지 않았다. 그때는 판정 자체를 하지 않고 되물었다
    margin = (
        days_margin(eta, sale_due)
        if position is not None or source in rules["margin_without_position"]
        else None
    )
    port_note = _port_note(facts)
    notes = [port_note] if port_note else []
    if position is None:
        notes.append("no_position")
    if plan is None:
        notes.append("no_schedule")
    sure = confidence(
        signals, identified=facts is not None, has_source=facts is not None or position is not None
    )
    # [왜] 항만 값을 확인하지 못했으면 신호가 모두 꺼져 보여도 "확실"이라고 하지 않는다
    if sure == "sure" and port_note:
        sure = "partial"
    level: Grade | None = grade(signals, margin)
    cell: Schedule | None = schedule(signals, margin, first_eta, eta)
    # [왜] 자료가 모자랄수록 등급이 좋아지면 안 된다. 도착 시각을 알 출처가 없거나, 판매 예정일을 받았는데
    #      여유 일수를 세지 못했으면(위치가 없고 포워더가 알려 준 날뿐일 때) "순항"과 "정시"는 근거가 없다.
    #      그 칸을 비우고 확신은 불명이다. 켜진 신호가 올린 등급(주의·경계·긴급)과 "우려"는 그대로 낸다:
    #      통관 보류를 가리면 안 된다. 판매 예정일을 받지 않았으면 견줄 날이 없으니 신호만으로 낸 등급을 둔다
    uncounted = sale_due is not None and margin is None
    if eta is None:
        notes.append("no_eta")
    elif uncounted:
        notes.append("no_margin")
    if eta is None or uncounted:
        if level == "fine":
            level, sure = None, "unknown"
        if cell == "on_time":
            cell = None
    return Verdict(
        grade=level,
        confidence=sure,
        schedule=cell,
        stage=facts.stage if facts else None,
        signals=signals,
        trusted_eta=eta,
        eta_source=source,
        margin_days=margin,
        notes=notes,
        info=["no_sale_date"] if sale_due is None else [],
    )
