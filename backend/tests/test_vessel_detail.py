"""선박 자세히 보기 테스트 (services/vessel_detail.py). 도구 넷을 가짜로 끼운다. 키 없이 돈다."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services import vessel_detail as svc

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
    svc._cache.clear()
    return calls


def test_combines_tools_and_caches(monkeypatch):
    calls = _fake(monkeypatch)
    r = svc.detail("TST01", "TEST SHIP")
    assert r["vessel"]["mmsi"] == 440999001 and r["position"]["freshness"] == "fresh"
    assert r["distance"]["distance_nm"] == 120.0 and r["distance"]["calc_eta"] and r["schedule"]["facility"] == "신선대"
    assert ("mof", {"call_sign": "TST01", "ship_name": None}) in calls  # 호출부호가 있으면 그것으로
    svc.detail("tst01", "test ship")
    assert len([c for c in calls if c[0] == "pos"]) == 1  # 10분 캐시: ShipFinder를 다시 부르지 않는다


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
