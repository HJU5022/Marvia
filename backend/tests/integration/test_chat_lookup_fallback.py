"""채팅 답 버그 수정 테스트 (services/chat/chat.py).

LLM·MCP·해수부·판정 흐름은 부르지 않는다. test_chat_agent.py의 가짜 llm.chat_agent와 MCP 가짜를 그대로 쓴다.
배 이름·B/L은 모두 모의값이다.
  35·52: 읽기 전용 도구 결과를 문장으로 못 옮겼을 때 "정리하지 못했습니다" 막다른 문구 대신 쓸 수 있는 답이 나간다
  34: 입항 선박 검색 답에 건수만이 아니라 배 이름이 든다
  54: 같은 B/L이 연달아 조회 결과 없음이면 같은 문장을 되풀이하지 않는다
"""
from backend.app.routers.agent import NO_CARGO, _response
from backend.app.services.chat import chat as svc
from backend.app.services import llm
from backend.tests.integration.test_chat import PLANS
from backend.tests.integration.test_chat_agent import MCP_TOOLS, _agent, _mcp  # noqa: F401 - 같은 가짜 도구 목록을 쓴다

CANDIDATES = {"candidates": [
    {"mmsi": 636000001, "imo": None, "name": "TEST LIBERIA ONE", "flag": "LR", "dest": "BUSAN", "last_time": None,
     "ship_type": 70, "similarity": 0.9},
    {"mmsi": 636000002, "imo": None, "name": "TEST LIBERIA TWO", "flag": "LR", "dest": "BUSAN", "last_time": None,
     "ship_type": 70, "similarity": 0.8}], "source": "shipfinder", "fetched_at": "2026-10-07T00:00:00+00:00"}
CAND_TOOL = [("get_vessel_candidates", {"ship_name": "TEST"})]


def _mcp_candidates(monkeypatch):
    monkeypatch.setattr(svc.mcp_client, "read_only_tools", lambda: [{"type": "function", "function": {
        "name": "get_vessel_candidates", "description": "ship candidates", "parameters": {"type": "object", "properties": {}}}}])
    monkeypatch.setattr(svc.mcp_client, "call_tool", lambda *a, **k: CANDIDATES, raising=False)
    return lambda name, args: CANDIDATES


def test_35_user_word_in_reply_gets_one_retry_then_good_answer(monkeypatch):
    """사용자가 쓴 낱말(라이베리아)을 옮긴 문장은 V10에 걸린다. 예전에는 바로 막다른 문구였고, 이제는 한 번 고쳐 쓰게 한다."""
    run_tool = _mcp_candidates(monkeypatch)
    calls = _agent(monkeypatch, CAND_TOOL, ["라이베리아에서 오는 배는 TEST LIBERIA ONE이에요.", "TEST LIBERIA ONE과 TEST LIBERIA TWO가 있어요."])
    r = svc.handle("지금 옆에 떠있네 라이베리아에서 오는거", "s1", None, lambda req: None, run_tool=run_tool)
    assert len(calls) == 2 and calls[1]["feedback"].startswith("V10:")
    assert r.reply == "TEST LIBERIA ONE과 TEST LIBERIA TWO가 있어요." and r.reply != svc.LOOKUP_NOT_SUMMARIZED


def test_35_still_failing_returns_tool_results_not_dead_end(monkeypatch):
    run_tool = _mcp_candidates(monkeypatch)
    bad = "라이베리아에서 오는 배는 TEST LIBERIA ONE이에요."
    calls = _agent(monkeypatch, CAND_TOOL, [bad, bad])
    r = svc.handle("지금 옆에 떠있네 라이베리아에서 오는거", "s1", None, lambda req: None, run_tool=run_tool)
    assert len(calls) == 2 and r.reply != svc.LOOKUP_NOT_SUMMARIZED
    assert "TEST LIBERIA ONE" in r.reply and "TEST LIBERIA TWO" in r.reply and "2척" in r.reply


def test_52_repeated_request_does_not_repeat_or_dead_end(monkeypatch):
    """"아니 다시해봐": LLM이 앞 답을 그대로 되풀이(V13)해도 막다른 문구 대신 결과가 나가고, 앞 답과 같은 글도 아니다."""
    run_tool = _mcp_candidates(monkeypatch)
    first = "TEST LIBERIA ONE과 TEST LIBERIA TWO가 있어요."
    history = [{"role": "user", "text": "라이베리아에서 오는거"}, {"role": "assistant", "text": first}]
    calls = _agent(monkeypatch, CAND_TOOL, [first, first])
    r = svc.handle("아니 다시해봐", "s1", None, lambda req: None, history=history, run_tool=run_tool)
    assert len(calls) == 2 and calls[1]["feedback"].startswith("V13:")
    assert r.reply != svc.LOOKUP_NOT_SUMMARIZED and r.reply != first and "TEST LIBERIA ONE" in r.reply


