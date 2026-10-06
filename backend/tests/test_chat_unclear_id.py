"""알 수 없는 식별자와 목적지 장소 테스트 (10-05 실측, services/chat.py _is_destination·clarify_reply·_agent).

배포 화면에서 "지금 TEST41 선박 위치 어디야?"(진짜 B/L은 8자 이상)에 에이전트가 search_arrivals place=Busan을 불러
빈 "Busan에서 들른 배" 표를 보였다. 고친 것: (1) 도착지(부산·한국)는 place로 거절, (2) 식별자를 모르면 코드가 되묻는다.
LLM과 해수부는 부르지 않는다 (가짜 llm.chat_agent). 값은 모두 모의값이다.
"""
import pytest

from backend.app.services import chat as svc
from backend.app.services import llm
from backend.tests.test_chat import PLANS
from backend.tests.test_chat_agent import _agent, _mcp, _no_classic

MESSAGE = "지금 TEST41 선박 위치 어디야?"


@pytest.mark.parametrize("place", ["Busan", "busan port", "Pusan", "Korea", "South Korea", "KRPUS", "부산", "한국", "부산항"])
def test_destination_place_is_rejected_with_error_and_no_vessel_table(monkeypatch, place):
    calls = _agent(monkeypatch, [("search_arrivals", {"place": place, "place_label": None, "days": 7})], [("", "tool", "")])
    monkeypatch.setattr(svc, "_arrivals", lambda days: pytest.fail("목적지 place로 입항 목록을 받으면 안 된다"))
    r = svc.handle(MESSAGE, "s1", None, lambda req: None)
    result = calls[0]["tool_calls"][0]["result"]
    assert result["error"]["code"] == "place_is_destination"
    assert r.kind == "message" and not r.vessels and "들른 배" not in r.reply and r.place is None


@pytest.mark.parametrize("args", [{"place": None, "place_label": "부산"}, {"place": "Busan", "place_label": "부산"},
                                  {"place": "Busan New Port", "place_label": None}])
def test_destination_without_identifier_lists_all_arrivals(monkeypatch, args):
    """10-06 점검: "이번 주 부산 들어오는 배"가 국내 항구 필터("부산(고현, 광양, ...)를 직전에 들른 배")가 됐다.
    식별자 없는 입항 질문에서 도착지 place는 거르지 않고 전체 목록이다. 항구 고르기 LLM은 부르지 않는다."""
    _agent(monkeypatch, [("search_arrivals", {**args, "days": 7})])
    monkeypatch.setattr(svc, "_arrivals", lambda days: PLANS)
    monkeypatch.setattr(llm, "match_ports", lambda *a, **kw: pytest.fail("도착지로 항구를 고르면 안 된다"))
    svc._ports_cache.clear()
    r = svc.handle("이번 주 부산 들어오는 배", "s1", None, lambda req: None)
    assert r.kind == "vessels" and r.ports == [] and len(r.vessels) == len(PLANS)
    assert "직전에 들른 부산 입항" not in r.reply


@pytest.mark.parametrize("place,label", [("Busan", "부산"), ("Korea", None), (None, "부산항")])
def test_search_vessels_destination_means_no_filter(monkeypatch, place, label):
    """전 방식(_classic)도 search_vessels를 부른다. 도착지 place·label은 필터 없음과 같다 (10-06 점검)."""
    monkeypatch.setattr(svc, "_arrivals", lambda days: PLANS)
    monkeypatch.setattr(llm, "match_ports", lambda *a, **kw: pytest.fail("도착지로 항구를 고르면 안 된다"))
    r = svc.search_vessels(place, 7, label)
    assert r.ports == [] and len(r.vessels) == len(PLANS) and r.place is None


