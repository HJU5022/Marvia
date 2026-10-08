"""대화로 지켜보기 + 먼저 제안 테스트 (services/chat/chat.py WatchHooks·_with_offer·run_watch, routers/chat.py 계약).

LLM·DB·판정 흐름은 부르지 않는다. llm.chat_agent를 가짜로 끼워 도구를 대본대로 부르게 하고, 지켜보기 저장소는 가짜 WatchHooks로 둔다.
B/L은 모의값이다.
"""
import pytest

from backend.app.routers import chat as chat_router
from backend.app.routers.agent import _response
from backend.app.schemas.agent import AgentRequest
from backend.app.services.chat import chat as svc
from backend.app.services import llm
from backend.app.services.watch.watch import WatchError
from backend.app.services.chat import texts as chat_texts

USER = "user-1"
BL = "TESTBL01"


@pytest.fixture(autouse=True)
def agent_path(monkeypatch):
    monkeypatch.setenv("CHAT_AGENT", "on")
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.setattr(svc.mcp_client, "read_only_tools", lambda: [])


def _llm(monkeypatch, script=(), cue=False):
    """가짜 llm.chat_agent. script의 (도구, 인자)를 run에 넘기고 도구를 쓴 답(reply 비어 있음)을 낸다. 받은 도구 결과는 results에 모은다."""
    results = []

    def fake(masked, refs, has_cargo, today, history, tools, run, *, model=None, feedback=None, evidence=None):
        calls = []
        if tools:
            for name, args in script:
                result = run(name, args)
                results.append((name, result))
                calls.append({"name": name, "arguments": args, "result": result})
        out = llm.ChatAgentOutput(reply="", answer_kind="tool", skill_quote="", watch_cue=cue)
        return llm.LLMAnswer(output=out, llm=None, prompt_version="test", tool_calls=calls)
    monkeypatch.setattr(llm, "chat_agent", fake)
    return results


def _run(verdict="watch", margin=2):
    """가짜 판정 흐름. 조회와 후속 질문 모두 같은 응답을 준다."""
    def run(req):
        return _response(status="ok", verdict=verdict, days_margin=margin, answer="조회 결과 답입니다.")
    return run


class Hooks:
    """가짜 지켜보기 저장소. watching: 이미 지켜보는 중인가, fail: tool이 낼 오류 종류."""

    def __init__(self, watching=False, fail=None, worry=None):
        self.watching, self.fail, self.worry_text = watching, fail, worry
        self.tool_calls = []

    def hooks(self):
        def tool(bl, on):
            self.tool_calls.append((bl, on))
            if self.fail:
                return {"error": self.fail}
            self.watching = on
            return {"on": on}
        return svc.WatchHooks(tool=tool, state=lambda bl: {"saved": True, "watch": self.watching}, worry=lambda bl: self.worry_text)


CONTEXT = AgentRequest(bl_no=BL, bl_type="HOUSE", session_id="s1")
ASK = [("ask_cargo", {"question": "지금 어디쯤이야?"})]
WATCH_ON = [("set_watch", {"on": True})]
OFFER_TURN = {"role": "assistant", "text": "조회 결과 답입니다.\n\n판매 예정일까지 여유가 2일이고 '주의' 판정이에요. " + chat_texts.WATCH_ASK}


def _handle(message, *, user_id=USER, hooks=None, context=CONTEXT, history=None, run=None):
    return svc.handle(message, "s1", context, run or _run(), user_id, history=history or [],
                      watch=hooks.hooks() if hooks else None)


# ── 켜기·끄기 ──

def test_explicit_words_turn_watch_on_with_code_sentence(monkeypatch):
    _llm(monkeypatch, WATCH_ON)
    store = Hooks()
    r = _handle("이거 지켜봐 줘", hooks=store)
    assert store.tool_calls == [(BL, True)]
    assert r.reply == svc.WATCH_ON_REPLY + "\n" + svc.WATCH_PAGE_LINE and r.watch_set == {"bl_no": BL, "on": True} and r.watch_offer is None
    assert "카카오톡을 연결해 두셨다면" in r.reply  # 연결한 사람에게만 간다고 사실대로 쓴다


