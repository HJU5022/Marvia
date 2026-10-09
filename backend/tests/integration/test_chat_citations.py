"""채팅 답 근거 표시([E1]) 연결 테스트 (services/chat/chat.py _with_citations·with_evidence, routers/chat.py, services/chat/conversations.py).

키·DB·LLM 없이 돈다. 순수 함수(parse_and_validate 등)는 test_citations.py가 본다. 여기서는 그 함수가 채팅 흐름에 제대로 걸렸는지만 본다:
읽기 전용 도구 결과 -> 근거 목록 -> LLM에 evidence 글 -> 답의 표시 검사 -> 응답 칸. 값은 모두 가공값이다.
"""
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.routers import chat as chat_router
from backend.app.services.chat import chat as svc
from backend.app.services.chat import conversations as conv
from backend.app.services import llm
from backend.tests.integration.test_chat_agent import MCP_TOOLS, POSITION, QUOTE, _mcp
from backend.tests.integration.test_chat_stream import _events


@pytest.fixture(autouse=True)
def agent_path(monkeypatch):
    monkeypatch.setenv("CHAT_AGENT", "on")
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)


def _fake(monkeypatch, replies, script=(("get_live_position", {"mmsi": 440999001}),)):
    """가짜 llm.chat_agent. evidence 칸을 받는 진짜 시그니처와 같게 **kw로 받아 모은다. replies를 호출 순서대로 답한다."""
    calls = []

    def fake(masked, refs, has_cargo, today, history, tools, run, *, model=None, feedback=None, **kw):
        call = {"history": history, "feedback": feedback, "kw": kw, "tool_results": []}
        calls.append(call)
        for name, args in (script if tools else ()):
            call["tool_results"].append(run(name, args))
        reply = replies[min(len(calls) - 1, len(replies) - 1)]
        out = reply if isinstance(reply, llm.ChatAgentOutput) else llm.ChatAgentOutput(reply=reply, answer_kind="tool")
        return llm.LLMAnswer(output=out, llm=None, prompt_version="test", tool_calls=[])
    monkeypatch.setattr(llm, "chat_agent", fake)
    return calls


def _handle(monkeypatch, replies, **kw):
    calls = _fake(monkeypatch, replies, **kw)
    _, run_tool = _mcp(monkeypatch)
    r = svc.handle("그 배 지금 어디야", "s1", None, lambda req: None, run_tool=run_tool)
    return r, calls


def test_valid_mark_returns_citation_and_tool_result_carries_evidence(monkeypatch):
    r, calls = _handle(monkeypatch, ["지금 속력은 12.3노트예요 [E1]."])
    assert r.reply == "지금 속력은 12.3노트예요[E1]."
    assert len(r.citations) == 1 and r.citations[0]["evidence_ref"] == "E1"
    c = r.citations[0]
    assert r.reply[c["start"]:c["end"]] == "[E1]"
    item = r.evidence_items[0]
    assert item["id"] == "E1" and item["source"] == "shipfinder" and {"field": "sog", "value": "12.3"} in item["values"]
    # LLM에는 도구 결과 안에 evidence 글(줄마다 [E1])이 갔다
    assert "[E1] source=shipfinder" in calls[0]["tool_results"][0]["evidence"]


def test_unknown_id_and_wrong_number_marks_are_stripped(monkeypatch):
    r, _ = _handle(monkeypatch, ["지금 속력은 12.3노트예요 [E9]."])
    assert r.reply == "지금 속력은 12.3노트예요." and r.citations == [] and r.evidence_items  # 없는 id는 지운다. 근거 목록은 그대로
    # 근거에 없는 숫자(73.77)는 답 검사(V7)가 먼저 걸러 코드가 결과를 그대로 전한다. 표시는 남지 않는다
    r, _ = _handle(monkeypatch, ["지금 속력은 73.77노트예요 [E1]."])
    assert "[E1]" not in r.reply and r.citations == []


def test_marks_are_ignored_by_answer_checks(monkeypatch):
    # "[E1]"의 숫자 1이 V7(근거에 없는 숫자)에 걸리면 안 된다: 검사는 표시를 걷어 낸 글로 돈다
    calls = _fake(monkeypatch, ["지금 속력은 12.3노트예요 [E1]."])
    _, run_tool = _mcp(monkeypatch)
    svc.handle("그 배 지금 어디야", "s1", None, lambda req: None, run_tool=run_tool)
    assert len(calls) == 1  # 다시 묻지 않았다


