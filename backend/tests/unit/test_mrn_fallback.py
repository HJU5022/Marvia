"""MRN 대체 조회 테스트 (docs/specs/mrn-fallback.md). 해수부·ShipFinder 도구는 가짜로 끼운다. 키 없이 돈다."""
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.schemas.agent import AgentRequest
from backend.app.services.chat import chat as chat_svc
from backend.app.services.chat import doc_ocr
from backend.app.services.judge import mrn_fallback as svc

KST = timezone(timedelta(hours=9))


class _Plan:
    ship_name, call_sign, nationality, facility, mrn = "TEST VICTORY", "TST01", "KOREA", "감만부두 4선석", "26TEST0001I"
    expected_arrival = datetime(2026, 10, 3, 9, 0, tzinfo=KST)


class _Mof:
    def __init__(self, plans):
        self.plans = plans

    def sailing_plans_all(self, start, end):
        return self.plans

    def close(self):
        pass


def _req(mrn="26TEST0001I"):
    return AgentRequest(bl_no="TESTBL0001", bl_type="HOUSE", session_id="s", mrn=mrn)


@pytest.fixture
def tools(monkeypatch):
    monkeypatch.setattr(svc, "MofClient", lambda: _Mof([_Plan()]))
    monkeypatch.setattr(svc, "get_vessel_candidates", lambda **kw: {"candidates": [{"mmsi": 440999001, "name": "TEST VICTORY"}]})
    monkeypatch.setattr(svc, "get_live_position", lambda mmsi: {"lat": 34.9, "lng": 129.5, "sog": 12.0, "cog": 300.0, "navistat": 0,
                                                                  "last_time": datetime.now(timezone.utc).isoformat()})
    monkeypatch.setattr(svc, "estimate_distance", lambda lat, lng, sog: {"distance_nm": 24.0, "calc_hours_at_sog": 2.0})


def test_partial_with_vessel_when_customs_missing(tools):
    r = svc.assess(_req())
    assert r.status == "partial" and r.verdict is None and r.customs is None  # 판정하지 않는다
    assert r.vessel.name == "TEST VICTORY" and r.vessel.call_sign == "TST01" and r.position.freshness == "fresh"
    assert r.eta.mof_eta == _Plan.expected_arrival and r.eta.trusted_eta is None and r.eta.distance_nm == 24.0
    assert r.berth.facility == "감만부두 4선석" and "세관" in r.answer


def test_none_when_mof_has_no_such_mrn(tools, monkeypatch):
    monkeypatch.setattr(svc, "MofClient", lambda: _Mof([]))
    assert svc.assess(_req()) is None  # EC-02: 원래 응답 그대로


def test_mof_only_when_ais_fails(tools, monkeypatch):
    monkeypatch.setattr(svc, "get_live_position", lambda mmsi: {"error": {"code": "rate_limited", "message": "x", "retryable": True}})
    r = svc.assess(_req())
    assert r.status == "partial" and r.position is None and r.eta.mof_eta is not None  # EC-03


def test_mrn_validation():
    assert _req(" 26test0001i ").mrn == "26TEST0001I"
    with pytest.raises(ValueError):
        _req("BAD")


def test_chat_extracts_mrn_before_masking():
    mrn, text = chat_svc.extract_mrn("TESTBL0001 MRN: 26test0001i 화물 어때")
    assert mrn == "26TEST0001I" and "26TEST" not in text.upper()
    masked, refs = chat_svc.mask_bls(text)
    assert list(refs.values()) == ["TESTBL0001"]  # MRN이 B/L로 잘못 가려지지 않는다


def test_document_reads_mrn_with_ocr_confusion():
    assert doc_ocr.take_mrn(["E.T.D. 2026-09-30", "MRN: 26TESTAB121", "MSN: 3805"]) == "26TESTAB12I"  # 끝의 1은 I
    assert doc_ocr.take_mrn(["MRN:", "26TESTAB12I"]) == "26TESTAB12I" and doc_ocr.take_mrn(["B/L NO."]) is None


def test_agent_uses_fallback_only_for_missing_customs(monkeypatch):
    from backend.app.routers import agent
    from backend.app.routers.agent import _response
    monkeypatch.setattr(agent, "_fetch_customs", lambda req: (None, _response(status="insufficient", answer="없음")))
    monkeypatch.setattr(svc, "assess", lambda req: _response(status="partial", answer="대체"))
    assert agent._assess(_req()).answer == "대체"
    assert agent._assess(_req(mrn=None)).status == "insufficient"
    monkeypatch.setattr(agent, "_fetch_customs", lambda req: (None, _response(status="failed", answer="세관 장애")))
    assert agent._assess(_req()).status == "failed"  # EC-04