def test_stop_watching_turns_off(monkeypatch):
    _llm(monkeypatch, [("set_watch", {"on": False})])
    store = Hooks(watching=True)
    r = _handle("그만 지켜봐도 돼", hooks=store)
    assert store.tool_calls == [(BL, False)] and r.reply == svc.WATCH_OFF_REPLY and r.watch_set == {"bl_no": BL, "on": False}


def test_llm_alone_cannot_flip_watch_without_explicit_words(monkeypatch):
    results = _llm(monkeypatch, WATCH_ON)
    store = Hooks()
    r = _handle("지금 어디쯤이야?", hooks=store)
    assert store.tool_calls == [] and r.watch_set is None  # 저장소를 건드리지 않았다
    assert results[0][1]["error"]["code"] == "not_requested"  # LLM에는 오류로 돌아간다
    assert r.reply == svc.WATCH_HOW


@pytest.mark.parametrize("answer", ["응", "네", "그래 부탁해", "ㅇㅇ", "좋아요!", "네 부탁드려요"])
def test_affirmative_after_offer_turns_on_even_if_llm_says_off(monkeypatch, answer):
    _llm(monkeypatch, [("set_watch", {"on": False})])  # 제안에 "응"은 켜기다. LLM이 on 값을 틀려도 코드가 켠다
    store = Hooks()
    r = _handle(answer, hooks=store, history=[{"role": "user", "text": "TESTBL01 괜찮아?"}, OFFER_TURN])
    assert store.tool_calls == [(BL, True)] and r.watch_set == {"bl_no": BL, "on": True}


def test_affirmative_without_a_previous_offer_is_refused(monkeypatch):
    _llm(monkeypatch, WATCH_ON)
    store = Hooks()
    r = _handle("응", hooks=store, history=[{"role": "assistant", "text": "무엇을 도와드릴까요?"}])
    assert store.tool_calls == [] and r.watch_set is None


def test_long_sentence_starting_with_yes_is_not_an_affirmative(monkeypatch):
    _llm(monkeypatch, WATCH_ON)
    store = Hooks()
    _handle("네 그런데 통관은 어디까지 됐어?", hooks=store, history=[OFFER_TURN])
    assert store.tool_calls == []


def test_not_logged_in_changes_nothing(monkeypatch):
    _llm(monkeypatch, WATCH_ON)
    r = _handle("이거 지켜봐 줘", user_id=None, hooks=None)
    assert r.reply == svc.WATCH_NEED_LOGIN == "로그인하면 이 화물을 지켜보다가 판정이 바뀔 때 알려 드려요." and r.watch_set is None


def test_logged_in_but_no_store_says_store_is_down(monkeypatch):
    _llm(monkeypatch, WATCH_ON)
    r = _handle("이거 지켜봐 줘", user_id=USER, hooks=None)
    assert r.reply == svc.WATCH_FAIL_REPLY["db"] and r.watch_set is None


@pytest.mark.parametrize("kind", ["limit", "done", "not_saved", "no_key", "db"])
def test_watch_errors_become_code_sentences(monkeypatch, kind):
    _llm(monkeypatch, WATCH_ON)
    r = _handle("이거 지켜봐 줘", hooks=Hooks(fail=kind))
    assert r.reply == svc.WATCH_FAIL_REPLY[kind] and r.watch_set is None
    assert (str(svc.MAX_WATCH) in r.reply) == (kind == "limit")


def test_store_exception_is_a_code_sentence_not_a_500(monkeypatch):
    _llm(monkeypatch, WATCH_ON)
    boom = svc.WatchHooks(tool=lambda bl, on: (_ for _ in ()).throw(RuntimeError("db down")), state=lambda bl: {}, worry=lambda bl: None)
    r = svc.handle("이거 지켜봐 줘", "s1", CONTEXT, _run(), USER, watch=boom)
    assert r.reply == svc.WATCH_FAIL_REPLY["db"]


def test_no_cargo_on_screen(monkeypatch):
    _llm(monkeypatch, WATCH_ON)
    r = _handle("이거 지켜봐 줘", hooks=Hooks(), context=None)
    assert r.reply == svc.WATCH_NO_CARGO


