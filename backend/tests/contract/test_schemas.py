"""A2 완료 기준: 계약 C1·C2·C3·C5·C4가 import 되고 예시 JSON이 검증을 통과한다 (작업 리스트 A2).

키 없이 돈다. 값은 전부 가공값이다 (실제 B/L·실제 응답 아님, CLAUDE.md).
"""
from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from backend.app.schemas.agent import AgentRequest, AgentResponse, VesselInfo
from backend.app.schemas.customs import CustomsRecord, mask_bl
from backend.app.schemas.signals import Signal, SignalSet
from mcp_server.schemas import LivePositionResult, ToolError, VesselCandidatesResult

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)


def test_request_normalizes_bl_and_accepts_optional_fields():
    req = AgentRequest(bl_no=" test bl 0001 ", bl_type="HOUSE", sale_due_date=date(2026, 9, 28), session_id="s1")
    assert req.bl_no == "TESTBL0001"           # 공백 제거·대문자
    assert req.follow_up_question is None      # 첫 조회는 선택 칸이 비어 있다


@pytest.mark.parametrize("bad", ["ABC", "A" * 21, "TEST-BL-01"])
def test_request_rejects_bad_bl(bad):
    with pytest.raises(ValidationError):
        AgentRequest(bl_no=bad, bl_type="MASTER", sale_due_date=date(2026, 9, 28), session_id="s1")


def test_request_rejects_long_follow_up():
    with pytest.raises(ValidationError):
        AgentRequest(bl_no="TESTBL0001", bl_type="MASTER", sale_due_date=date(2026, 9, 28),
                     session_id="s1", follow_up_question="x" * 301)


def _ok_response() -> dict:
    return {
        "status": "ok", "verdict": "watch", "vessel_match": "confirmed",
        "reasons": [{"rule": "eta_conflict", "value": "14h", "triggered": True}],
        "conflicts": [{"signals": ["eta_conflict", "dest_changed"], "chosen": "mof", "why": "해수부 예정을 신뢰"}],
        "actions": ["포워더에 도착 이후 일정 확인"],
        "days_margin": 3, "decided_by": "llm",
        "vessel": {"mmsi": 440000001, "imo": 9000001, "name": "TEST CARGO A", "call_sign": "TESTA",
                   "flag": "KR", "ship_type": 70, "voyage_no": "001E"},
        "position": {"lat": 33.0, "lng": 128.0, "sog": 12.0, "cog": 45.0, "navistat": 0,
                     "last_time": NOW.isoformat(), "freshness": "fresh"},
        "eta": {"ais_eta": NOW.isoformat(), "mof_eta": NOW.isoformat(), "calc_eta": None,
                "trusted_eta": NOW.isoformat(), "distance_nm": 120.5},
        "customs": {"stage_code": "T01", "stage_name": "입항 전", "plain_explanation": "아직 입항 전입니다.",
                    "next_stage": "입항보고 수리", "needs_broker": False, "history": []},
        "berth": {"facility": None, "shed": None},
        "evidence": [{"source": "mof", "field": "planned_arrival", "value": "2026-09-24T12:00+09:00",
                      "fetched_at": NOW.isoformat()}],
        "answer": "해수부 기준 24일 입항 예정, 판매일까지 3일 여유.",
        "trace_id": "trace-test-1",
    }


def test_response_ok_example_validates():
    res = AgentResponse.model_validate(_ok_response())
    assert res.vessel.name == "TEST CARGO A"
    assert res.days_margin == 3


