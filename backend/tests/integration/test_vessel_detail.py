"""선박 자세히 보기 테스트 (services/watch/vessel_detail.py). 도구 넷을 가짜로 끼운다. 키 없이 돈다."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.watch import vessel_detail as svc

NOW = datetime.now(timezone.utc)


def _fake(monkeypatch, *, pos_age_hours=1, candidates=True, schedule_error=False):
    calls = []
    monkeypatch.setattr(svc, "get_port_schedule", lambda **kw: calls.append(("mof", kw)) or (
        {"error": {"code": "timeout", "message": "느림", "retryable": True}} if schedule_error else
        {"planned_arrival": "2026-10-03T05:00:00+00:00", "actual_arrival": None, "facility": "신선대", "control_events": []}))
    monkeypatch.setattr(svc, "get_vessel_candidates", lambda **kw: calls.append(("cand", kw)) or {
        "candidates": [{"mmsi": 440999001, "name": "TEST SHIP", "call_sign": "TST01", "flag": "KR"}] if candidates else []})
    monkeypatch.setattr(svc, "get_live_position", lambda mmsi: calls.append(("pos", mmsi)) or {
        "mmsi": mmsi, "lat": 33.0, "lng": 128.0, "sog": 12.0, "dest": "BUSAN",
        "last_time": (NOW - timedelta(hours=pos_age_hours)).isoformat()})
    monkeypatch.setattr(svc, "estimate_distance", lambda lat, lng, sog: {"distance_nm": 120.0, "calc_hours_at_sog": 10.0})
    monkeypatch.setattr(svc, "route_points", lambda lat, lng: [[lat, lng], [35.1, 129.0]])
    svc._cache.clear()
    return calls


def test_combines_tools_and_caches(monkeypatch):
    calls = _fake(monkeypatch)
    r = svc.detail("TST01", "TEST SHIP")
    assert r["vessel"]["mmsi"] == 440999001 and r["position"]["freshness"] == "fresh"
    assert r["distance"]["distance_nm"] == 120.0 and r["distance"]["calc_eta"] and r["schedule"]["facility"] == "신선대"
    assert ("mof", {"call_sign": "TST01", "ship_name": None}) in calls  # 호출부호가 있으면 그것으로
    again = svc.detail("tst01", "test ship")
    assert len([c for c in calls if c[0] == "pos"]) == 1  # 10분 캐시: ShipFinder를 다시 부르지 않는다
    assert again["cached_at"] == r["cached_at"]  # 캐시에서 나가도 만든 시각 그대로
    assert datetime.fromisoformat(r["cached_at"]).tzinfo is not None


def test_stale_position_uses_rule(monkeypatch):
    _fake(monkeypatch, pos_age_hours=30)
    assert svc.detail("TST01", None)["position"]["freshness"] == "stale"  # rules.md position_stale_hours


def test_partial_when_tools_fail(monkeypatch):
    _fake(monkeypatch, candidates=False, schedule_error=True)
    r = svc.detail("TST01", "TEST SHIP")
    assert r["schedule"] is None and r["position"] is None
    assert {e["source"] for e in r["errors"]} == {"mof", "shipfinder"}


def test_api_requires_identifier(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    _fake(monkeypatch)
    with TestClient(app) as client:
        assert client.get("/api/vessels/detail").status_code == 400
        assert client.get("/api/vessels/detail", params={"call_sign": "TST01"}).json()["vessel"]["call_sign"] == "TST01"


def test_route_points_end_at_busan_and_are_capped():
    """지도용 남은 바닷길: 첫 점은 배, 마지막 점은 부산 기준점(rules.md busan_ref), 점 수 상한."""
    from backend.app.services.judge.rules import rule
    from mcp_server.tools.distance import ROUTE_MAX_POINTS, route_points
    ref = rule("busan_ref")
    far = route_points(31.2, 121.9)  # 상하이 앞바다
    assert far[-1] == [ref["lat"], ref["lng"]] and 2 < len(far) <= ROUTE_MAX_POINTS
    assert abs(far[0][0] - 31.2) < 1 and abs(far[0][1] - 121.9) < 1
    near = route_points(ref["lat"] + 0.01, ref["lng"])
    assert near == [[ref["lat"] + 0.01, ref["lng"]], [ref["lat"], ref["lng"]]]
