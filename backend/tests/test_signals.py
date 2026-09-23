"""C-4 1층 신호 판정 테스트. 신호 7종 × triggered·clear·unknown (SDD 9절)."""
from datetime import date, datetime, timedelta, timezone

import pytest

from backend.app.schemas.customs import CustomsRecord
from backend.app.services.signals import compute

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


def _position(**over) -> dict:
    base = {
        "mmsi": 440999001,
        "lat": 35.12,
        "lng": 129.05,
        "sog": 10.0,
        "cog": 180.0,
        "navistat": 0,
        "dest": "BUSAN, KR",
        "destcode": "KRPUS",
        "ais_eta": None,
        "last_time": (NOW - timedelta(hours=1)).isoformat(),
        "source": "shipfinder",
        "fetched_at": NOW.isoformat(),
    }
    return {**base, **over}


def _customs(stage_name: str = "입항보고") -> CustomsRecord:
    return CustomsRecord(stage_name=stage_name, bl_masked="TEST****0001", fetched_at=NOW)


def _state(result, signal_id: str) -> str:
    return next(s.state for s in result.signals if s.id == signal_id)


def test_all_seven_signals_present():
    result = compute(_position(), None, None, None, now=NOW)
    assert len(result.signals) == 7
    assert len({s.id for s in result.signals}) == 7


@pytest.mark.parametrize(
    "hours_ago, expected, freshness",
    [(1, "clear", "fresh"), (7, "triggered", "stale")],
)
def test_position_stale_uses_rules_threshold(hours_ago, expected, freshness):
    result = compute(_position(last_time=(NOW - timedelta(hours=hours_ago)).isoformat()), None, None, None, now=NOW)
    assert _state(result, "position_stale") == expected
    assert result.freshness == freshness


def test_position_stale_unknown_without_position():
    result = compute(None, None, None, None, now=NOW)
    assert _state(result, "position_stale") == "unknown" and result.freshness == "unknown"


def test_tool_error_is_treated_as_missing():
    """도구가 error를 돌려주면 값이 없는 것으로 본다."""
    result = compute({"error": {"code": "rate_limited"}}, None, None, None, now=NOW)
    assert _state(result, "position_stale") == "unknown"


@pytest.mark.parametrize("gap_hours, expected", [(6, "clear"), (20, "triggered")])
def test_eta_conflict(gap_hours, expected):
    ais = NOW + timedelta(hours=24)
    schedule = {"planned_arrival": (ais + timedelta(hours=gap_hours)).isoformat(), "actual_arrival": None}
    result = compute(_position(ais_eta=ais.isoformat()), schedule, None, None, now=NOW)
    assert _state(result, "eta_conflict") == expected
    assert result.eta_gap_hours == gap_hours


def test_eta_conflict_unknown_when_one_side_missing():
    result = compute(_position(ais_eta=(NOW + timedelta(hours=10)).isoformat()), None, None, None, now=NOW)
    assert _state(result, "eta_conflict") == "unknown" and result.eta_gap_hours is None


def test_anchor_wait_clear_when_moving_or_far():
    near_moving = compute(_position(sog=8.0), None, None, None, now=NOW)
    far_stopped = compute(_position(lat=33.0, lng=127.0, sog=0.0), None, None, None, now=NOW)
    assert _state(near_moving, "anchor_wait") == "clear"
    assert _state(far_stopped, "anchor_wait") == "clear"


def test_anchor_wait_unknown_when_stopped_near_busan():
    """지속 시간은 수집 이력(D1)이 있어야 알 수 있어 지금은 unknown이다."""
    result = compute(_position(sog=0.0), None, None, None, now=NOW)
    signal = next(s for s in result.signals if s.id == "anchor_wait")
    assert signal.state == "unknown" and "지속 시간 미확인" in signal.value


@pytest.mark.parametrize(
    "destcode, expected",
    [("KRPUS", "clear"), ("VNDQR", "triggered"), ("", "triggered")],
)
def test_dest_changed(destcode, expected):
    result = compute(_position(destcode=destcode), None, None, None, now=NOW)
    assert _state(result, "dest_changed") == expected


@pytest.mark.parametrize(
    "navistat, sog, expected",
    [(0, 10.0, "clear"), (1, 0.0, "clear"), (1, 12.0, "triggered"), (0, 0.0, "triggered")],
)
def test_navstat_mismatch(navistat, sog, expected):
    result = compute(_position(navistat=navistat, sog=sog), None, None, None, now=NOW)
    assert _state(result, "navstat_mismatch") == expected


def test_navstat_unknown_without_values():
    result = compute(_position(navistat=None), None, None, None, now=NOW)
    assert _state(result, "navstat_mismatch") == "unknown"


@pytest.mark.parametrize(
    "stage, expected",
    [("입항보고", "clear"), ("검사대상 지정", "triggered"), ("통관보류", "triggered")],
)
def test_customs_hold(stage, expected):
    result = compute(_position(), None, None, _customs(stage), now=NOW)
    assert _state(result, "customs_hold") == expected


def test_customs_unknown_without_record():
    assert _state(compute(_position(), None, None, None, now=NOW), "customs_hold") == "unknown"


@pytest.mark.parametrize(
    "eta_offset_days, due_offset_days, expected",
    [(1, 5, "clear"), (5, 1, "triggered")],
)
def test_sales_date_exceeded(eta_offset_days, due_offset_days, expected):
    schedule = {"planned_arrival": (NOW + timedelta(days=eta_offset_days)).isoformat(), "actual_arrival": None}
    due = (NOW + timedelta(days=due_offset_days)).date()
    result = compute(_position(), schedule, None, None, sale_due_date=due, now=NOW)
    assert _state(result, "sales_date_exceeded") == expected


def test_sales_date_unknown_without_due_date():
    assert _state(compute(_position(), None, None, None, now=NOW), "sales_date_exceeded") == "unknown"


def test_actual_arrival_wins_over_planned():
    """신뢰 ETA는 해수부 실적이 우선이다 (rules.md priority)."""
    schedule = {
        "actual_arrival": (NOW - timedelta(days=1)).isoformat(),
        "planned_arrival": (NOW + timedelta(days=10)).isoformat(),
    }
    due = (NOW + timedelta(days=2)).date()
    result = compute(_position(), schedule, None, None, sale_due_date=due, now=NOW)
    assert _state(result, "sales_date_exceeded") == "clear"  # 이미 들어왔으므로 여유가 있다


def test_distance_and_calc_eta_carried():
    distance = {"distance_nm": 120.0, "calc_hours_at_sog": 10.0, "source": "searoute", "fetched_at": NOW.isoformat()}
    result = compute(_position(), None, distance, None, now=NOW)
    assert result.distance_nm == 120.0
    assert result.calc_eta == NOW + timedelta(hours=10)
