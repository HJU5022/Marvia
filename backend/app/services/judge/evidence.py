"""근거 조립과 여유 일수 계산 (작업 C-8, SDD 5.8).

두 가지를 한다.
- days_margin(): 판매 예정일까지 며칠 남았나를 코드가 계산한다.
  LLM이 다른 값을 내도 이 값으로 덮어쓴다 (CLAUDE.md "days_margin을 LLM이 정하게 두지 않는다").
- build(): 도구 응답마다 근거 카드(Evidence)를 만든다 (SDD 5.8 "도구 응답마다 Evidence 1건 이상").
  판정에 쓴 숫자·날짜는 모두 여기 있어야 한다. 출력 검증 V3·V6·V7이 이 목록과 대조한다 (SDD 5.7).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from backend.app.schemas.agent import Evidence
from backend.app.schemas.customs import CustomsRecord
from backend.app.schemas.signals import SignalSet

KST = timezone(timedelta(hours=9))  # 판매 예정일은 한국 날짜로 받으므로 ETA도 한국 날짜로 바꿔 센다 (SDD 5.8)


def days_margin(trusted_eta: datetime | None, sale_due_date: date | None) -> int | None:
    """판매 예정일 - 신뢰 ETA의 한국 날짜. 음수면 판매 예정일을 넘긴다.

    시간은 무시하고 날짜만 센다. 창고 입고·배송에 걸리는 시간은 넣지 않는다 (SDD 5.8).
    둘 중 하나라도 없으면 None. 판정은 이 값이 없음을 알고 한다.
    """
    if trusted_eta is None or sale_due_date is None:
        return None
    if trusted_eta.tzinfo is None:
        trusted_eta = trusted_eta.replace(tzinfo=timezone.utc)
    return (sale_due_date - trusted_eta.astimezone(KST).date()).days


def build(customs: CustomsRecord | None, position: dict | None, schedule: dict | None, distance: dict | None,
          trusted: datetime | None, margin: int | None, now: datetime | None = None,
          signals: SignalSet | None = None, sale_due_date: date | None = None,
          forwarder_eta: date | None = None) -> list[Evidence]:
    """도구 응답과 코드 계산값을 근거 카드 목록으로 만든다.

    값이 없거나 도구가 실패한 곳은 카드를 만들지 않는다. 없는 값을 근거로 쓰지 못하게 하려는 것이다.
    시각은 한국 시각 "YYYY-MM-DD HH:MM"으로 적는다. 화면과 answer가 한국 시각으로 말하기 때문이다.
    """
    now = now or datetime.now(timezone.utc)
    cards: list[Evidence] = []

    def add(source: str, field: str, value, fetched_at) -> None:
        if value is None or value == "":
            return
        cards.append(Evidence(source=source, field=field, value=_text(value), fetched_at=fetched_at))

    if customs is not None:
        entry = customs.entry_date.date().isoformat() if customs.entry_date else None  # UNI-PASS 입항일은 날짜만 온다
        for field, value in (("ship_name", customs.ship_name), ("stage_name", customs.stage_name),
                             ("entry_date", entry), ("shed_name", customs.shed_name)):
            add("unipass", field, value, customs.fetched_at)
        # 통관 이력. UNI-PASS 처리일시는 시간대 없이 한국 시각으로 온다 (services/judge/customs.py _dt)
        for stage in customs.stage_history:
            if stage.at:
                add("unipass", f"stage:{stage.name}", stage.at.strftime("%Y-%m-%d %H:%M") if stage.at.tzinfo is None else stage.at,
                    customs.fetched_at)

    if _ok(position):
        at = position["fetched_at"]
        add("shipfinder", "position", f"{position['lat']}, {position['lng']}", at)
        for field in ("sog", "navistat", "dest", "ais_eta", "last_time"):
            add("shipfinder", field, position.get(field), at)

    if _ok(schedule):
        for field in ("planned_arrival", "actual_arrival", "facility"):
            add("mof", field, schedule.get(field), schedule["fetched_at"])

    if _ok(distance):
        for field in ("distance_nm", "calc_hours_at_sog"):
            add("searoute", field, distance.get(field), distance["fetched_at"])

    # 코드가 계산한 값도 근거다. 판정과 answer가 이 값을 인용한다 (SDD 5.8)
    # 신호 값은 LLM이 보고 답하는 자료라 V7 대조에 필요하다. unknown은 값이 없다는 뜻이라 뺀다
    for signal in (signals.signals if signals else []):
        if signal.state != "unknown":
            add("rule", signal.id, signal.value, signals.computed_at)
    add("rule", "trusted_eta", trusted, now)
    add("rule", "days_margin", margin, now)
    # 남은 거리 ÷ 현재 속도로 계산한 대략 도착. 참고용이지만 답에 "10월 5일쯤"으로 나올 수 있어 카드로 둔다
    add("rule", "calc_eta", signals.calc_eta if signals else None, now)
    # 사용자가 넣은 날짜도 카드로 둔다. LLM이 "판매 예정일 10월 7일"처럼 말하면 V7이 이 카드로 숫자를 확인한다.
    # 날짜만 있는 값이라 _text(시각 변환)를 거치지 않는다. 거치면 UTC 0시로 읽혀 한국 시각 9시가 붙는다
    for field, day in (("sale_due_date", sale_due_date), ("forwarder_eta", forwarder_eta)):
        if day is not None:
            cards.append(Evidence(source="rule", field=field, value=day.isoformat(), fetched_at=now))
    return cards


def _ok(tool_output: dict | None) -> bool:
    """도구가 값을 돌려줬나. None이거나 {error:...}면 카드를 만들지 않는다 (SDD 3.4 도구 실패 형식)."""
    return bool(tool_output) and "error" not in tool_output


def _text(value) -> str:
    """근거 값은 문자열이다 (C1 Evidence.value). 시각은 한국 시각으로 바꾼다."""
    moment = value if isinstance(value, datetime) else _parse_time(value)
    if moment is not None:
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(KST).strftime("%Y-%m-%d %H:%M")
    return str(value)


def _parse_time(value) -> datetime | None:
    """도구 출력은 JSON이라 시각이 ISO 문자열로 온다. 시각 모양이 아니면 None."""
    if not isinstance(value, str) or "T" not in value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
