"""자연어 입력 테스트 (docs/specs/chat-search.md, services/chat.py, routers/chat.py).

LLM·해수부·판정 흐름은 부르지 않는다. llm.route_chat / match_ports, 해수부 캐시, run_agent를 가짜로 끼운다.
"""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.routers import chat as chat_router
from backend.app.schemas.agent import AgentRequest
from backend.app.services import chat as svc
from backend.app.services import llm


class _Plan:
    def __init__(self, name, port, day):
        self.ship_name, self.call_sign, self.nationality, self.ship_kind = name, "CS" + name[-1], "KR", "컨테이너선"
        self.previous_port, self.next_port, self.purpose, self.facility = port, None, "양하", "신선대"
        self.expected_arrival = datetime(2026, 10, day, tzinfo=timezone.utc)


PLANS = [_Plan("SHIP A", "SHANGHAI", 3), _Plan("SHIP B", "KOBE", 2), _Plan("SHIP C", "NINGBO PT", 4)]


def _route(monkeypatch, **out):
    calls = []
    base = {"intent": "other", "bl_ref": None, "bl_type": None, "sale_due_date": None, "question": None,
            "place": None, "place_label": None, "days": None, "reply": ""}

    def fake(masked, refs, has_cargo, today, **kw):
        calls.append({"masked": masked, "refs": refs, "has_cargo": has_cargo})
        return llm.LLMAnswer(output=llm.ChatRouteOutput(**{**base, **out}), llm=None, prompt_version="test")
    monkeypatch.setattr(llm, "route_chat", fake)
    return calls


def _agent_calls():
    calls = []

    def run(req):
        calls.append(req)
        from backend.app.routers.agent import _response
        return _response(status="ok", answer="괜찮습니다")
    return calls, run


def test_mask_bls_hides_numbers_and_keeps_words():
    masked, refs = svc.mask_bls("testbl01 화물이랑 TESTBL01, MSCU1234567 비교해줘 shanghai")
    assert masked == "[BL1] 화물이랑 [BL1], [BL2] 비교해줘 shanghai"  # 같은 B/L은 같은 토큰, 숫자 없는 영어 단어는 그대로
    assert refs == {"[BL1]": "TESTBL01", "[BL2]": "MSCU1234567"}


def test_llm_never_sees_bl(monkeypatch):
    calls = _route(monkeypatch, intent="cargo", bl_ref="[BL1]")
    agent, run = _agent_calls()
    r = svc.handle("TESTBL01 괜찮아?", "s1", None, run)
    assert "TESTBL01" not in calls[0]["masked"] and agent[0].bl_no == "TESTBL01"
    assert agent[0].bl_type == "HOUSE" and "House B/L로 조회" in r.reply  # 구분을 말하지 않으면 HOUSE로 알림


def test_cargo_uses_stated_type_and_valid_date_only(monkeypatch):
    _route(monkeypatch, intent="cargo", bl_ref="[BL1]", bl_type="MASTER", sale_due_date="2026-13-40")
    agent, run = _agent_calls()
    r = svc.handle("TESTBL01 마스터", "s1", None, run)
    assert agent[0].bl_type == "MASTER" and agent[0].sale_due_date is None  # 없는 날짜는 버린다
    assert "House" not in r.reply


def test_bl_ref_outside_masked_list_is_ignored(monkeypatch):
    _route(monkeypatch, intent="cargo", bl_ref="[BL9]")
    agent, run = _agent_calls()
    assert svc.handle("뭐든", "s1", None, run).reply == svc.NEED_BL and agent == []  # EC-02


def test_follow_up_needs_cargo_and_uses_context(monkeypatch):
    _route(monkeypatch, intent="follow_up", question="언제 도착해?")
    agent, run = _agent_calls()
    assert svc.handle("언제 와?", "s1", None, run).reply == svc.NO_CARGO  # EC-03
    ctx = AgentRequest(bl_no="TESTBL01", bl_type="HOUSE", session_id="old")
    r = svc.handle("언제 와?", "s1", ctx, run)
    assert r.kind == "cargo" and agent[0].follow_up_question == "언제 도착해?" and agent[0].session_id == "s1"


def test_fallback_without_llm(monkeypatch):
    def broken(*a, **k):
        raise llm.LLMError("no key", kind="not_configured")
    monkeypatch.setattr(llm, "route_chat", broken)
    agent, run = _agent_calls()
    assert svc.handle("TESTBL04 어때", "s1", None, run).kind == "cargo" and agent[0].bl_no == "TESTBL04"  # EC-01
    assert svc.handle("중국에서 오는 배", "s1", None, run).reply == svc.LLM_DOWN


def test_vessel_search_keeps_only_listed_ports(monkeypatch):
    _route(monkeypatch, intent="vessel_search", place="China", days=99)
    monkeypatch.setattr(svc, "_arrivals", lambda days: PLANS)
    seen = {}

    def fake_match(place, ports, **kw):
        seen["ports"] = ports
        return llm.LLMAnswer(output=llm.PortMatchOutput(ports=["SHANGHAI", "NINGBO PT", "BEIJING"]), llm=None,
                             prompt_version="test")
    monkeypatch.setattr(llm, "match_ports", fake_match)
    r = svc.handle("중국에서 부산 오는 배", "s1", None, lambda req: None)
    assert seen["ports"] == ["KOBE", "NINGBO PT", "SHANGHAI"]
    assert r.kind == "vessels" and r.ports == ["SHANGHAI", "NINGBO PT"] and r.days == svc.DAYS_MAX  # 목록 밖 BEIJING 버림, 기간 상한
    assert [v["ship_name"] for v in r.vessels] == ["SHIP A", "SHIP C"]  # 입항 예정 순


def test_vessel_search_no_match_explains_previous_port(monkeypatch):
    _route(monkeypatch, intent="vessel_search", place="Netherlands", place_label="네덜란드")
    monkeypatch.setattr(svc, "_arrivals", lambda days: PLANS)
    monkeypatch.setattr(llm, "match_ports", lambda place, ports, **kw: llm.LLMAnswer(
        output=llm.PortMatchOutput(ports=[]), llm=None, prompt_version="test"))
    r = svc.handle("네덜란드에서 한국 오는 배 뭐야", "s1", None, lambda req: None)
    assert r.vessels == [] and "직전 기항지" in r.reply and "네덜란드" in r.reply and r.place == "네덜란드"  # EC-04


def test_other_returns_reply(monkeypatch):
    _route(monkeypatch, intent="other", reply="B/L 번호로 화물을 조회할 수 있어요.")
    assert svc.handle("안녕", "s1", None, lambda req: None).reply == "B/L 번호로 화물을 조회할 수 있어요."


def test_api(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    _route(monkeypatch, intent="cargo", bl_ref="[BL1]")
    agent, run = _agent_calls()
    monkeypatch.setattr(chat_router, "run_agent", lambda req, user_id: run(req))
    with TestClient(app) as client:
        r = client.post("/api/chat", json={"message": "TESTBL01 괜찮아?", "session_id": "s1"})
        assert r.status_code == 200 and r.json()["kind"] == "cargo" and r.json()["request"]["bl_no"] == "TESTBL01"
        assert client.post("/api/chat", json={"message": "가" * 501, "session_id": "s1"}).status_code == 422  # EC-07
        assert client.post("/api/chat", json={"message": "  ", "session_id": "s1"}).status_code == 400
