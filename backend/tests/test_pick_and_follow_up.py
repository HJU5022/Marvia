"""llm.pick_vessel()·answer_follow_up() 테스트 (C-5·C-9 LLM 부분). 키 없이 돈다: chat()을 가짜로 바꾼다."""
import json
from datetime import datetime, timezone

import pytest

from backend.app.schemas.agent import AgentResponse, VesselCandidate
from backend.app.schemas.customs import CustomsRecord
from backend.app.services import llm

NOW = datetime(2026, 9, 27, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def local_prompt(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)


def _fake_chat(monkeypatch, answer: dict):
    calls = []

    def fake_chat(messages, **kwargs):
        calls.append({"messages": messages, **kwargs})
        return llm.LLMResult(content=json.dumps(answer, ensure_ascii=False), model="test/model")

    monkeypatch.setattr(llm, "chat", fake_chat)
    return calls


def _candidates() -> list[VesselCandidate]:
    """가공값. 이름이 같은 배 두 척."""
    return [
        VesselCandidate(mmsi=440999001, imo=9900001, name="TEST STAR", flag="PA", dest="KRPUS",
                        last_time=NOW, ship_type=70, match_reasons=[]),
        VesselCandidate(mmsi=440999002, imo=9900002, name="TEST STAR", flag="LR", dest="CNSHA",
                        last_time=NOW, ship_type=80, match_reasons=[]),
    ]


def _customs() -> CustomsRecord:
    return CustomsRecord(ship_name="TEST STAR", ship_nat="PA", voyage="0012W", mrn="26TEST0099I",
                         bl_masked="TEST****0001", fetched_at=NOW)


# ── pick_vessel ──

def test_pick_sends_customs_and_candidates_without_bl(monkeypatch):
    calls = _fake_chat(monkeypatch, {"choice": None, "confidence": "low", "reasons_per_candidate": []})
    llm.pick_vessel(_candidates(), _customs(), voyage_no="0012W")

    user = calls[0]["messages"][1]["content"]
    data = json.loads(user)
    assert data["customs"]["ship_nat"] == "PA" and data["user_voyage_no"] == "0012W"
    assert len(data["candidates"]) == 2
    assert "TEST****0001" not in user and "26TEST0099I" not in user  # B/L·MRN은 LLM에 안 간다


def test_pick_sends_hours_since_last_computed_by_code(monkeypatch):
    """LLM은 지금 시각을 모른다. 경과 시간은 코드가 계산해 넣는다 (09-27 스모크 테스트에서 발견)."""
    calls = _fake_chat(monkeypatch, {"choice": None, "confidence": "low", "reasons_per_candidate": []})
    llm.pick_vessel(_candidates(), _customs(), now=NOW.replace(hour=3))

    candidates = json.loads(calls[0]["messages"][1]["content"])["candidates"]
    assert [c["hours_since_last"] for c in candidates] == [3.0, 3.0]  # 후보 둘 다 last_time=NOW(0시)


def test_pick_reads_choice(monkeypatch):
    _fake_chat(monkeypatch, {"choice": 440999001, "confidence": "high",
                             "reasons_per_candidate": [{"mmsi": 440999001, "reason": "국적 PA 일치"}]})
    out = llm.pick_vessel(_candidates(), _customs()).output
    assert (out.choice, out.confidence) == (440999001, "high")


def test_pick_rejects_mmsi_not_in_candidates(monkeypatch):
    """후보에 없는 배로 확정하면 안 된다 (오확정 방지)."""
    _fake_chat(monkeypatch, {"choice": 123456789, "confidence": "high", "reasons_per_candidate": []})
    with pytest.raises(llm.LLMError):
        llm.pick_vessel(_candidates(), _customs())


# ── answer_follow_up ──

def _response() -> AgentResponse:
    return AgentResponse(status="ok", verdict="watch", vessel_match="confirmed", days_margin=5, decided_by="llm",
                         vessel=None, position=None, eta=None, customs=None, berth=None, evidence=[],
                         answer="한 번 확인이 필요합니다.", trace_id="trace-test")


def test_follow_up_sends_question_as_data(monkeypatch):
    calls = _fake_chat(monkeypatch, {"in_scope": True, "answer": "여유는 5일입니다."})
    llm.answer_follow_up("여유가 며칠이야?", _response())

    data = json.loads(calls[0]["messages"][1]["content"])
    assert data["question"] == "여유가 며칠이야?"
    assert data["result"]["days_margin"] == 5 and "trace_id" not in data["result"]
    assert calls[0]["messages"][0]["role"] == "system"  # 질문은 system이 아니라 user 쪽 데이터로만 간다


def test_follow_up_reads_out_of_scope(monkeypatch):
    _fake_chat(monkeypatch, {"in_scope": False, "answer": "이 화물의 조회 결과 안에서만 답할 수 있습니다."})
    out = llm.answer_follow_up("비트코인 시세 알려줘", _response()).output
    assert out.in_scope is False
