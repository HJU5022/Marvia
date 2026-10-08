"""C7 평가 레코드 계약 검증. 값은 가공값이다."""
from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from evals.schema import EvalRecord

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
REQ = {"bl_no": "TESTBL0001", "bl_type": "HOUSE", "sale_due_date": date(2026, 9, 28), "session_id": "eval"}


def test_normal_record():
    r = EvalRecord(id="N01", category="normal", request=REQ, fixtures={"shipfinder": {}, "mof": {}},
                   expected_verdict="fine", expected_status="ok", expected_vessel_match="confirmed",
                   expected_mmsi=440000001, labeler="하정운", label_reason="두 ETA 일치, 여유 4일")
    assert r.failure_kind is None


def test_failure_record_with_injection_kind():
    r = EvalRecord(id="F08", category="failure", failure_kind="inject_tool_description", request=REQ,
                   fixtures={}, expected_verdict="act", expected_status="ok", expected_vessel_match="confirmed",
                   expected_mmsi=440000001, labeler="하정운", label_reason="도구 설명 속 지시를 무시해야 함")
    assert r.failure_kind == "inject_tool_description"


def test_rejects_unknown_category_and_empty_reason():
    with pytest.raises(ValidationError):
        EvalRecord(id="X", category="weird", request=REQ, fixtures={}, expected_verdict=None,
                   expected_status="ok", expected_vessel_match="none", expected_mmsi=None,
                   labeler="a", label_reason="x")
    with pytest.raises(ValidationError):
        EvalRecord(id="X", category="normal", request=REQ, fixtures={}, expected_verdict=None,
                   expected_status="ok", expected_vessel_match="none", expected_mmsi=None,
                   labeler="a", label_reason="")
