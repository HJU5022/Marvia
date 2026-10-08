"""실제 화면에서 나온 여러 B/L·카톡·제목 문제 (services/chat/chat.py, services/chat/conversations.py).
1) B/L로 읽지 못한 식별자 모양 글자(tesbl41)가 말없이 빠지지 않는다  2) 판정을 못 낸 줄의 이유 + 답 문장
3) 되묻기가 필요한 줄이 다음 문장의 문맥  4) "아래" 문구  5) 카톡 말과 함께 지켜보기 요청 → 연결 상태를 사실대로
6) "인사" 같은 임시 제목은 첫 진짜 질문에서 다시 짓는다. LLM·DB는 가짜."""
from datetime import datetime, timezone

import pytest

from backend.app.routers.agent import ASK_BACK, ASK_BACK_AFTER_EVIDENCE, NO_CARGO, _response
from backend.app.schemas.agent import VesselCandidate
from backend.app.services.chat import chat as svc
from backend.app.services.chat import conversations as conv
from backend.tests.integration.test_chat_agent import _agent
from backend.tests.integration.test_chat_multi_bl import CHECK, _two_run
from backend.tests.integration.test_chat_watch import CONTEXT, USER, Hooks, _llm, _run, agent_path  # noqa: F401 (fixture)


def _cand(n):
    return VesselCandidate(mmsi=440000000 + n, imo=None, name="TEST TWIN 42", flag=None, dest=None,
                           last_time=datetime(2026, 10, 6, tzinfo=timezone.utc), ship_type=None, match_reasons=[])


def _mixed_run(first="ask", answer=ASK_BACK):
    """TESTBL02는 판정을 못 낸 줄(first: ask=같은 이름 배 두 척, none=조회 결과 없음), 나머지는 정상."""
    _, ok = _two_run()

    def run(req):
        if req.bl_no.endswith("02"):
            cands = [_cand(1), _cand(2)] if first == "ask" else []
            return _response(status="insufficient", answer=answer, vessel_match="uncertain", vessel_candidates=cands,
                             missing_inputs=[] if cands else ["bl_type"])
        return ok(req)
    return run


def test_unread_id_like_text_is_named_in_notice(monkeypatch):
    _agent(monkeypatch, CHECK)
    _, run = _two_run()
    r = svc.handle("tesbl41 TESTBL01 TESTBL02 셋다 확인 좀 해줄래?", "s1", None, run)
    assert len(r.cargos) == 2 and "'tesbl41'" in r.reply and "읽지 못한" in r.reply
    assert r.reply.count("tesbl41") == 1


def test_ordinary_words_dates_and_known_bls_are_not_flagged(monkeypatch):
    _agent(monkeypatch, CHECK)
    _, run = _two_run()
    r = svc.handle("TESTBL01 TESTBL02 판매 2026-10-11 까지 어느 게 먼저 와? 10월 8일", "s1", None, run)
    assert "읽지 못한" not in r.reply
    assert svc.unread_ids("hello 20261008 [BL1] vessel 10.08", ["TESTBL01"]) == []
    assert svc.unread_ids("tesbl41 AB12 [BL1] tesbl41", []) == ["tesbl41", "AB12"]
    assert svc.unread_ids("testbl01 [BL2]", ["TESTBL01"]) == []  # 조회한 B/L과 같은 글자는 뺀다


def test_insufficient_row_says_what_is_needed(monkeypatch):
    _agent(monkeypatch, CHECK)
    r = svc.handle("TESTBL02 TESTBL03 확인해줘", "s1", None, _mixed_run())
    row = next(c for c in r.cargos if c["bl_no"] == "TESTBL02")
    assert row["note"] == "같은 이름 배 2척" and row["status"] == "insufficient"
    assert next(c for c in r.cargos if c["bl_no"] == "TESTBL03")["note"] is None
    assert "TESTBL02는 같은 이름의 배가 여러 척이라 항차 번호나 포워더 입항 예정일이 필요해요." in r.reply
    assert "TESTBL03는" not in r.reply


