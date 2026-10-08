"""채팅 "지금 상태 카카오톡으로 보내기" 테스트 (services/chat/chat.py send_kakao·KakaoHooks, routers/chat._kakao_hooks).

LLM·DB·카카오는 부르지 않는다. 가짜 llm.chat_agent와 가짜 KakaoHooks를 끼운다. B/L은 모의값이다.
확인하는 것: 보내기는 분명한 말에서만 실행 · 보내기 말이 지켜보기를 바꾸지 않음 · 5분 쿨다운 · 이미 지켜보는 중 문장 ·
연결 안 됨/로그인 안 함/화물 없음 문장 · 카카오톡 글에 B/L 원문이 없음 · LLM에는 B/L 원문이 가지 않음.
"""
from datetime import date, datetime, timezone

import pytest
from cryptography.fernet import Fernet

from backend.app.services.chat import chat as svc
from backend.app.services import llm
from backend.tests.integration.test_chat_watch import BL, CONTEXT, USER, Hooks, _llm, _run, agent_path  # noqa: F401 (fixture)

ROW = {"bl_masked": "TEST****01", "label": None, "last_verdict": "watch", "last_eta": date(2026, 10, 12),
       "sale_due_date": date(2026, 10, 15), "last_days_margin": 3, "last_stage": "반입신고",
       "last_checked_at": datetime(2026, 10, 6, 1, 0, tzinfo=timezone.utc)}
SEND = [("send_kakao", {})]


class Kakao:
    """가짜 카카오톡 저장소. sent: 보낸 글 목록, fail: send가 낼 오류 종류, row: 저장된 화물 줄."""

    def __init__(self, fail=None, row=ROW):
        self.sent, self.fail, self.row_value = [], fail, row

    def hooks(self):
        def send(text):
            if self.fail:
                return {"error": self.fail}
            self.sent.append(text)
            return {"sent": True}
        return svc.KakaoHooks(row=lambda bl: self.row_value, send=send)


@pytest.fixture(autouse=True)
def clean_cooldown(monkeypatch):
    monkeypatch.setenv("BL_ENCRYPTION_KEY", Fernet.generate_key().decode())  # 화물 지문(cargo_key)에 필요하다
    svc._kakao_sent_at.clear()
    yield
    svc._kakao_sent_at.clear()


def _handle(message, *, kakao=None, watch=None, user_id=USER, context=CONTEXT, run=None, history=None):
    return svc.handle(message, "s1", context, run or _run(), user_id, history=history or [],
                      watch=watch.hooks() if watch else None, kakao=kakao.hooks() if kakao else None)


# ── 말 가르기 ──

@pytest.mark.parametrize("text", ["지금 지켜보는거 알림 보내줄래?", "현재 기준으로 카카오톡 알림 보내줘", "카톡으로 보내 줘",
                                  "지금 상태 카카오톡으로 전송해줘", "보내줘 카톡으로"])
def test_send_now_words(text):
    assert svc.wants_send_now(text)


@pytest.mark.parametrize("text", ["이거 지켜봐 줘", "바뀌면 카톡으로 알림 보내 줘", "알림 걸어줘", "카톡 연결은 어떻게 해?",
                                  "앞으로 카카오톡으로 보내줘", "지금 어디쯤이야?"])
def test_not_send_now_words(text):
    assert not svc.wants_send_now(text)


# ── 보내기 ──

