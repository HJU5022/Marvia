"""믿을 ETA와 여유 일수 시험 (계획 8a). 값은 모두 가공값이다."""

from datetime import UTC, date, datetime, timedelta, timezone

from marvia.tools.vessel import PortSchedule, Position, days_margin, is_port_code, other_port, trusted_eta

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 22, 3, 0, tzinfo=UTC)
PLANNED = datetime(2026, 9, 24, 12, 0, tzinfo=KST)
ACTUAL = datetime(2026, 9, 22, 10, 0, tzinfo=KST)
AIS = datetime(2026, 9, 24, 3, 0, tzinfo=UTC)


def position(dest_code: str | None = "KRPUS", ais_eta: datetime | None = AIS) -> Position:
    return Position(
        mmsi=999000001, lat=33.0, lng=128.0, sog=12.0, dest_code=dest_code, ais_eta=ais_eta, fetched_at=NOW
    )


def schedule(planned: datetime | None = None, actual: datetime | None = None) -> PortSchedule:
    return PortSchedule(planned_arrival=planned, actual_arrival=actual, fetched_at=NOW)


def test_actual_arrival_beats_the_plan_and_the_plan_beats_the_ship_signal():
    assert trusted_eta(position(), schedule(PLANNED, ACTUAL), "KRPUS") == (ACTUAL, "mof_actual")
    assert trusted_eta(position(), schedule(PLANNED), "KRPUS") == (PLANNED, "mof_planned")
    assert trusted_eta(position(), schedule(), "KRPUS") == (AIS, "ais_eta")
    assert trusted_eta(position(), None, "KRPUS") == (AIS, "ais_eta")


def test_ship_eta_for_another_port_or_an_unknown_port_is_not_this_cargo_eta():
    # [왜] 목적지가 오사카면 그 ETA는 오사카 도착 시각이다 (v1 평가 문항 B09)
    assert trusted_eta(position("JPOSA"), schedule(), "KRPUS") == (None, None)
    assert trusted_eta(position("KRPUS"), schedule(), None) == (None, None)  # 양륙항을 모른다
    # 목적지 글이 깨졌거나 비었으면 다른 항구라고 말할 근거가 없다. 그 ETA는 쓴다
    assert trusted_eta(position(None), schedule(), "KRPUS") == (AIS, "ais_eta")


def test_forwarder_date_is_the_last_resort_and_is_read_as_a_korean_day():
    eta, source = trusted_eta(None, None, "KRPUS", forwarder_eta=date(2026, 9, 25))
    assert source == "forwarder_eta" and eta == datetime(2026, 9, 25, 0, 0, tzinfo=KST)
    assert (
        trusted_eta(position(), schedule(PLANNED), "KRPUS", forwarder_eta=date(2026, 9, 25))[1]
        == "mof_planned"
    )
    assert trusted_eta(None, None, "KRPUS") == (None, None)


def test_margin_counts_korean_calendar_days():
    assert days_margin(PLANNED, date(2026, 9, 28)) == 4
    assert days_margin(PLANNED, date(2026, 9, 23)) == -1  # 판매 예정일보다 하루 늦게 도착
    # 한국 시각 9월 25일 01:00은 UTC로 24일이다. 한국 날짜로 세야 한다
    assert days_margin(datetime(2026, 9, 24, 16, 0, tzinfo=UTC), date(2026, 9, 25)) == 0
    assert days_margin(None, date(2026, 9, 28)) is None and days_margin(PLANNED, None) is None


def test_port_code_shape_and_other_port():
    assert is_port_code("KRPUS") and is_port_code("jposa") and is_port_code("CN2QD")
    assert not is_port_code("BUSAN PORT") and not is_port_code("KR1US") and not is_port_code(None)
    assert other_port(position("JPOSA"), "KRPUS") == "JPOSA"
    assert other_port(position("KRPUS"), "KRPUS") is None and other_port(position("XX QZQ"), "KRPUS") is None
    assert other_port(position("JPOSA"), None) is None and other_port(None, "KRPUS") is None