def test_new_bl_in_message_is_looked_up_first_then_watched(monkeypatch):
    """이번 문장의 B/L은 조회부터 한다 (화물 줄은 조회 뒤에 저장된다). set_watch를 먼저 부르면 조회부터 하라는 오류가 돌아온다."""
    results = _llm(monkeypatch, [("set_watch", {"on": True}), ("check_cargo", {"bl_ref": "[BL1]"}), ("set_watch", {"on": True})])
    store = Hooks()
    r = svc.handle("OTHERBL02 지켜봐 줘", "s1", None, _run(), USER, watch=store.hooks())
    assert results[0][1]["error"]["code"] == "lookup_first"
    assert store.tool_calls == [("OTHERBL02", True)]  # 대상은 이번 문장의 B/L
    assert r.kind == "cargo" and r.watch_set == {"bl_no": "OTHERBL02", "on": True}
    assert "조회 결과 답입니다." in r.reply and svc.WATCH_ON_REPLY in r.reply and r.watch_offer is None


def test_two_bls_cannot_be_watched_at_once(monkeypatch):
    _llm(monkeypatch, WATCH_ON)
    store = Hooks()
    r = svc.handle("TESTBL01 TESTBL02 지켜봐 줘", "s1", None, _run(), USER, watch=store.hooks())
    assert store.tool_calls == [] and svc.WATCH_ONE_AT_A_TIME in r.reply


# ── 먼저 제안 ──

def test_cargo_answer_gets_offer_with_real_reasons(monkeypatch):
    _llm(monkeypatch, ASK)
    r = _handle("지금 어디쯤이야?", hooks=Hooks())
    assert r.watch_offer == {"bl_no": BL, "reason": r.watch_offer["reason"], "logged_in": True}
    assert r.watch_offer["reason"] == "판매 예정일까지 여유가 2일이고 '주의' 판정이에요. 이 화물을 지켜볼까요?"
    assert r.reply.endswith(r.watch_offer["reason"]) and "조회 결과 답입니다." in r.reply


def test_offer_mentions_worry_memo_when_user_has_one(monkeypatch):
    _llm(monkeypatch, ASK)
    r = _handle("지금 어디쯤이야?", hooks=Hooks(worry="통관 늦어질까 걱정"))
    assert "지난번에 '통관 늦어질까 걱정'이라고 하셨죠." in r.watch_offer["reason"]
    assert r.watch_offer["reason"].endswith(chat_texts.WATCH_ASK)


def test_offer_without_margin_or_late(monkeypatch):
    _llm(monkeypatch, ASK)
    r = _handle("지금 어디쯤이야?", hooks=Hooks(), run=_run("act", None))
    assert r.watch_offer["reason"] == "'긴급' 판정이에요. 이 화물을 지켜볼까요?"
    r = _handle("지금 어디쯤이야?", hooks=Hooks(), run=_run("act", -3))
    assert r.watch_offer["reason"].startswith("판매 예정일보다 3일 늦게 도착할 예정이고 '긴급' 판정이에요.")


def test_no_offer_without_a_verdict(monkeypatch):
    _llm(monkeypatch, ASK)
    r = _handle("지금 어디쯤이야?", hooks=Hooks(), run=lambda req: _response(status="insufficient", verdict=None, answer="더 알려 주세요"))
    assert r.watch_offer is None and chat_texts.WATCH_ASK not in r.reply  # 이유가 없으면 말하지 않는다


def test_not_logged_in_offer_ends_with_login_notice(monkeypatch):
    _llm(monkeypatch, ASK)
    r = _handle("지금 어디쯤이야?", user_id=None, hooks=None)
    assert r.watch_offer["logged_in"] is False and r.watch_offer["reason"].endswith("로그인하면 지켜보다가 알려 드려요.")
    assert "지난번에" not in r.watch_offer["reason"]  # 로그인하지 않으면 메모를 읽지 않는다


def test_already_watching_gets_no_offer(monkeypatch):
    _llm(monkeypatch, ASK)
    r = _handle("지금 어디쯤이야?", hooks=Hooks(watching=True))
    assert r.watch_offer is None and chat_texts.WATCH_ASK not in r.reply