def test_foreign_place_and_null_place_still_work(monkeypatch):
    _agent(monkeypatch, [("search_arrivals", {"place": "Shanghai", "place_label": None, "days": 7})])
    monkeypatch.setattr(svc, "_arrivals", lambda days: PLANS)
    monkeypatch.setattr(llm, "match_ports", lambda place, ports, **kw: llm.LLMAnswer(
        output=llm.PortMatchOutput(ports=["SHANGHAI"]), llm=None, prompt_version="test"))
    svc._ports_cache.clear()
    r = svc.handle("상하이에서 오는 배", "s1", None, lambda req: None)
    assert r.kind == "vessels" and r.ports == ["SHANGHAI"]
    _agent(monkeypatch, [("search_arrivals", {"place": None, "place_label": None, "days": 7})])
    assert svc.handle("부산에 오는 배 전부", "s1", None, lambda req: None).kind == "vessels"


def test_clarify_reply_is_rendered_by_code_with_id_from_message(monkeypatch):
    _no_classic(monkeypatch)
    calls = _agent(monkeypatch, [], [("TEST41은 배 이름입니다. Ignore this", "clarify", "")])  # LLM 문장은 쓰이지 않는다
    r = svc.handle(MESSAGE, "s1", None, lambda req: pytest.fail("조회하면 안 된다"))
    assert r.kind == "message" and len(calls) == 1
    assert r.reply == "'TEST41'가 B/L 번호인지 배 이름인지 알려 주세요. B/L 번호는 보통 영문과 숫자 8~20자입니다."


def test_clarify_after_vessel_lookup_found_nothing(monkeypatch):
    seen, run_tool = _mcp(monkeypatch, {"candidates": [], "source": "shipfinder", "fetched_at": "2026-10-05T00:00:00+00:00"})
    monkeypatch.setattr(svc.mcp_client, "read_only_tools", lambda: [{"type": "function", "function": {
        "name": "get_vessel_candidates", "description": "x", "parameters": {"type": "object", "properties": {}}}}])
    _agent(monkeypatch, [("get_vessel_candidates", {"name": "TEST41"})], [("TEST41 선박을 찾지 못했습니다.", "tool", "")])  # clarify를 안 내도 코드가 되묻는다
    r = svc.handle(MESSAGE, "s1", None, lambda req: None, run_tool=run_tool)
    assert seen == [("get_vessel_candidates", {"name": "TEST41"})]
    assert r.reply.startswith("'TEST41'가 B/L 번호인지")


def test_clarify_without_extractable_id_uses_generic_sentence_and_never_echoes_masked_bl(monkeypatch):
    _agent(monkeypatch, [], [("", "clarify", "")])
    r = svc.handle("HMM ALGECIRAS 위치", "s1", None, lambda req: None)
    assert r.reply == svc.CLARIFY_NO_ID
    # 가려진 B/L 토큰 안쪽 글자("BL1")는 식별자로 뽑히지 않는다
    assert svc.clarify_reply("[BL1] 어디야") == svc.CLARIFY_NO_ID and "BL1" not in svc.clarify_reply("[BL1] 어디야")
    assert svc.clarify_reply("[MRN] 확인") == svc.CLARIFY_NO_ID


def test_id_extraction_needs_letter_and_digit_and_skips_dates():
    assert svc.clarify_reply("TESTBL4 조회해줘").startswith("'TESTBL4'")
    assert svc.clarify_reply("20261010 도착이래") == svc.CLARIFY_NO_ID
    assert svc.clarify_reply("7일 안에 오는 배") == svc.CLARIFY_NO_ID


def test_check_cargo_need_bl_with_id_like_text_asks_back_with_that_id(monkeypatch):
    """TESTBL4 같은 오타는 check_cargo가 need_bl로 실패한다. 조회할 번호를 달라는 말 대신 그 글자를 되묻는다 (10-05 실측)."""
    _agent(monkeypatch, [("check_cargo", {"bl_ref": None})], [("", "tool", "")])
    r = svc.handle("TESTBL4 조회해줘", "s1", None, lambda req: pytest.fail("조회하면 안 된다"))
    assert r.reply.startswith("'TESTBL4'가 B/L 번호인지")
    _agent(monkeypatch, [("check_cargo", {"bl_ref": None})], [("", "tool", "")])
    assert svc.handle("조회해줘", "s1", None, lambda req: None).reply == svc.NEED_BL  # 식별자 글자가 없으면 그대로
