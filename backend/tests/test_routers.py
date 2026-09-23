"""A6 POST /api/agent, A12 GET /api/history 라우터 테스트.

외부 API와 DB 없이 돈다. 서비스와 도구는 가짜로 바꿔 끼운다.
"""
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.routers import agent as agent_router
from backend.app.routers import history as history_router
from backend.app.schemas.customs import CustomsRecord

NOW = datetime(2026, 9, 23, 12, tzinfo=timezone.utc)


def _request(**over) -> dict:
    base = {
        "bl_no": "TESTMBL0000001",
        "bl_type": "MASTER",
        "sale_due_date": "2026-10-05",
        "session_id": "sess-1",
    }
    return {**base, **over}


def _candidate(mmsi: int, name: str = "TEST STAR", call_sign: str = "TST01") -> dict:
    return {
        "mmsi": mmsi, "imo": 9316684, "name": name, "call_sign": call_sign,
        "flag": "Panama", "dest": "BUSAN, KR", "last_time": NOW.isoformat(),
        "ship_type": 70, "similarity": 1.0,
    }


@pytest.fixture
def fake(monkeypatch):
    """UNI-PASS·도구·DB를 전부 가짜로. 라우터가 무엇을 어떤 순서로 부르는지만 본다."""

    def _use(*, customs=..., candidates=None, position=None, schedule=None):
        record = CustomsRecord(ship_name="TEST STAR", ship_nat="PA", stage_name="반입신고",
                               bl_masked="TEST****0001", fetched_at=NOW) if customs is ... else customs

        class FakeUnipass:
            def __init__(self, *a, **k):
                pass

            def fetch(self, *a, **k):
                return record

        monkeypatch.setattr(agent_router, "UnipassClient", FakeUnipass)
        monkeypatch.setattr(agent_router, "get_vessel_candidates",
                            lambda **k: {"candidates": candidates or [], "source": "shipfinder", "fetched_at": NOW.isoformat()})
        monkeypatch.setattr(agent_router, "get_live_position", lambda mmsi: position or {"error": {"code": "not_found"}})
        monkeypatch.setattr(agent_router, "get_port_schedule", lambda **k: schedule or {"planned_arrival": None, "actual_arrival": None, "fetched_at": NOW.isoformat()})
        monkeypatch.setattr(agent_router, "_logged", lambda request, response: response)  # DB 없이

    return _use


def test_single_candidate_is_confirmed(fake):
    fake(candidates=[_candidate(440999001)],
         position={"mmsi": 440999001, "lat": 35.1, "lng": 129.05, "sog": 0.0, "cog": 10.0,
                   "navistat": 8, "dest": "BUSAN, KR", "destcode": "KRPUS", "ais_eta": None,
                   "last_time": NOW.isoformat(), "fetched_at": NOW.isoformat()})

    with TestClient(app) as client:
        body = client.post("/api/agent", json=_request()).json()

    assert body["vessel_match"] == "confirmed"
    assert body["position"]["lat"] == 35.1
    assert body["status"] == "partial"  # 판정(C-6)이 아직 없다
    assert body["verdict"] is None


def test_multiple_candidates_ask_back(fake):
    """동명 선박이면 확정하지 않고 되묻는다 (PRD 6.2)."""
    fake(candidates=[_candidate(440999001), _candidate(440999002, call_sign="TST02")])

    with TestClient(app) as client:
        body = client.post("/api/agent", json=_request()).json()

    assert body["status"] == "insufficient" and body["vessel_match"] == "uncertain"
    assert len(body["vessel_candidates"]) == 2
    assert set(body["missing_inputs"]) == {"voyage_no", "forwarder_eta"}
    assert body["verdict"] is None


def test_unknown_bl_is_insufficient_not_failed(fake):
    """없는 B/L은 실패가 아니라 정보 부족이다 (SDD 4.1)."""
    fake(customs=None)

    with TestClient(app) as client:
        body = client.post("/api/agent", json=_request()).json()

    assert body["status"] == "insufficient" and body["missing_inputs"] == ["bl_type"]
    assert "B/L 번호와 M/H 구분" in body["answer"]


def test_resolved_mmsi_skips_candidate_search(fake):
    """되묻기 답을 받으면 후보를 다시 찾지 않는다."""
    fake(candidates=[_candidate(1), _candidate(2)])

    with TestClient(app) as client:
        body = client.post("/api/agent", json=_request(resolved_mmsi=440999009)).json()

    assert body["vessel_match"] == "confirmed" and body["vessel_candidates"] == []


def test_invalid_bl_is_rejected():
    """B/L 형식 검증은 스키마가 한다 (A7)."""
    with TestClient(app) as client:
        assert client.post("/api/agent", json=_request(bl_no="짧음")).status_code == 422


def test_history_without_db_returns_unavailable(monkeypatch):
    """DB가 없으면 빈 이력이 아니라 available=false로 알린다."""
    def boom(*a, **k):
        raise RuntimeError("no db")

    monkeypatch.setattr(history_router, "connect", boom)
    with TestClient(app) as client:
        body = client.get("/api/history", params={"session_id": "sess-1"}).json()

    assert body["items"] == [] and body["available"] is False


def test_history_reads_session_rows(monkeypatch):
    rows = [{
        "request_id": "req-1", "bl_masked": "TEST****0001", "status": "partial", "verdict": None,
        "vessel_match": "confirmed", "decided_by": None, "model": None, "trace_id": "req-1",
        "created_at": NOW,
    }]

    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(history_router, "connect", lambda *a, **k: FakeConn())
    monkeypatch.setattr(history_router, "recent_queries", lambda conn, session_id, limit: rows if session_id == "sess-1" else [])

    with TestClient(app) as client:
        mine = client.get("/api/history", params={"session_id": "sess-1"}).json()
        other = client.get("/api/history", params={"session_id": "sess-2"}).json()

    assert len(mine["items"]) == 1 and mine["items"][0]["bl_masked"] == "TEST****0001"
    assert other["items"] == [] and other["available"] is True