def test_offer_only_once_per_cargo_in_history(monkeypatch):
    _llm(monkeypatch, ASK)
    store = Hooks()
    history = [OFFER_TURN, {"role": "user", "text": "배는 어디야?"}, {"role": "assistant", "text": "부산 앞바다입니다."}]
    r = _handle("통관은?", hooks=store, history=history)
    assert r.watch_offer is None  # 같은 화물에 앞서 제안했다
    r = svc.handle("OTHERBL02 괜찮아?", "s1", CONTEXT, _run(), USER, history=history, watch=store.hooks())
    assert r.watch_offer is not None and r.watch_offer["bl_no"] == "OTHERBL02"  # 다른 화물은 새로 제안한다


def test_cue_offers_again_but_never_right_after_an_offer(monkeypatch):
    _llm(monkeypatch, ASK, cue=True)
    history = [OFFER_TURN, {"role": "user", "text": "배는 어디야?"}, {"role": "assistant", "text": "부산 앞바다입니다."}]
    r = _handle("늦으면 안 되는데 걱정되네", hooks=Hooks(), history=history)
    assert r.watch_offer is not None  # 걱정을 비쳤으니 다시 묻는다
    r = _handle("늦으면 안 되는데 걱정되네", hooks=Hooks(), history=[OFFER_TURN])
    assert r.watch_offer is None  # 방금 제안했는데 또 하지 않는다


def test_cue_without_flag_does_not_bypass_once_per_cargo(monkeypatch):
    _llm(monkeypatch, ASK, cue=False)
    r = _handle("늦으면 안 되는데", hooks=Hooks(), history=[OFFER_TURN, {"role": "assistant", "text": "그렇군요."}])
    assert r.watch_offer is None  # 코드는 LLM 신호가 있을 때만 다시 제안한다


def test_multi_bl_table_gets_no_offer(monkeypatch):
    _llm(monkeypatch, [("check_cargo", {"bl_ref": "[BL1]"})])
    r = svc.handle("TESTBL01 TESTBL02 뭐가 먼저 와?", "s1", None, _run(), USER, watch=Hooks().hooks())
    assert len(r.cargos) == 2 and r.watch_offer is None and chat_texts.WATCH_ASK not in r.reply


def test_state_failure_skips_offer_but_keeps_answer(monkeypatch):
    _llm(monkeypatch, ASK)
    bad = svc.WatchHooks(tool=lambda bl, on: {}, state=lambda bl: (_ for _ in ()).throw(RuntimeError("x")), worry=lambda bl: None)
    r = svc.handle("지금 어디쯤이야?", "s1", CONTEXT, _run(), USER, watch=bad)
    assert r.reply == "조회 결과 답입니다." and r.watch_offer is None


def test_fallback_path_without_agent_has_no_offer(monkeypatch):
    monkeypatch.setenv("CHAT_AGENT", "off")
    monkeypatch.setattr(llm, "route_chat", lambda *a, **k: llm.LLMAnswer(
        output=llm.ChatRouteOutput(intent="cargo", bl_ref="[BL1]", bl_type=None, sale_due_date=None, question=None,
                                   place=None, place_label=None, days=None, reply=""), llm=None, prompt_version="test"))
    r = svc.handle("TESTBL01 괜찮아?", "s1", None, _run(), None)
    assert r.watch_offer is None and r.watch_set is None


# ── 계약 (routers/chat.py ChatResponse) ──

def test_response_contract_defaults_and_shapes():
    base = chat_router.ChatResponse(kind="message", reply="안녕하세요")
    assert base.watch_offer is None and base.watch_set is None
    dumped = base.model_dump(mode="json")
    assert dumped["watch_offer"] is None and dumped["watch_set"] is None
    result = svc.ChatResult(kind="cargo", reply="r", watch_offer={"bl_no": BL, "reason": "이유", "logged_in": False},
                            watch_set={"bl_no": BL, "on": True})
    resp = chat_router.ChatResponse(**result.__dict__).model_dump(mode="json")
    assert resp["watch_offer"] == {"bl_no": BL, "reason": "이유", "logged_in": False}
    assert resp["watch_set"] == {"bl_no": BL, "on": True}
    assert svc.ChatResult(kind="message", reply="x").watch_offer is None  # 옛 결과는 그대로


