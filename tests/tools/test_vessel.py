"""믿을 ETA와 여유 일수 시험 (계획 8a). 값은 모두 가공값이다."""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from marvia.tools.rules import load_rules
from marvia.tools.vessel import (
    PortSchedule,
    Position,
    TrackPoint,
    days_margin,
    is_port_code,
    other_port,
    trusted_eta,
)

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 22, 3, 0, tzinfo=UTC)
PLANNED = datetime(2026, 9, 24, 12, 0, tzinfo=KST)
ACTUAL = datetime(2026, 9, 22, 10, 0, tzinfo=KST)
AIS = datetime(2026, 9, 24, 3, 0, tzinfo=UTC)


def position(dest_code: str | None = "KRPUS", ais_eta: datetime | None = AIS) -> Position:
    return Position(
        mmsi=999000001, lat=33.0, lng=128.0, sog=12.0, dest_code=dest_code, ais_eta=ais_eta, fetched_at=NOW
    )


def schedule(
    planned: datetime | None = None, actual: datetime | None = None, final: datetime | None = None
) -> PortSchedule:
    return PortSchedule(planned_arrival=planned, actual_arrival=actual, final_arrival=final, fetched_at=NOW)


def test_actual_arrival_beats_the_plan_and_the_plan_beats_the_ship_signal():
    assert trusted_eta(position(), schedule(PLANNED, ACTUAL), "KRPUS") == (ACTUAL, "mof_actual")
    assert trusted_eta(position(), schedule(PLANNED), "KRPUS") == (PLANNED, "mof_planned")
    assert trusted_eta(position(), schedule(), "KRPUS") == (AIS, "ais_eta")
    assert trusted_eta(position(), None, "KRPUS") == (AIS, "ais_eta")


def test_a_final_arrival_report_stands_in_for_the_arrival_until_the_control_record_comes():
    # [왜] 막 입항한 배는 배 신호 ETA가 이미 지났고 관제 실적은 아직 없다. 최종 입항 신고의 시각이
    #      실제 입항 시각이므로 그것을 쓴다. 관제 실적이 오면 관제 실적이 먼저다
    final = ACTUAL - timedelta(minutes=20)
    arrived = position(ais_eta=ACTUAL - timedelta(hours=1))
    now = ACTUAL + timedelta(hours=1)
    assert trusted_eta(arrived, schedule(), "KRPUS", now=now) == (None, None)
    assert trusted_eta(arrived, schedule(final=final), "KRPUS", now=now) == (final, "mof_final")
    assert trusted_eta(arrived, schedule(actual=ACTUAL, final=final), "KRPUS", now=now) == (
        ACTUAL,
        "mof_actual",
    )
    assert trusted_eta(None, schedule(PLANNED, final=final), "KRPUS")[1] == "mof_final"


def test_ship_eta_for_another_port_or_an_unknown_port_is_not_this_cargo_eta():
    # [왜] 목적지가 오사카면 그 ETA는 오사카 도착 시각이다 (v1 평가 문항 B09)
    assert trusted_eta(position("JPOSA"), schedule(), "KRPUS") == (None, None)
    assert trusted_eta(position("KRPUS"), schedule(), None) == (None, None)  # 양륙항을 모른다
    # [왜] 목적지 글이 깨졌거나 비었으면 그 ETA가 이 항만 도착 시각이라고 말해 주는 것이 없다.
    #      자료가 모자랄수록 등급이 좋아지면 안 된다. 목적지가 양륙항과 맞을 때만 믿을 출처로 친다
    assert trusted_eta(position(None), schedule(), "KRPUS") == (None, None)
    assert trusted_eta(position("QZ QZ"), schedule(), "KRPUS") == (None, None)
    assert trusted_eta(position(" krpus "), schedule(), "KRPUS") == (AIS, "ais_eta")  # 대소문자·공백만 다름
    # 해수부 일정이 함께 있으면 그것을 쓴다
    assert trusted_eta(position(None), schedule(PLANNED), "KRPUS") == (PLANNED, "mof_planned")


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


def test_a_ship_eta_that_already_passed_is_not_a_trusted_eta():
    # [왜] 배가 아직 멀리 있는데 배 신호 ETA가 열흘 전이면 그 값은 낡은 입력이다. 그것으로 여유 일수를 세면
    #      순항이 나왔다. 지금보다 앞선 ETA는 믿을 출처로 치지 않는다 (허용 오차는 rules/verdict.yaml)
    slack = timedelta(minutes=load_rules("verdict")["clock_skew_minutes"])
    past = position(ais_eta=NOW - slack - timedelta(minutes=1))
    assert trusted_eta(past, schedule(), "KRPUS", now=NOW) == (None, None)
    edge = position(ais_eta=NOW - slack)  # 허용 오차와 같으면 아직 쓴다
    assert trusted_eta(edge, schedule(), "KRPUS", now=NOW) == (NOW - slack, "ais_eta")
    # 해수부 일정이나 포워더 날짜가 있으면 그것으로 넘어간다. 해수부의 실제 입항은 지난 시각이 맞다
    assert trusted_eta(past, schedule(PLANNED, ACTUAL), "KRPUS", now=NOW) == (ACTUAL, "mof_actual")
    assert trusted_eta(past, None, "KRPUS", date(2026, 9, 25), now=NOW)[1] == "forwarder_eta"


@pytest.mark.parametrize(
    ("lat", "lng"), [(999, 128.0), (33.0, -181), (float("nan"), 128.0), (33.0, float("inf"))]
)
def test_a_position_outside_the_globe_is_not_a_position(lat, lng):
    # [왜] 위도 999나 NaN으로 거리를 재면 항구 앞 정지가 "꺼짐"으로 나오고 확신이 내려가지 않는다
    with pytest.raises(ValidationError):
        Position(mmsi=999000001, lat=lat, lng=lng, fetched_at=NOW)
    with pytest.raises(ValidationError):
        TrackPoint(at=NOW, lat=lat, lng=lng)


def test_a_blank_port_code_never_matches_a_missing_destination():
    # [왜] 공백뿐인 양륙항 코드와 없는 목적지 코드는 둘 다 빈 글이 된다. 빈 글끼리는 같다고 보지 않는다
    for blank in (" ", "", "\t"):
        assert trusted_eta(position(None), schedule(), blank) == (None, None)
        assert trusted_eta(position(" "), schedule(), blank) == (None, None)