def test_response_insufficient_example_validates():
    """되묻기: verdict 없음, 후보 목록 채움 (SDD 8절)."""
    d = _ok_response()
    d.update({"status": "insufficient", "verdict": None, "vessel_match": "uncertain", "vessel": None,
              "days_margin": None, "decided_by": None, "reasons": [], "conflicts": [],
              "missing_inputs": ["voyage_no", "forwarder_eta"],
              "vessel_candidates": [{"mmsi": 440000001, "imo": None, "name": "TEST PAN", "flag": "MH",
                                     "dest": "BUSAN", "last_time": NOW.isoformat(), "ship_type": 70,
                                     "match_reasons": ["선명 일치"]}]})
    res = AgentResponse.model_validate(d)
    assert res.verdict is None and len(res.vessel_candidates) == 1


def test_response_failed_keeps_evidence():
    d = _ok_response()
    d.update({"status": "failed", "verdict": None, "decided_by": None,
              "answer": "판정을 생성하지 못했습니다. 근거 카드를 확인하세요."})
    res = AgentResponse.model_validate(d)
    assert res.evidence  # 실패해도 근거 카드는 남긴다


def test_response_unsupported_for_out_of_scope_port():
    # 부산 외 항만 요청: 판정·선박 없이 범위 밖 안내만 한다. failed와 다른 상태다.
    d = _ok_response()
    d.update({"status": "unsupported", "verdict": None, "vessel_match": "none", "decided_by": None,
              "days_margin": None, "vessel": None, "position": None, "eta": None, "customs": None, "berth": None,
              "answer": "부산항 수입 화물만 지원합니다."})
    res = AgentResponse.model_validate(d)
    assert res.status == "unsupported" and res.verdict is None


def test_response_rejects_unknown_status():
    d = _ok_response(); d["status"] = "maybe"
    with pytest.raises(ValidationError):
        AgentResponse.model_validate(d)


def test_vessel_info_has_seven_fields():
    assert set(VesselInfo.model_fields) == {"mmsi", "imo", "name", "call_sign", "flag", "ship_type", "voyage_no"}


def test_signal_set_accepts_seven_ids_and_rejects_unknown():
    ids = ["position_stale", "eta_conflict", "anchor_wait", "dest_changed",
           "navstat_mismatch", "customs_hold", "sales_date_exceeded"]
    signals = [Signal(id=i, state="clear", value="-", threshold="-", source="rule") for i in ids]
    ss = SignalSet(signals=signals, freshness="fresh", distance_nm=None, calc_eta=None,
                   eta_gap_hours=None, computed_at=NOW)
    assert len(ss.signals) == 7
    with pytest.raises(ValidationError):
        Signal(id="weather_bad", state="clear", value="-", threshold="-", source="rule")


def test_customs_record_has_no_sensitive_fields():
    rec = CustomsRecord(ship_name="TEST CARGO A", ship_nat="KR", bl_masked=mask_bl("TESTBL0001"), fetched_at=NOW)
    assert rec.bl_masked == "TE*****001"  # 가운데 절반을 가린다 (SDD 3.5). 홀수 남는 자리는 뒤로
    # 품명은 오후부터 goods_name으로 둔다. 중량·화주·세관명은 여전히 자리가 없다
    for banned in ("prnm", "wght", "consignee", "customs_office"):
        assert banned not in CustomsRecord.model_fields


def test_mask_bl_short_keeps_ends_readable():
    """변경: 8자 이하도 전부 가리지 않는다. 조회 이력에서 알아볼 수 있게 가운데 절반만"""
    assert mask_bl("ABCD1234") == "AB****34"


def test_mcp_tool_results_and_error():
    r = VesselCandidatesResult(candidates=[], fetched_at=NOW)
    assert r.source == "shipfinder"
    p = LivePositionResult(mmsi=440000001, lat=33.0, lng=128.0, sog=None, cog=None, navistat=None,
                           dest=None, destcode=None, ais_eta=None, last_time=None, fetched_at=NOW)
    assert "freshness" not in LivePositionResult.model_fields  # freshness 판정은 도구 몫이 아니다 (B4 경계)
    err = ToolError(code="rate_limited", message="29", retryable=True)
    assert err.model_dump() == {"code": "rate_limited", "message": "29", "retryable": True}
