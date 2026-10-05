"""채팅 에이전트 버그 두 개 (10-05 버그 찾기, services/chat.py _agent).
1) 한 문장에 B/L이 여러 개: 조회는 하나만 가고, 답 끝에 코드가 쓴 안내가 붙는다 (번호는 적지 않는다).
2) 화물 답과 LLM 문장이 같은 문장을 되풀이하면 LLM 문장을 버린다.
LLM·MCP는 test_chat_agent.py의 가짜를 그대로 쓴다."""
import pytest

from backend.app.routers.agent import _response
from backend.app.services import chat as svc
from backend.tests.test_chat import _agent_calls
from backend.tests.test_chat_agent import _agent, _mcp

CHECK = [("check_cargo", {"bl_ref": "[BL1]", "bl_type": "MASTER"})]


@pytest.mark.parametrize("msg", ["testbl01 그리고 testbl04 판매예정일 2026-09-28",
                                 "TESTBL01과 TESTBL02 중에 어느 것이 더 빨리 도착할까?"])
def test_two_bls_look_up_one_and_reply_has_notice(monkeypatch, msg):
    calls = _agent(monkeypatch, CHECK + [("check_cargo", {"bl_ref": "[BL2]", "bl_type": "MASTER"})])
    agent, run = _agent_calls()
    r = svc.handle(msg, "s1", None, run)
    assert len(agent) == 1  # 화물 조회는 한 번만
    assert r.reply.endswith(svc.MULTI_BL_NOTICE) and r.reply.startswith("괜찮습니다")
    assert "TESTBL" not in r.reply.upper() and "TESTBL" not in str(calls).upper()  # 원문 B/L은 어디에도 없다


def test_one_bl_or_same_bl_twice_has_no_notice(monkeypatch):
    _agent(monkeypatch, CHECK)
    _, run = _agent_calls()
    assert svc.MULTI_BL_NOTICE not in svc.handle("testbl01 testbl01 괜찮아?", "s1", None, run).reply
    assert svc.MULTI_BL_NOTICE not in svc.handle("testbl01 괜찮아?", "s1", None, run).reply


def test_llm_sentence_repeating_cargo_reply_is_dropped(monkeypatch):
    ask = "같은 이름의 배가 여러 척입니다. 항차 번호나 입항 예정일로 가릅니다."
    script = CHECK + [("get_live_position", {"mmsi": 440999001})]
    _, run_tool = _mcp(monkeypatch)
    run = lambda req: _response(status="ok", answer=ask)
    _agent(monkeypatch, script, [ask])
    r = svc.handle("TESTBL04 판매예정일 2026-09-28", "s1", None, run, run_tool=run_tool)
    assert r.reply.count("같은 이름의 배가 여러 척입니다") == 1


def test_repeats_reply_ignores_spacing_and_short_overlap():
    assert svc._repeats_reply("같은 이름의  배가 여러 척입니다.", ["같은 이름의 배가\n여러 척입니다. 확인하세요"])
    assert not svc._repeats_reply("지금 속력은 12.3노트입니다.", ["괜찮습니다"])
    assert not svc._repeats_reply("괜찮습니다.", ["괜찮습니다"])  # 12자 미만은 우연히 겹칠 수 있다
