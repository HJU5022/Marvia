"""배 지켜보기·웹 답·지도 점선 테스트 (10-08 정운 실사용 79, services/chat/chat.py watch_vessel·is_action_request, validate.is_mostly_foreign).

LLM·DB·ShipFinder는 부르지 않는다. llm.chat_agent를 가짜로 끼우고 배 저장소는 가짜 VesselHooks로 둔다. 배 이름·호출부호·MMSI는 모의값이다.
"""
import pytest

from backend.app.services.chat import chat as svc
from backend.app.services import llm
from backend.app.services.judge import validate
from backend.tests.test_chat_agent import QUOTE, _agent, _out, agent_path, web_off  # noqa: F401 (fixture)
from backend.tests.test_chat_tiers import WEB_ARGS, WEB_QUOTE  # noqa: F401
from backend.app.services.chat import models as chat_models

USER = "user-1"
ON_SCREEN = {"arrivals": [{"ship_name": "TEST STAR", "flag": "Panama", "eta": "2026-10-09T03:00:00", "call_sign": "TST01"},
                          {"ship_name": "TEST MOON", "flag": "Liberia", "call_sign": "TST02", "selected": True}]}
ENGLISH = "You can find the bill of lading number on the shipping documents or on the arrival notice from the forwarder."
EN_QUOTE = "find the bill of lading number on the shipping documents"
KO_ANSWER = "선하증권 번호는 선적 서류나 포워더가 보낸 도착 통지서에서 확인할 수 있어요."


# ── S1 영어 웹 글로 낸 한국어 답 ──

def test_is_mostly_foreign():
    assert validate.is_mostly_foreign(ENGLISH) and not validate.is_mostly_foreign(KO_ANSWER) and not validate.is_mostly_foreign("")


def test_english_quote_supports_korean_answer_only_on_web_path():
    ok = validate.check_chat_reply("선하증권 번호는 도착 통지서에서 확인해요.", "선하증권 번호는 도착 통지서에서 확인해요. " + ENGLISH, "번호 어디서 찾아?",
                                   None, EN_QUOTE, ENGLISH, skip_support_if_foreign=True)
    assert not [v for v in ok if v.rule == "V14"]
    strict = validate.check_chat_reply("선하증권 번호는 도착 통지서에서 확인해요.", "선하증권 번호는 도착 통지서에서 확인해요. " + ENGLISH, "번호 어디서 찾아?",
                                       None, EN_QUOTE, ENGLISH)
    assert [v for v in strict if v.rule == "V14"]  # 영어 원문에 한글 낱말이 없으니 기본 검사는 걸린다 (Skill 경로는 그대로)


def test_english_quote_still_must_appear_in_text():
    found = validate.check_chat_reply("선하증권 번호는 도착 통지서에서 확인해요.", "선하증권 번호는 도착 통지서에서 확인해요. " + ENGLISH, "번호 어디서 찾아?",
                                      None, "this sentence is not in the fetched text at all", ENGLISH, skip_support_if_foreign=True)
    assert [v for v in found if v.rule == "V14"]


def test_korean_skill_source_with_unrelated_answer_still_fails():
    skill = "포워더 도착 통지서의 배 이름과 항차로 확인해 주세요. 입항 예정일도 같이 알려 달라고 합니다."
    found = validate.check_chat_reply("컨테이너 반출은 터미널 예약 후 가능해요 운임 정산 마감 이후입니다.", skill, "질문", None,
                                      "포워더 도착 통지서의 배 이름과 항차로 확인해 주세요", skill, skip_support_if_foreign=True)
    assert [v for v in found if v.rule == "V14"]


def test_english_web_answer_is_shown_with_source(monkeypatch):
    monkeypatch.setattr(llm, "web_search", lambda q: [{"title": "BL guide", "url": "https://a.example.test/bl", "text": ENGLISH}])
    monkeypatch.delenv("WEB_SEARCH", raising=False)
    _agent(monkeypatch, [("web_search", WEB_ARGS)], [(KO_ANSWER, "web", EN_QUOTE)])
    r = svc.handle("선하증권 번호 어디서 찾아?", "s1", None, lambda req: None)
    assert r.reply.startswith(KO_ANSWER) and "웹 참고: [BL guide](" in r.reply and r.reply != svc.NOT_IN_SKILLS


# ── S2 요청 문장에는 웹 검색을 시키지 않는다 ──

@pytest.mark.parametrize("msg,expected", [("지금 지도에 보이는 배 추적현황에 넣어줘", True), ("이 배 감시 켜 줘", True), ("알림 꺼 줘", True),
                                          ("B/L 번호는 어디에 넣어요?", False), ("하우스 b/l은 누가 만들어?", False),
                                          ("B/L 어디서 찾는지 알려줘", False)])
