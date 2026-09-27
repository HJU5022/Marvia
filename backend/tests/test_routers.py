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
from backend.app.schemas.signals import Signal, SignalSet
from backend.app.services import llm

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

    def _use(*, customs=..., candidates=None, position=None, schedule=None, judge=None, pick=None):
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
        # LLM도 가짜로. 기본은 실패 → partial. judge에 dict를 주면 그 판정을 돌려준다
        monkeypatch.setattr(agent_router.llm, "judge", _fake_judge(judge))
        monkeypatch.setattr(agent_router.llm, "pick_vessel", _fake_pick(pick))

    return _use


def _fake_judge(answer: dict | None):
    def judge(signal_set, customs, margin, **kwargs):
        if answer is None:
            raise llm.LLMError("테스트: LLM 없음")
        return llm.LLMAnswer(output=llm.JudgeOutput.model_validate(answer),
                             llm=llm.LLMResult(content="", model="test/model"), prompt_version="test")
    return judge


def _fake_pick(answer: dict | None):
    """가짜 pick_vessel. None이면 LLM 실패."""
    def pick(candidates, customs, voyage_no=None, forwarder_eta=None, **kwargs):
        if answer is None:
            raise llm.LLMError("테스트: LLM 없음")
        return llm.LLMAnswer(output=llm.PickOutput.model_validate(answer),
                             llm=llm.LLMResult(content="", model="test/model"), prompt_version="test")
    return pick


JUDGED = {
    "verdict": "watch",
    "reasons": [{"rule": "navstat_mismatch", "value": "항해 중인데 속도 0", "triggered": True}],
    "conflicts": [], "actions": ["포워더에 확인"], "answer": "한 번 확인이 필요합니다.",
    "customs": {"plain_explanation": "화물이 터미널에 들어갔습니다.", "next_stage": "수입신고", "needs_broker": False},
}


def _all_clear(monkeypatch):
    """신호 7개를 전부 clear로 바꾼다. 규칙 판정(fine) 경로를 보려고."""
    ids = ["position_stale", "eta_conflict", "anchor_wait", "dest_changed",
           "navstat_mismatch", "customs_hold", "sales_date_exceeded"]
    signal_set = SignalSet(signals=[Signal(id=i, state="clear", value="-", threshold="-", source="test") for i in ids],
                           freshness="fresh", distance_nm=None, calc_eta=None, eta_gap_hours=None, computed_at=NOW)
    monkeypatch.setattr(agent_router.signals_service, "compute", lambda *a, **k: signal_set)


def test_single_candidate_is_confirmed(fake):
    fake(candidates=[_candidate(440999001)],
         position={"mmsi": 440999001, "lat": 35.1, "lng": 129.05, "sog": 0.0, "cog": 10.0,
                   "navistat": 8, "dest": "BUSAN, KR", "destcode": "KRPUS", "ais_eta": None,
                   "last_time": NOW.isoformat(), "fetched_at": NOW.isoformat()})

    with TestClient(app) as client:
        body = client.post("/api/agent", json=_request()).json()

    assert body["vessel_match"] == "confirmed"
    assert body["position"]["lat"] == 35.1
    assert body["status"] == "partial"  # LLM 실패면 판정 없이 partial (09-23 결정)
    assert body["verdict"] is None
    assert "sales_date_exceeded" not in body["answer"]  # 실패 안내 문장이 나간다


POSITION = {"mmsi": 440999001, "lat": 35.1, "lng": 129.05, "sog": 0.0, "cog": 10.0,
            "navistat": 8, "dest": "BUSAN, KR", "destcode": "KRPUS", "ais_eta": None,
            "last_time": NOW.isoformat(), "fetched_at": NOW.isoformat()}


def test_llm_verdict_fills_response(fake):
    """신호가 하나라도 켜지면 LLM 판정을 그대로 담는다. 통관 해설은 UNI-PASS 단계 이름과 합친다."""
    fake(candidates=[_candidate(440999001)], position=POSITION, judge=JUDGED)

    with TestClient(app) as client:
        body = client.post("/api/agent", json=_request()).json()

    assert (body["status"], body["verdict"], body["decided_by"]) == ("ok", "watch", "llm")
    assert body["actions"] == ["포워더에 확인"] and body["reasons"][0]["rule"] == "navstat_mismatch"
    assert body["customs"]["stage_name"] == "반입신고" and body["customs"]["next_stage"] == "수입신고"
    assert body["position"]["freshness"] in ("fresh", "stale")  # unknown이 아니라 signals가 계산한 값


def test_all_clear_is_fine_by_rule(fake, monkeypatch):
    """신호가 전부 clear면 LLM이 뭐라 하든 판정은 규칙으로 fine (SDD 4.1 7단계)."""
    fake(candidates=[_candidate(440999001)], position=POSITION, judge=JUDGED)
    _all_clear(monkeypatch)

    with TestClient(app) as client:
        body = client.post("/api/agent", json=_request()).json()

    assert (body["verdict"], body["decided_by"], body["status"]) == ("fine", "rule", "ok")
    assert body["answer"] == JUDGED["answer"]  # 문장은 LLM 것을 쓴다


def test_llm_hold_asks_forwarder_eta(fake):
    """LLM이 판정을 보류하면 포워더 입항 예정일을 묻는다 (skills/ais-reliability 되묻기 조건)."""
    fake(candidates=[_candidate(440999001)], position=POSITION, judge={**JUDGED, "verdict": None})

    with TestClient(app) as client:
        body = client.post("/api/agent", json=_request()).json()

    assert body["status"] == "insufficient" and body["missing_inputs"] == ["forwarder_eta"]
    assert body["verdict"] is None


def test_multiple_candidates_ask_back(fake):
    """동명 선박인데 LLM이 못 고르면(여기선 실패) 확정하지 않고 되묻는다 (PRD 6.2)."""
    fake(candidates=[_candidate(440999001), _candidate(440999002, call_sign="TST02")])

    with TestClient(app) as client:
        body = client.post("/api/agent", json=_request()).json()

    assert body["status"] == "insufficient" and body["vessel_match"] == "uncertain"
    assert len(body["vessel_candidates"]) == 2
    assert set(body["missing_inputs"]) == {"voyage_no", "forwarder_eta"}
    assert body["verdict"] is None


@pytest.mark.parametrize("confidence", ["medium", "low"])
def test_multiple_candidates_not_sure_ask_back(fake, confidence):
    """LLM이 골라도 high가 아니면 확정하지 않는다 (SDD 5.5)."""
    fake(candidates=[_candidate(440999001), _candidate(440999002, call_sign="TST02")],
         pick={"choice": 440999002, "confidence": confidence, "reasons_per_candidate": []})

    with TestClient(app) as client:
        body = client.post("/api/agent", json=_request()).json()

    assert body["status"] == "insufficient" and body["vessel_match"] == "uncertain"


def test_multiple_candidates_llm_sure_is_confirmed(fake):
    """LLM이 high로 고르면 그 배로 확정하고 판정까지 간다 (C-5)."""
    fake(candidates=[_candidate(440999001), _candidate(440999002, call_sign="TST02")],
         pick={"choice": 440999002, "confidence": "high", "reasons_per_candidate": []},
         position={**POSITION, "mmsi": 440999002}, judge=JUDGED)

    with TestClient(app) as client:
        body = client.post("/api/agent", json=_request()).json()

    assert body["vessel_match"] == "confirmed" and body["verdict"] == "watch"
    assert len(body["vessel_candidates"]) == 2  # 무엇 중에서 골랐는지 화면에 남긴다


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