@pytest.mark.parametrize("first, answer, note, sentence", [
    ("ask", ASK_BACK_AFTER_EVIDENCE, "같은 이름 배 2척", "어느 배인지 가르지 못했어요"),
    ("none", NO_CARGO, "조회 결과 없음", "조회 결과가 없어요"),
    ("none", "무언가 더 필요", "정보 더 필요", "정보가 더 필요해요"),
])
def test_other_insufficient_reasons(monkeypatch, first, answer, note, sentence):
    _agent(monkeypatch, CHECK)
    r = svc.handle("TESTBL02 TESTBL03 확인해줘", "s1", None, _mixed_run(first, answer))
    assert next(c for c in r.cargos if c["bl_no"] == "TESTBL02")["note"] == note and sentence in r.reply


def test_ask_back_row_becomes_the_context_even_if_not_first(monkeypatch):
    _agent(monkeypatch, CHECK)
    r = svc.handle("TESTBL03 TESTBL02 확인해줘", "s1", None, _mixed_run())  # 되묻기 줄이 둘째
    assert [c["bl_no"] for c in r.cargos] == ["TESTBL03", "TESTBL02"]  # 줄 순서는 그대로
    assert r.request.bl_no == "TESTBL02" and r.agent.status == "insufficient" and len(r.agent.vessel_candidates) == 2


def test_not_found_row_does_not_steal_the_context(monkeypatch):
    _agent(monkeypatch, CHECK)
    r = svc.handle("TESTBL03 TESTBL02 확인해줘", "s1", None, _mixed_run("none", NO_CARGO))
    assert r.request.bl_no == "TESTBL03"  # 되묻기가 아니라 못 찾은 줄이다. 첫 B/L 그대로


def test_all_ok_keeps_first_row_as_context(monkeypatch):
    _agent(monkeypatch, CHECK)
    _, run = _two_run()
    r = svc.handle("TESTBL01 TESTBL02 확인해줘", "s1", None, run)
    assert r.request.bl_no == "TESTBL01" and all(c["note"] is None for c in r.cargos)


def test_lead_and_texts_say_below_not_right(monkeypatch):
    assert "아래" in svc.MULTI_TABLE_LEAD and "오른쪽" not in svc.MULTI_TABLE_LEAD
    _agent(monkeypatch, CHECK)
    _, run = _two_run()
    r = svc.handle("TESTBL01 TESTBL02 확인해줘", "s1", None, run)
    assert "오른쪽" not in r.reply


# ── 카톡 말 + 지켜보기 ──

def _kakao(linked):
    return svc.KakaoHooks(row=lambda bl: None, send=lambda t: {"sent": True}, linked=lambda: linked)


def _ask(monkeypatch, message, store, kakao):
    _llm(monkeypatch, [("set_watch", {"on": True})])
    return svc.handle(message, "s1", CONTEXT, _run(), USER, watch=store.hooks(), kakao=kakao)


def test_already_watching_with_kakao_linked(monkeypatch):
    r = _ask(monkeypatch, "이거 카톡으로 알림 설정 좀 해줄래?", Hooks(watching=True), _kakao(True))
    assert r.reply == "이미 이 화물을 지켜보고 있어요. 판정이 바뀌면 카카오톡으로도 보내 드려요." + "\n" + svc.WATCH_PAGE_LINE


def test_already_watching_with_kakao_not_linked(monkeypatch):
    r = _ask(monkeypatch, "이거 카톡으로 알림 설정 좀 해줄래?", Hooks(watching=True), _kakao(False))
    assert r.reply == ("이미 이 화물을 지켜보고 있어요. 카카오톡은 아직 연결되지 않았어요. "
                       "설정에서 연결하면 판정이 바뀔 때 카톡으로도 받을 수 있어요." + "\n" + svc.WATCH_PAGE_LINE)