def test_is_action_request(msg, expected):
    assert svc.is_action_request(msg) is expected


def test_action_request_gets_no_web_nudge(monkeypatch):
    searched = []
    monkeypatch.setattr(llm, "web_search", lambda q: searched.append(q) or [])
    monkeypatch.delenv("WEB_SEARCH", raising=False)
    calls = _agent(monkeypatch, [], [("", "not_in_skills", "")])
    r = svc.handle("지금 지도에 보이는 배 추적현황에 넣어줘", "s1", None, lambda req: None)
    assert len(calls) == 1 and searched == [] and r.reply == svc.NOT_IN_SKILLS


def test_web_hint_is_about_current_message():
    assert "CURRENT message" in svc.WEB_HINT and "Never search for an earlier question" in svc.WEB_HINT
    assert "use history to see what the message refers to" not in svc.WEB_HINT


# ── S3 배 지켜보기 ──

class Vessels:
    def __init__(self, resolve=None, add_error=None):
        self.added, self.removed, self.resolved = [], [], []
        self._resolve, self._add_error = resolve or (lambda sign, name: {"mmsi": 440999002}), add_error

    def hooks(self):
        def add(mmsi, name, flag, dest, eta, call_sign):
            self.added.append((mmsi, name, flag, eta, call_sign))
            return {"error": self._add_error} if self._add_error else {"mmsi": mmsi}

        def resolve(sign, name):
            self.resolved.append((sign, name))
            return self._resolve(sign, name)
        return svc.WatchHooks(tool=lambda bl, on: {"on": on}, state=lambda bl: {"watch": False}, worry=lambda bl: None,
                              vessel=chat_models.VesselHooks(resolve=resolve, add=add, remove=lambda m: self.removed.append(m) or {"mmsi": m}))


def _vessel_llm(monkeypatch, args, tools=None):
    monkeypatch.setattr(svc.mcp_client, "read_only_tools", lambda: tools or [])
    seen = []

    def fake(masked, refs, has_cargo, today, history, tool_list, run, *, model=None, feedback=None, **extra):
        seen.append(run("watch_vessel", args))
        return llm.LLMAnswer(output=llm.ChatAgentOutput(reply="", answer_kind="tool", skill_quote=""), llm=None, prompt_version="test", tool_calls=[])
    monkeypatch.setattr(llm, "chat_agent", fake)
    return seen


def _say(msg, store, on_screen=ON_SCREEN, user=USER, run_tool=None):
    return svc.handle(msg, "s1", None, lambda req: None, user_id=user, watch=store.hooks() if store else None, on_screen=on_screen, run_tool=run_tool)


def test_selected_arrival_is_watched_by_call_sign(monkeypatch, agent_path, web_off):  # noqa: F811
    _vessel_llm(monkeypatch, {"on": True, "ship_name": None})
    store = Vessels()
    r = _say("지금 지도에 보이는 배 추적현황에 넣어줘", store)
    assert store.resolved == [("TST02", "TEST MOON")] and store.added[0][:2] == (440999002, "TEST MOON")
    assert r.reply == svc.VESSEL_ON_REPLY.format(name="TEST MOON") + "\n" + svc.WATCH_PAGE_LINE
    assert r.watch_vessel_set == {"mmsi": 440999002, "name": "TEST MOON", "on": True} and r.watch_set is None


def test_turning_off_removes_vessel(monkeypatch, agent_path, web_off):  # noqa: F811
    _vessel_llm(monkeypatch, {"on": False, "ship_name": None})
    store = Vessels()
    r = _say("이 배 그만 지켜봐 줘", store)
    assert store.removed == [440999002] and r.reply == svc.VESSEL_OFF_REPLY.format(name="TEST MOON")


def test_single_ship_on_screen_is_used_without_selection(monkeypatch, agent_path, web_off):  # noqa: F811
    _vessel_llm(monkeypatch, {"on": True, "ship_name": None})
    store = Vessels()
    _say("이 배 지켜봐 줘", store, {"arrivals": [{"ship_name": "TEST STAR", "call_sign": "TST01"}]})
    assert store.added[0][1] == "TEST STAR"


def test_cargo_vessel_with_mmsi_skips_resolve(monkeypatch, agent_path, web_off):  # noqa: F811
    _vessel_llm(monkeypatch, {"on": True, "ship_name": None})
    store = Vessels()
    _say("이 배 지켜봐 줘", store, {"vessel": {"ship_name": "TEST SUN", "mmsi": 440999001}})
    assert store.resolved == [] and store.added[0][0] == 440999001


