"""판정 묶음: 화물 사실·배 위치·입항 일정을 받아 판정 네 칸과 그 재료를 한 번에 낸다 (계획 8a, 설계 7.1).

하지 않는 일: 바깥 조회, 배 고르기, 답 글. 등급·확신·일정은 tools/verdict.py가, 신호는
tools/signals.py가 정한다.
여기는 그 둘을 잇고, 항만 값이나 조회 결과가 없을 때 "판정을 미루지 않고 확신을 낮추며 이유를 적는" 일만 한다.
[주의] 아직 그래프의 어느 노드도 이 함수를 부르지 않는다. 연결은 다음 계획이다
       (tests/test_vessel_base_not_wired.py).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from pydantic import BaseModel

from marvia.identify.models import CargoFacts
from marvia.tools.ports import port
from marvia.tools.rules import load_rules
from marvia.tools.signals import away_nm, compute, watches_ship
from marvia.tools.verdict import Confidence, Grade, Schedule, Signal, confidence, grade, schedule
from marvia.tools.vessel import (
    PortSchedule,
    Position,
    TrackPoint,
    as_utc,
    days_margin,
    trusted_eta,
    voyage_guard,
)


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
    cap: Confidence | None = None,
    cap_note: str | None = None,
) -> Verdict:
    """판정 네 칸. sale_due=판매 예정일, first_eta=처음 알던 도착 예정, forwarder_eta=포워더가 알려 준 날.

    cap="partial"이면 확신이 확실이어도 부분으로 낮추고 이유 cap_note를 더한다(배 확정이 호출부호를 맞추지
    못했을 때, tools/vessel_match.Match.cap). 확신이 이미 낮으면 그대로 두고 이유만 남긴다.
    """
    rules = load_rules("verdict")
    # [왜] 배 신호는 화물이 배에 실려 있는 동안에만 판정에 쓴다(11-13 판정). 내린 뒤에는 배가 다음 항구로
    #      떠나는 것이 정상이라, 그 배의 목적지·위치·ETA를 넣으면 멀쩡한 화물이 "경계"가 된다.
    #      통관 단계와 통관 멈춤만 본다. 누가 배 신호를 넘겨도 여기서 버린다
    if facts is not None and not watches_ship(facts.stage):
        signals = [
            s if s.id == "customs_hold" else Signal(id=s.id, state="clear", value="배에서 내린 화물")
            for s in compute(facts, None, None, now=now)
        ]
        return Verdict(
            grade=grade(signals, None),
            confidence=confidence(signals, identified=True, has_source=True),
            schedule=None,
            stage=facts.stage,
            signals=signals,
            trusted_eta=None,
            eta_source=None,
            margin_days=None,
            notes=[],
            info=["landed"],
        )
    # [왜] 11-15 판정. 해수부 신고는 이 화물의 항차 것만 쓴다(세관 입항일 앞뒤 며칠 안). 지난 항차의 입항
    #      예정이
    #      믿을 ETA로 들어오면 경계가 주의로 좋아진다. 세관 입항일이 없으면 어느 신고도 입항 시각으로 쓰지
    #      않는다
    row = port(facts.port_code) if facts and facts.port_code else None
    plan, voyage_notes = voyage_guard(
        plan, facts.entry_date if facts else None, row.voyage_window_days if row else None
    )
    signals = compute(facts, position, plan, now=now, history=history)
    eta, source = trusted_eta(position, plan, facts.port_code if facts else None, forwarder_eta, now=now)
    # [왜] 이 항차의 실제 입항(위의 가드를 지난 관제 실적이나 최종 신고)이 믿을 ETA의 출처면 그 배는 도착했다.
    #      그 뒤 다음 항구로 떠나거나 부두에 오래 서 있는 것은 이 화물의 위험이 아니다(11-13, 11-15 판정).
    #      배 신호(목적지, 항구 앞 정지, ETA 어긋남, 위치 끊김, 항해 상태)는 해당 없음(꺼짐)이고
    #      통관 단계와 통관 멈춤만 본다. 입항 전(실적 없음)의 신호는 그대로 켜진다
    arrived = source in rules["arrived_sources"]
    differs = False
    if arrived and position is not None:
        # [왜] 11-15, 11-16 판정(R-128, R-131). 입항 신고(실적, 최종)가 있어도 배 신호가 새것이고 목적지가
        #      이 항만인데 배가 항구에 서 있지 않으면 두 출처가 어긋난 것이다. ETA의 차이는 보지 않는다
        #      (가깝거나 이미 지났어도 같다). 입항으로 치지 않고 ETA 어긋남을 켜며 확신은 부분이다.
        #      배 신호가 오래됐거나 다른 항구행이면 이 검사는 하지 않는다
        state = {s.id: s.state for s in signals}
        # [왜] 배가 항만 기준점 반경 안에서 멈춰 있으면(실제로 항구에 있음) 배 신호 ETA를 고치지 않은 것일
        #      뿐이라 두 출처가 맞는 것으로 본다. 반경 안이어도 움직이면(속도가 stop_speed_kn 넘음) 항구에
        #      선 것이 아니다. 속도를 모르면 멈춘 것으로 보지 않는다. 항만 표에 기준점이 없어 거리를 볼 수
        #      없으면 어긋남으로 둔다(보수적)
        dist = away_nm(position.lat, position.lng, row)
        limit = rules["signals"]["stop_speed_kn"]
        docked = (
            dist is not None
            and row is not None
            and row.stop_radius_nm is not None
            and dist <= row.stop_radius_nm
            and position.sog is not None
            and position.sog <= limit
        )
        differs = state["position_stale"] == "clear" and state["dest_changed"] == "clear" and not docked
        if differs:
            arrived = False
            # [왜] 11-16 판정(R-129, E6). 어긋나면 믿을 ETA는 배 신호 ETA다. 신고가 있다고 신고가 없을 때보다
            #      여유가 늘면 안 된다. 그 ETA도 평소와 같이 이미 지났거나 없으면 출처가 아니고, 이른 쪽
            #      신고로 돌아가지 않고 믿을 ETA가 없다
            slack = timedelta(minutes=rules["clock_skew_minutes"])
            late = as_utc(position.ais_eta) if position.ais_eta is not None else None
            if late is not None and late >= as_utc(now) - slack:
                eta, source = late, "ais_eta"
            else:
                eta, source = None, None
            value = "입항 신고와 배 신호가 어긋남"
            signals = [
                Signal(id=s.id, state="triggered", value=value) if s.id == "eta_conflict" else s
                for s in signals
            ]
    if arrived:
        signals = [
            s if s.id == "customs_hold" else Signal(id=s.id, state="clear", value="이미 입항")
            for s in signals
        ]
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
    notes += voyage_notes
    # [왜] notes는 확신을 낮춘 이유다. 이 항차의 실제 입항이 확인됐으면 배 신호를 보지 않으므로 위치나 일정이
    #      없다는 사실이 확신을 낮추지 않는다(11-15 판정). 그 사실은 참고 글(arrived)로 알린다
    if differs:
        notes.append("arrival_report_differs")
    if position is None and not arrived:
        notes.append("no_position")
    if plan is None and not arrived:
        notes.append("no_schedule")
    sure = confidence(
        signals, identified=facts is not None, has_source=facts is not None or position is not None
    )
    # [왜] 항만 값을 확인하지 못했으면 신호가 모두 꺼져 보여도 "확실"이라고 하지 않는다
    if sure == "sure" and port_note:
        sure = "partial"
    if sure == "sure" and differs:
        sure = "partial"
    # [왜] 11-15 판정. 배 확정이 호출부호를 코드로 맞추지 못했으면(서류만, 사용자 선택만, 같은 호출부호의
    #      배가 여럿)
    #      확신이 부분을 넘지 못한다
    if cap == "partial":
        if sure == "sure":
            sure = "partial"
        if cap_note:
            notes.append(cap_note)
    # [왜] 세관 입항일이나 항만의 기간을 몰라 해수부 신고를 쓰지 못했으면 "확실"이라고 하지 않는다
    if sure == "sure" and ({"no_entry_date", "voyage_unchecked"} & set(voyage_notes)):
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
    # [왜] 처음 알던 도착 예정이 없으면 "지연"이 나올 수 없다. 그 상태에서 "정시"나 "우려"를 보이면
    #      견줘 본 것처럼 읽힌다(11-13 판정). 일정 칸은 견줄 처음 예정이 있을 때만 낸다.
    #      "초과"는 판매 예정일로 내므로 그대로 둔다. 켜진 신호는 등급 칸이 그대로 드러낸다
    if first_eta is None and cell != "overdue":
        cell = None
    info = ["no_sale_date"] if sale_due is None else []
    if first_eta is None:
        info.append("no_first_eta")
    if arrived:
        info.append("arrived")
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
        info=info,
    )
