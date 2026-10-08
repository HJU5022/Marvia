"""실험 A4: 화면 화물의 "이 배"를 위치·거리 도구로 따로 찾지 않고 ask_cargo로 돌려 보낸다 (services/chat/chat.py _run_tool, 항상 켜짐).

화면에 화물이 있고(context) 화면의 배(on_screen.vessel)와 같은 MMSI로 get_live_position을 부르면, 그 호출은 ask_cargo가 대신 답한다.
다른 배(이 배 말고 SAMPLE PINE)나 화물이 없는 화면은 건드리지 않는다. LLM·MCP는 부르지 않는다 (가짜).
"""
import pytest

from backend.app.routers.agent import _response
from backend.app.schemas.agent import AgentRequest
from backend.app.services.chat import chat as svc
from backend.app.services import llm
from backend.tests.integration.test_chat_agent import _mcp, _out, agent_path  # noqa: F401 (fixture)

CONTEXT = AgentRequest(bl_no="TESTBL01", bl_type="HOUSE", session_id="s1")
SCREEN = {"vessel": {"ship_name": "SAMPLE ORCHID", "flag": "LR", "mmsi": 440999001, "lat": 34.2, "lng": 128.9, "destination": "BUSAN"}}
TOOLS = [{"type": "function", "function": {"name": n, "description": "x", "parameters": {"type": "object", "properties": {}}}}
         for n in ("get_live_position", "estimate_distance")]


def _fake(monkeypatch, script):
    """on_screen을 받는 가짜 chat_agent. script의 도구를 부르고 결과를 모은다."""
    done = []

    def fake(masked, refs, has_cargo, today, history, tools, run, *, model=None, feedback=None, **extra):
        calls = [{"name": n, "arguments": a, "result": run(n, a)} for n, a in script]
        done.extend(calls)
        return llm.LLMAnswer(output=_out(("", "tool", "")), llm=None, prompt_version="test", tool_calls=calls)
    monkeypatch.setattr(llm, "chat_agent", fake)
    return done


def _run(monkeypatch, script, context=CONTEXT, screen=SCREEN):
    seen, run_tool = _mcp(monkeypatch, {"mmsi": 440999001, "lat": 34.9, "lng": 129.3, "source": "shipfinder", "fetched_at": "2026-10-08T00:00:00+00:00"})
    monkeypatch.setattr(svc.mcp_client, "read_only_tools", lambda: TOOLS)  # _mcp가 끼운 목록을 위치·거리 둘이 있는 목록으로 바꾼다
    asked = []
    done = _fake(monkeypatch, script)

    def run_agent(req):
        asked.append(req.follow_up_question)
        return _response(status="ok", answer="배는 부산 앞바다에 있어요.")
    r = svc.handle("이 배 어디야?", "s1", context, run_agent, run_tool=run_tool, on_screen=screen)
    return r, seen, asked, done


def test_own_vessel_position_call_is_rerouted_to_ask_cargo(monkeypatch, agent_path):  # noqa: F811
    r, seen, asked, done = _run(monkeypatch, [("get_live_position", {"mmsi": 440999001}),
                                              ("estimate_distance", {"lat": 34.9, "lng": 129.3, "sog": 12.4})])
    assert seen == [] and len(asked) == 1  # 위치·거리 도구는 실행하지 않았고 화물 질문이 한 번 돌았다
    assert done[0]["result"]["rerouted_to"] == "ask_cargo" and done[1]["result"]["rerouted_to"] == "ask_cargo"
    assert r.kind == "cargo" and "부산 앞바다" in r.reply


def test_other_vessel_is_not_rerouted(monkeypatch, agent_path):  # noqa: F811
    _, seen, asked, _ = _run(monkeypatch, [("get_live_position", {"mmsi": 440999004})])
    assert seen == [("get_live_position", {"mmsi": 440999004})] and asked == []


def test_no_cargo_on_screen_is_not_rerouted(monkeypatch, agent_path):  # noqa: F811
    _, seen, asked, _ = _run(monkeypatch, [("get_live_position", {"mmsi": 440999001})], context=None)
    assert seen == [("get_live_position", {"mmsi": 440999001})] and asked == []