def test_unclear_ship_asks_which_one(monkeypatch, agent_path, web_off):  # noqa: F811
    _vessel_llm(monkeypatch, {"on": True, "ship_name": None})
    store = Vessels()
    two = {"arrivals": [{"ship_name": "A ONE", "call_sign": "A1"}, {"ship_name": "B TWO", "call_sign": "B2"}]}
    r = _say("이 배 지켜봐 줘", store, two)
    assert r.reply == svc.VESSEL_ASK_WHICH == "어느 배를 넣을까요? 배 이름을 알려 주세요." and store.added == []
    assert _say("이 배 지켜봐 줘", store, None).reply == svc.VESSEL_ASK_WHICH


def test_typed_name_matches_screen_row_but_invented_name_is_refused(monkeypatch, agent_path, web_off):  # noqa: F811
    _vessel_llm(monkeypatch, {"on": True, "ship_name": "test star"})
    store = Vessels()
    _say("test star 지켜봐 줘", store)
    assert store.resolved == [("TST01", "TEST STAR")]
    _vessel_llm(monkeypatch, {"on": True, "ship_name": "INVENTED ONE"})
    store2 = Vessels()
    assert _say("지켜봐 줘", store2).reply == svc.VESSEL_ASK_WHICH and store2.added == []


def test_typed_name_uses_candidates_and_requires_one_pick(monkeypatch, agent_path, web_off):  # noqa: F811
    tools = [{"type": "function", "function": {"name": "get_vessel_candidates", "description": "d", "parameters": {"type": "object", "properties": {}}}}]
    _vessel_llm(monkeypatch, {"on": True, "ship_name": "OTHER SHIP"}, tools)
    one = {"candidates": [{"mmsi": 1234, "name": "OTHER SHIP", "flag": "Korea", "call_sign": "X1", "dest": "BUSAN"}]}
    store = Vessels()
    r = _say("OTHER SHIP 지켜봐 줘", store, None, run_tool=lambda n, a: one)
    assert store.added[0][:2] == (1234, "OTHER SHIP") and r.watch_vessel_set["mmsi"] == 1234
    two = {"candidates": [{"mmsi": 1, "name": "OTHER SHIP"}, {"mmsi": 2, "name": "OTHER SHIP"}]}
    store2 = Vessels()
    assert _say("OTHER SHIP 지켜봐 줘", store2, None, run_tool=lambda n, a: two).reply == svc.VESSEL_MANY and store2.added == []


def test_not_logged_in_and_no_watch_words_change_nothing(monkeypatch, agent_path, web_off):  # noqa: F811
    _vessel_llm(monkeypatch, {"on": True, "ship_name": None})
    store = Vessels()
    assert _say("이 배 지켜봐 줘", store, user=None).reply == svc.VESSEL_NEED_LOGIN and store.added == []
    seen = _vessel_llm(monkeypatch, {"on": True, "ship_name": None})
    r = _say("이 배 어디야?", store)
    assert store.added == [] and seen[0]["error"]["code"] == "not_requested" and r.watch_vessel_set is None


def test_errors_use_router_messages(monkeypatch, agent_path, web_off):  # noqa: F811
    from backend.app.routers import watch as watch_router
    _vessel_llm(monkeypatch, {"on": True, "ship_name": None})
    assert _say("이 배 지켜봐 줘", Vessels(add_error="limit")).reply == watch_router._VESSEL_ERRORS["limit"][1]
    unknown = Vessels(resolve=lambda s, n: {"error": "unknown_vessel"})
    assert _say("이 배 지켜봐 줘", unknown).reply == watch_router._VESSEL_ERRORS["unknown_vessel"][1]


def test_screen_passes_call_sign_and_selected():
    out = svc._masked_screen(ON_SCREEN)
    assert out["arrivals"][1]["call_sign"] == "TST02" and out["arrivals"][1]["selected"] is True and "selected" not in out["arrivals"][0]


def test_request_schema_accepts_call_sign_and_selected():
    from backend.app.routers.chat import ChatScreenArrival
    row = ChatScreenArrival(ship_name="TEST STAR", call_sign="TST01", selected=True)
    assert row.model_dump()["selected"] is True and ChatScreenArrival(ship_name="X").selected is False


# ── C1·C2 ──

def test_dashed_line_question_is_answered_from_skill(monkeypatch, web_off):  # noqa: F811
    quote = "선박 지도에서 고른 배에 붙는 점선은 그 배의 마지막 위치에서 부산항까지 남은 예상 바닷길이다"
    _agent(monkeypatch, [], [("점선은 고른 배의 마지막 위치에서 부산항까지 남은 예상 바닷길이에요. 지나온 길은 아니에요.", "skill", quote)])
    r = svc.handle("지도에 점선은 뭐야?", "s1", None, lambda req: None)
    assert "예상 바닷길" in r.reply and r.reply != svc.NOT_IN_SKILLS


def test_usage_guide_mentions_ship_watch():
    assert "이 배 지켜봐 줘" in svc.USAGE_GUIDE and "감시 화물" in svc.USAGE_GUIDE