def test_schema_has_watch_cue_and_default_false():
    assert "watch_cue" in llm.CHAT_AGENT_SCHEMA["required"] and llm.CHAT_AGENT_SCHEMA["properties"]["watch_cue"] == {"type": "boolean"}
    assert llm.ChatAgentOutput(reply="", answer_kind="tool").watch_cue is False


# ── 라우터가 만드는 저장소 함수 (DB 연결은 가짜) ──

def test_router_hooks_none_without_user_or_db(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://example")
    assert chat_router._watch_hooks(None) is None
    monkeypatch.delenv("DATABASE_URL")
    assert chat_router._watch_hooks(USER) is None


def test_router_tool_retries_not_saved_then_succeeds(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://example")
    monkeypatch.setattr(chat_router, "SAVE_WAIT_SEC", 0)
    attempts = []

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_set(conn, user_id, bl_no, on):
        attempts.append(bl_no)
        if len(attempts) < 2:
            raise WatchError("not_saved")
        return on
    monkeypatch.setattr(chat_router.ops, "open_conn", lambda: Conn())
    monkeypatch.setattr(chat_router.watch_service, "set_watch", fake_set)
    hooks = chat_router._watch_hooks(USER)
    assert hooks.tool(BL, True) == {"on": True} and len(attempts) == 2
    monkeypatch.setattr(chat_router.watch_service, "set_watch", lambda *a: (_ for _ in ()).throw(WatchError("limit")))
    assert hooks.tool(BL, True) == {"error": "limit"}


def test_router_worry_picks_latest_worry_of_that_cargo(monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("BL_ENCRYPTION_KEY", Fernet.generate_key().decode())  # 화물 지문(cargo_key)에 필요
    monkeypatch.setenv("DATABASE_URL", "postgres://example")
    from backend.app.services.watch import cargo

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
    key = cargo.cargo_key(BL)
    items = [{"kind": "worry", "cargo_key": key, "fields": {"text": "옛 걱정"}},
             {"kind": "worry", "cargo_key": "other", "fields": {"text": "남의 화물"}},
             {"kind": "todo", "cargo_key": key, "fields": {"text": "할 일"}},
             {"kind": "worry", "cargo_key": key, "fields": {"text": "통관 늦어질까 걱정"}}]
    monkeypatch.setattr(chat_router.ops, "open_conn", lambda: Conn())
    monkeypatch.setattr(chat_router.memory_service, "load", lambda conn, user_id: (items, 1, True, False))
    assert chat_router._watch_hooks(USER).worry(BL) == "통관 늦어질까 걱정"
    assert chat_router._watch_hooks(USER).worry("NOPE00001") is None


# ── 지켜보기만 바라는 짧은 말은 LLM 없이 코드가 처리 ("응 지켜봐 줘"에 엉뚱한 화물 답이 붙었다) ──

def _ctx():
    from backend.app.schemas.agent import AgentRequest
    return AgentRequest(bl_no="TESTBL01", bl_type="HOUSE", session_id="s1")


@pytest.mark.parametrize("text", ["응 지켜봐 줘", "이거 지켜봐 줘", "그만 지켜봐도 돼"])
def test_short_watch_request_skips_llm(monkeypatch, text):
    from backend.tests.integration.test_chat_agent import _agent
    calls = _agent(monkeypatch, [])  # LLM이 불리면 기록된다
    r = svc.handle(text, "s1", _ctx(), lambda req: pytest.fail("조회하면 안 된다"))
    assert len(calls) == 0 and r.reply == svc.WATCH_NEED_LOGIN  # 로그인 없음: 아무것도 안 바꾸고 안내만


@pytest.mark.parametrize("text", ["카톡 알림 안 와", "언제 오는지 알려줘", "지켜봐야 해?"])
def test_non_requests_are_not_short_path(text):
    assert not svc.WATCH_REQUEST.search(text)