def test_just_turned_on_with_kakao_words(monkeypatch):
    store = Hooks()
    r = _ask(monkeypatch, "카카오톡으로 알림 걸어줘", store, _kakao(False))
    assert store.tool_calls and r.watch_set == {"bl_no": CONTEXT.bl_no, "on": True}
    assert r.reply.startswith(svc.WATCH_ON_PLAIN) and "아직 연결되지 않았어요" in r.reply
    r = _ask(monkeypatch, "카카오톡으로 알림 걸어줘", Hooks(), _kakao(True))
    assert r.reply.endswith("판정이 바뀌면 카카오톡으로도 보내 드려요.\n" + svc.WATCH_PAGE_LINE) and "연결되지" not in r.reply


def test_no_kakao_word_or_unknown_state_keeps_old_sentences(monkeypatch):
    r = _ask(monkeypatch, "이거 지켜봐 줘", Hooks(watching=True), _kakao(True))
    assert r.reply == svc.WATCH_ALREADY_ON + "\n" + svc.WATCH_PAGE_LINE  # 카톡 말이 없으면 그대로
    r = _ask(monkeypatch, "카톡으로 알림 설정", Hooks(watching=True), None)
    assert r.reply == svc.WATCH_ALREADY_ON + "\n" + svc.WATCH_PAGE_LINE  # 카카오 저장소가 없어 상태를 모른다: 지어내지 않는다

    def boom():
        raise RuntimeError("db")
    r = _ask(monkeypatch, "카톡으로 알림 설정", Hooks(watching=True), svc.KakaoHooks(row=lambda b: None, send=lambda t: {}, linked=boom))
    assert r.reply == svc.WATCH_ALREADY_ON + "\n" + svc.WATCH_PAGE_LINE


def test_router_kakao_hooks_expose_linked(monkeypatch):
    from backend.app.routers import chat as chat_router
    monkeypatch.setenv("DATABASE_URL", "postgres://x")
    seen = []

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(chat_router.ops, "open_conn", lambda: Conn())
    monkeypatch.setattr(chat_router.kakao_service, "is_linked", lambda conn, uid: seen.append(uid) or True)
    hooks = chat_router._kakao_hooks("u1")
    assert hooks.linked() is True and seen == ["u1"]


# ── 임시 제목 ──

@pytest.mark.parametrize("title", ["인사", "인사말", "안부 인사", "안부", "감사 인사", "새 대화", "", "  안녕하세요  ", "hello"])
def test_placeholder_titles(title):
    assert conv.is_placeholder_title(title)


@pytest.mark.parametrize("title", ["TESTBL01 언제 와?", "고추 입항 확인", None])
def test_real_or_unreadable_titles_are_kept(title):
    assert not conv.is_placeholder_title(title)


def test_old_greeting_title_is_retitled_on_first_real_question(monkeypatch):
    from backend.tests.integration.test_conversations import FakeConn, REPLY
    from cryptography.fernet import Fernet
    monkeypatch.setenv("PII_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    conn = FakeConn()
    monkeypatch.setattr(conv, "connect", lambda: conn)
    titles = []
    monkeypatch.setattr(conv, "make_title", lambda text: titles.append(text) or "화물 도착 확인")
    monkeypatch.setattr(conv, "save_turn", lambda *a: False)
    monkeypatch.setattr(conv, "current_title", lambda *a: "인사")  # 고치기 전에 만들어진 대화
    conv._save_job("u1", "s1", "TESTBL01 언제 와?", REPLY)
    assert titles == ["TESTBL01 언제 와?"]
    monkeypatch.setattr(conv, "current_title", lambda *a: "화물 도착 확인")
    conv._save_job("u1", "s1", "통관은?", REPLY)
    assert titles == ["TESTBL01 언제 와?"]  # 진짜 제목이 있으면 다시 짓지 않는다