def test_fallback_has_evidence_items_but_no_citations(monkeypatch):
    # 답이 검사에 끝내 걸리면 코드가 결과를 그대로 전한다 (lookup_fallback). 코드 문장이라 표시는 없고 근거 목록은 있다
    r, calls = _handle(monkeypatch, ["지금 속력은 73.77노트예요 [E1]."])
    assert len(calls) == 2 and "12.3노트" in r.reply and r.citations == []
    assert r.evidence_items and r.evidence_items[0]["source"] == "shipfinder"
    assert calls[1]["kw"]["evidence"].startswith("[E1]")  # 다시 묻는 호출은 근거 글을 입력 자료로 다시 받는다


def test_no_evidence_keeps_old_behaviour_and_strips_marks(monkeypatch):
    # 도구를 안 불렀으면 근거가 없다. 문장 속 표시는 지워지고 응답 칸은 비어 있다. LLM 입력에는 evidence 칸이 안 생긴다
    out = llm.ChatAgentOutput(reply="포워더 도착 통지서의 배 이름과 항차로 확인해 주세요 [E1].", answer_kind="skill", skill_quote=QUOTE)
    calls = _fake(monkeypatch, [out], script=())
    r = svc.handle("없을 때는 어떻게 해?", "s1", None, lambda req: None)
    assert r.reply == "포워더 도착 통지서의 배 이름과 항차로 확인해 주세요." and r.citations == [] and r.evidence_items == []
    assert "evidence" not in calls[0]["kw"]


def test_history_marks_are_stripped_before_llm(monkeypatch):
    calls = _fake(monkeypatch, [""], script=())
    history = [{"role": "user", "text": "배 속력 알려줘"}, {"role": "assistant", "text": "지금 속력은 12.3노트예요[E1]. 또 궁금한가요?"}]
    svc.handle("그럼 목적지는?", "s1", None, lambda req: None, history=history)
    texts = [t["text"] for t in calls[0]["history"]]
    assert texts == ["배 속력 알려줘", "지금 속력은 12.3노트예요. 또 궁금한가요?"]


def test_cargo_answer_gets_evidence_items_without_citations(monkeypatch):
    from backend.app.routers.agent import _response
    from backend.app.schemas.agent import Evidence
    from datetime import datetime, timezone
    card = Evidence(source="mof", field="planned_arrival", value="2026-10-12 09:00", fetched_at=datetime(2026, 10, 8, tzinfo=timezone.utc))
    calls = _fake(monkeypatch, [""], script=(("check_cargo", {"bl_ref": "[BL1]"}),))
    r = svc.handle("TESTBL01 괜찮아?", "s1", None, lambda req: _response(status="ok", answer="괜찮아요", evidence=[card]))
    assert r.reply.startswith("괜찮아요") and r.citations == []
    assert r.evidence_items[0]["source"] == "mof"
    assert "evidence" not in calls[0]["tool_results"][0]  # 코드가 쓰는 답이라 UNI-PASS 값이 든 근거를 LLM에 더 주지 않는다


# ── 라우터·스트림·저장 ──

def test_chat_response_and_stream_result_carry_fields(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    items = [{"id": "E1", "source": "shipfinder", "fetched_at": "2026-10-08T00:00:00+00:00", "values": [{"field": "sog", "value": "12.3"}]}]
    cites = [{"id": "C1", "start": 12, "end": 16, "evidence_ref": "E1"}]

    def fake_handle(message, session_id, context, run_agent, user_id=None, history=None, run_tool=None, watch=None, kakao=None, on_screen=None):
        return svc.ChatResult(kind="message", reply="지금 속력은 12.3노트예요[E1].", evidence_items=items, citations=cites)
    monkeypatch.setattr(svc, "handle", fake_handle)
    body = {"message": "속력", "session_id": "s1"}
    with TestClient(app) as client:
        plain = client.post("/api/chat", json=body).json()
        events = _events(client.post("/api/chat/stream", json=body).text)
    assert plain["evidence_items"] == items and plain["citations"] == cites
    assert events[-1] == ("result", plain)  # 스트림 마지막(result) 이벤트도 같은 두 칸을 싣는다


def test_old_response_without_fields_defaults_to_empty(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setattr(svc, "handle", lambda *a, **k: svc.ChatResult(kind="message", reply="안녕"))
    with TestClient(app) as client:
        data = client.post("/api/chat", json={"message": "안녕", "session_id": "s1"}).json()
    assert data["evidence_items"] == [] and data["citations"] == []


def test_conversation_extra_keeps_evidence_fields():
    reply = {"kind": "message", "reply": "지금 속력은 12.3노트예요[E1].",
             "evidence_items": [{"id": "E1", "source": "shipfinder", "values": []}],
             "citations": [{"id": "C1", "start": 12, "end": 16, "evidence_ref": "E1"}]}
    extra = conv._extra_of(reply)  # 잠긴 JSON 칸(extra_enc)에 들어가는 값. 새 칼럼이 필요 없다
    assert extra["evidence_items"] == reply["evidence_items"] and extra["citations"] == reply["citations"]