def test_35_llm_error_after_tools_returns_tool_results(monkeypatch):
    run_tool = _mcp_candidates(monkeypatch)
    _agent(monkeypatch, CAND_TOOL, [""], error=llm.LLMError("timeout"))
    r = svc.handle("라이베리아에서 오는거", "s1", None, lambda req: None, run_tool=run_tool)
    assert r.reply != svc.LOOKUP_NOT_SUMMARIZED and "TEST LIBERIA ONE" in r.reply


def test_empty_reply_after_lookup_gets_retry(monkeypatch):
    run_tool = _mcp_candidates(monkeypatch)
    calls = _agent(monkeypatch, CAND_TOOL, ["", "TEST LIBERIA ONE이 있어요."])
    r = svc.handle("TEST 배 찾아줘", "s1", None, lambda req: None, run_tool=run_tool)
    assert len(calls) == 2 and calls[1]["feedback"].startswith("EMPTY:") and r.reply == "TEST LIBERIA ONE이 있어요."


def test_lookup_fallback_per_tool_shapes():
    pos = {"name": "get_live_position", "result": {"lat": 35.123, "lng": 129.045, "sog": 12.34, "dest": "BUSAN", "last_time": "2026-10-07T01:02:03+00:00"}}
    sched = {"name": "get_port_schedule", "result": {"planned_arrival": "2026-10-08T00:00:00+00:00", "actual_arrival": None, "facility": "TEST PIER"}}
    dist = {"name": "estimate_distance", "result": {"distance_nm": 100.04, "calc_hours_at_sog": 8.26}}
    out = svc.lookup_fallback([pos, sched, dist])
    assert "위도 35.12" in out and "12.3노트" in out and "2026-10-07 01:02" in out
    assert "입항 예정 2026-10-08 00:00" in out and "TEST PIER" in out and "약 100.0해리" in out and "8.3시간" in out
    assert svc.lookup_fallback([{"name": "get_live_position", "result": {}}]) is None


# ── 34: 건수만이 아니라 이름 ──

def test_34_arrival_search_names_the_ships(monkeypatch):
    monkeypatch.setattr(svc, "_arrivals", lambda days: PLANS)
    r = svc.search_vessels(None, 7)
    names = [v["ship_name"] for v in r.vessels if v["is_cargo"]] or [v["ship_name"] for v in r.vessels]
    assert r.vessels and names[0] in r.reply
    assert "입니다" not in r.reply and "습니다" not in r.reply
    # 첫 줄은 결론만, 배는 한 척에 한 줄, 마지막은 출처 한 줄
    lines = r.reply.split("\n")
    assert lines[0].endswith("척이에요.") or "수입 화물선은 없고" in lines[0]
    assert lines[-1] == svc.PREV_PORT_NOTE
    ship_lines = [x for x in lines if x.startswith("· ")]
    assert ship_lines and ship_lines[0].startswith(f"· {names[0]} · ") and "도착 예정" in ship_lines[0]


# ── 54: 조회 결과 없음 반복 ──

def _no_result_run(req):
    return _response(status="insufficient", answer=NO_CARGO)


def test_54_second_no_result_is_not_the_same_sentence(monkeypatch):
    _agent(monkeypatch, [("check_cargo", {"bl_ref": "[BL1]", "bl_type": "HOUSE"})])
    first = svc.handle("TESTBL01 조회해줘", "s1", None, _no_result_run)
    assert svc.NO_RESULT_REPLY in first.reply and "습니다" not in first.reply.split("\n")[0]
    history = [{"role": "user", "text": "TESTBL01 조회해줘"}, {"role": "assistant", "text": first.reply}]
    _agent(monkeypatch, [("check_cargo", {"bl_ref": "[BL1]", "bl_type": "HOUSE"})])
    second = svc.handle("TESTBL01 다시 해줄래", "s1", None, _no_result_run, history=history)
    assert svc.NO_RESULT_REPLY not in second.reply and "마스터로 다시" in second.reply  # 하우스로 했으니 마스터를 권한다
    history += [{"role": "user", "text": "다시 해줄래"}, {"role": "assistant", "text": second.reply}]
    _agent(monkeypatch, [("check_cargo", {"bl_ref": "[BL1]", "bl_type": "HOUSE"})])
    third = svc.handle("TESTBL01 또 해줘", "s1", None, _no_result_run, history=history)
    assert third.reply != second.reply and third.reply != first.reply