def test_short_send_is_code_path_without_llm(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("LLM을 부르면 안 된다")
    monkeypatch.setattr(llm, "chat_agent", boom)
    kakao, store = Kakao(), Hooks(watching=True)
    r = _handle("현재 기준으로 카카오톡 알림 보내줘", kakao=kakao, watch=store)
    assert r.reply == svc.KAKAO_SENT and r.watch_set is None and store.tool_calls == []
    assert len(kakao.sent) == 1


def test_message_template_uses_only_stored_values(monkeypatch):
    kakao = Kakao()
    _handle("지금 카톡으로 보내 줘", kakao=kakao)
    text = kakao.sent[0]
    assert text.startswith("[Marvia] TEST****01 화물 현재 상태\n판정: 주의\n도착 예정: 2026-10-12\n")
    assert "판매 예정일(2026-10-15)까지: " in text and "도착 기준: 여유 3일" in text
    assert "통관: 반입신고" in text and "마지막 확인: 10.06" in text and "Marvia에서 이유와 할 일을 확인하세요." in text
    assert BL not in text  # 원문 B/L 없음


def test_label_used_when_present_and_missing_values_skipped():
    row = {**ROW, "label": "내 화물", "last_eta": None, "sale_due_date": None, "last_days_margin": None, "last_stage": None}
    text = svc.kakao_now_text(row, date(2026, 10, 6))
    assert "내 화물 화물 현재 상태" in text and "도착 예정" not in text and "판매 예정일" not in text and "통관" not in text


def test_sale_date_passed_text():
    assert "3일 지남" in svc.kakao_now_text({**ROW, "sale_due_date": date(2026, 10, 3)}, date(2026, 10, 6))


def test_no_verdict_means_no_message():
    assert svc.kakao_now_text({**ROW, "last_verdict": None}, date(2026, 10, 6)) is None
    kakao = Kakao(row={**ROW, "last_verdict": None})
    assert _handle("카톡으로 보내 줘", kakao=kakao).reply == svc.KAKAO_NO_VERDICT and kakao.sent == []


def test_row_missing_is_not_ready():
    kakao = Kakao(row=None)
    assert _handle("카톡으로 보내 줘", kakao=kakao).reply == svc.KAKAO_NOT_READY and kakao.sent == []


# ── 분명한 말에서만, 지켜보기는 건드리지 않음 ──

def test_llm_calling_send_without_words_is_refused(monkeypatch):
    _llm(monkeypatch, SEND)
    kakao = Kakao()
    r = _handle("지금 어디쯤이야?", kakao=kakao)
    assert kakao.sent == [] and svc.KAKAO_SENT not in r.reply


def test_llm_path_sends_with_words_and_does_not_toggle_watch(monkeypatch):
    results = _llm(monkeypatch, [("set_watch", {"on": True}), *SEND])
    kakao, store = Kakao(), Hooks()
    r = _handle("이 화물 지금 상태를 판정이랑 도착 예정일이랑 통관 단계까지 전부 모아서 카톡으로 좀 보내 줄래 부탁해요", kakao=kakao, watch=store)
    assert store.tool_calls == [] and r.watch_set is None
    assert dict(results)["set_watch"]["error"]["code"] == "not_requested"  # LLM이 set_watch를 불러도 거절된다
    assert len(kakao.sent) == 1 and r.reply.endswith(svc.KAKAO_SENT)


def test_watch_requests_still_watch():
    store, kakao = Hooks(), Kakao()
    r = _handle("이거 지켜봐 줘", kakao=kakao, watch=store)
    assert r.watch_set == {"bl_no": BL, "on": True} and kakao.sent == []
    r = _handle("바뀌면 카톡으로 알려 줘", kakao=kakao, watch=Hooks(), run=_run())
    assert kakao.sent == []  # 앞날 낱말이 있어 지금 보내기가 아니다


# ── 쿨다운 ──

def test_cooldown_five_minutes(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(svc.time, "monotonic", lambda: clock[0])
    kakao = Kakao()
    assert _handle("카톡으로 보내 줘", kakao=kakao).reply == svc.KAKAO_SENT
    clock[0] += 120
    assert _handle("카톡으로 보내 줘", kakao=kakao).reply == svc.KAKAO_COOLDOWN_REPLY
    clock[0] += 181  # 합계 301초
    assert _handle("카톡으로 보내 줘", kakao=kakao).reply == svc.KAKAO_SENT
    assert len(kakao.sent) == 2


def test_cooldown_is_per_user_and_failure_does_not_consume_it():
    kakao = Kakao()
    _handle("카톡으로 보내 줘", kakao=kakao)
    assert _handle("카톡으로 보내 줘", kakao=kakao, user_id="user-2").reply == svc.KAKAO_SENT
    failing = Kakao(fail="not_linked")
    assert _handle("카톡으로 보내 줘", kakao=failing, user_id="user-3").reply == svc.KAKAO_NOT_LINKED
    ok = Kakao()
    assert _handle("카톡으로 보내 줘", kakao=ok, user_id="user-3").reply == svc.KAKAO_SENT  # 실패는 쿨다운을 쓰지 않는다


# ── 결과 문장 ──

@pytest.mark.parametrize("kind,reply", [
    ("not_linked", svc.KAKAO_NOT_LINKED), ("relink", svc.KAKAO_FAIL_REPLY["relink"]),
    ("no_consent", svc.KAKAO_FAIL_REPLY["no_consent"]), ("failed", svc.KAKAO_FAILED), ("db", svc.KAKAO_FAILED)])
def test_send_errors_are_code_sentences(kind, reply):
    assert _handle("카톡으로 보내 줘", kakao=Kakao(fail=kind)).reply == reply


def test_not_logged_in():
    assert _handle("카톡으로 보내 줘", user_id=None).reply == svc.KAKAO_NEED_LOGIN


def test_no_hooks_logged_in_is_failure_sentence():
    assert _handle("카톡으로 보내 줘").reply == svc.KAKAO_FAILED


def test_no_current_cargo_asks_for_bl():
    kakao = Kakao()
    r = _handle("카톡으로 보내 줘", kakao=kakao, context=None)
    assert r.reply == svc.KAKAO_NO_CARGO and kakao.sent == []


def test_two_bls_one_at_a_time(monkeypatch):
    _llm(monkeypatch, SEND)
    kakao = Kakao()
    r = svc.handle("TESTBL01 TESTBL02 카톡으로 보내 줘 지금", "s1", None, _run(), USER, kakao=kakao.hooks())
    assert kakao.sent == [] and svc.KAKAO_ONE_AT_A_TIME in r.reply


def test_no_raw_bl_to_llm(monkeypatch):
    seen = []

    def fake(masked, refs, has_cargo, today, history, tools, run, *, model=None, feedback=None, evidence=None):
        seen.append((masked, refs, [t["function"]["name"] for t in tools]))
        run("send_kakao", {})
        out = llm.ChatAgentOutput(reply="", answer_kind="tool", skill_quote="", watch_cue=False)
        return llm.LLMAnswer(output=out, llm=None, prompt_version="test", tool_calls=[])
    monkeypatch.setattr(llm, "chat_agent", fake)
    kakao = Kakao()
    svc.handle("TESTBL01 현재 상태를 지금 카톡으로 보내 줘 부탁", "s1", CONTEXT, _run(), USER, kakao=kakao.hooks())
    assert seen and "TESTBL01" not in seen[0][0] and "send_kakao" in seen[0][2]
    assert all(BL not in t for t in kakao.sent)


# ── 이미 지켜보는 중 ──

def test_already_watching_message():
    store = Hooks(watching=True)
    r = _handle("이거 지켜봐 줘", watch=store)
    assert r.reply == svc.WATCH_ALREADY_ON + "\n" + svc.WATCH_PAGE_LINE and store.tool_calls == [] and r.watch_set is None


def test_already_off_message():
    store = Hooks(watching=False)
    r = _handle("그만 지켜봐도 돼", watch=store)
    assert r.reply == svc.WATCH_ALREADY_OFF and store.tool_calls == []


def test_usage_guide_mentions_send():
    assert "카톡으로 보내 줘" in svc.USAGE_GUIDE
