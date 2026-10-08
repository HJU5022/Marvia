"""안내처(다음 행선지) 붙이기 (services/chat/referrals.py, docs/specs/referral-guide.md).

- 판정: 켜진 신호마다 확인처 한 줄. 위험한 순서로 두 개까지, 괜찮음과 입력 오류 신호에는 붙이지 않는다
- 판정 응답: LLM 검증을 통과한 뒤 할 일 끝에 붙고, LLM이 끝내 실패한 표 등급 응답에도 붙는다
- 채팅: 범위 밖 주제는 LLM 없이 고정 문장. B/L이 있으면 조회가 먼저라 보지 않는다
문장·주소는 skills/referrals/rules.md에서 읽는다. 테스트도 rule()로 비교해 문장을 고쳐도 깨지지 않게 한다.
키·DB·LLM 없이 돈다.
"""
from datetime import datetime, timezone

import pytest

from backend.app.schemas.signals import Signal, SignalSet
from backend.app.services.chat import referrals
from backend.app.services.judge.rules import rule
from backend.app.services.judge.signals import DEST_BROKEN

NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)
IDS = ["position_stale", "eta_conflict", "anchor_wait", "dest_changed", "navstat_mismatch", "customs_hold",
       "sales_date_exceeded"]


def _set(on: dict[str, str] | set[str] = frozenset(), unknown: set[str] = frozenset()) -> SignalSet:
    """on에 든 신호는 triggered. dict면 값도 준다 (목적지 입력 오류 시험용)."""
    values = on if isinstance(on, dict) else {}
    signals = [Signal(id=i, state="triggered" if i in on else "unknown" if i in unknown else "clear",
                      value=values.get(i, "-"), threshold="-", source="rule") for i in IDS]
    return SignalSet(signals=signals, freshness="fresh", distance_nm=None, calc_eta=None, eta_gap_hours=None,
                     computed_at=NOW)


def _text(sid: str) -> str:
    return rule("signal_referrals")[sid]


def test_fine_gets_nothing():
    assert referrals.signal_lines(_set()) == []
    assert referrals.signal_lines(None) == []


def test_unknown_is_not_on():
    assert referrals.signal_lines(_set(unknown={"customs_hold", "anchor_wait"})) == []


def test_one_signal_one_line():
    assert referrals.signal_lines(_set({"anchor_wait"})) == [rule("referral_prefix") + _text("anchor_wait")]


def test_customs_hold_adds_official_link():
    lines = referrals.signal_lines(_set({"customs_hold"}))
    assert lines == [rule("referral_prefix") + _text("customs_hold"), rule("signal_referral_links")["customs_hold"]]
    assert "unipass.customs.go.kr" in lines[1]


def test_order_and_max():
    """위험한 순서(referral_order)로 referral_max개까지만 한 줄로 묶는다."""
    lines = referrals.signal_lines(_set({"eta_conflict", "sales_date_exceeded", "dest_changed", "position_stale"}))
    assert rule("referral_max") == 2
    assert lines == [rule("referral_prefix") + " ".join([_text("dest_changed"), _text("sales_date_exceeded")])]


def test_navstat_mismatch_gets_nothing():
    """항해 상태 불일치는 데이터 오류일 수 있어 안내하지 않는다 (판정에서도 세지 않는다)."""
    assert referrals.signal_lines(_set({"navstat_mismatch"})) == []


def test_broken_destination_gets_nothing():
    """깨진 목적지로 켜진 dest_changed는 판정에서 세지 않으니 안내도 붙이지 않는다 (verdict.input_error)."""
    assert referrals.signal_lines(_set({"dest_changed": DEST_BROKEN})) == []


def test_with_signal_lines_appends_once():
    actions = ["접안 예정일을 확인해 두세요."]
    out = referrals.with_signal_lines(actions, _set({"anchor_wait"}))
    assert out == [*actions, rule("referral_prefix") + _text("anchor_wait")]
    assert referrals.with_signal_lines(out, _set({"anchor_wait"})) == out  # 두 번 붙이지 않는다


def test_every_triggerable_signal_in_order_has_text():
    """순서 목록의 신호는 모두 문장이 있고, 신호 id는 계약(SignalId)에 있는 이름이다."""
    texts = rule("signal_referrals")
    assert set(rule("referral_order")) == set(texts)
    assert set(texts) <= set(IDS)


@pytest.mark.parametrize("message,topic", [
    ("항공으로 오는 화물도 봐 줄 수 있어?", "air_land"),
    ("창고에서 언제 물건 받을 수 있어?", "warehouse_date"),
    ("배 일정 좀 앞당겨 줄 수 있어?", "schedule_change"),
    ("태풍 오는데 내 배 늦어?", "weather"),
    ("이거 수입하려면 인증 필요해?", "import_requirement"),
])
def test_out_of_scope_topics(message, topic):
    hit = referrals.out_of_scope_topic(message)
    assert hit is not None and hit[0] == topic
    assert hit[1] == next(i["reply"] for i in rule("out_of_scope") if i["topic"] == topic)


@pytest.mark.parametrize("message", [
    "판매일까지 괜찮을까?",
    "배 지금 어디쯤이야?",
    "언제 도착해?",
    "판매 일정을 바꿨어",          # 일정 이야기지만 바꿔 달라는 요청이 아니다 (require)
    "창고 이름이 뭐야?",           # 창고 이야기지만 날짜를 묻지 않는다
    "통관 단계가 뭐야?",
    "언제 반출돼?",                # 통관 시기 질문은 지금 단계로 답한다 (채팅 에이전트 규칙). 범위 밖이 아니다
])
def test_cargo_questions_are_not_out_of_scope(message):
    assert referrals.out_of_scope_topic(message) is None


def test_weather_reply_does_not_claim_a_cause():
    """날씨 답은 늦는다·안 늦는다를 단정하지 않는다 (판정은 관측값에서 나온다)."""
    reply = referrals.out_of_scope_topic("태풍 때문에 늦어?")[1]
    assert "미리 판단하지 않습니다" in reply


# ── 채팅 연결 (services/chat/chat.py) ──

def test_chat_answers_out_of_scope_without_llm(monkeypatch):
    from backend.app.services.chat import chat as svc
    monkeypatch.setattr(svc.llm, "chat_agent", lambda *a, **k: pytest.fail("범위 밖 주제는 LLM을 부르지 않는다"))
    monkeypatch.setattr(svc.llm, "route_chat", lambda *a, **k: pytest.fail("범위 밖 주제는 LLM을 부르지 않는다"),
                        raising=False)
    r = svc.handle("항공으로 오는 화물도 봐 줄 수 있어?", "s-ref", None, lambda req: pytest.fail("조회 안 함"))
    assert r.kind == "message" and r.reply.startswith("마르비아는 부산항으로")


def test_chat_with_bl_goes_to_lookup_not_out_of_scope(monkeypatch):
    """B/L이 있으면 날씨 낱말이 있어도 그 화물 조회가 먼저다."""
    from backend.app.services.chat import chat as svc
    seen = []
    monkeypatch.setattr(svc.referrals, "out_of_scope_topic", lambda m: seen.append(m) or ("weather", "x"))
    monkeypatch.setattr(svc, "agent_enabled", lambda: False)
    monkeypatch.setattr(svc, "_classic", lambda *a, **k: svc.ChatResult(kind="cargo", reply="조회"))
    r = svc.handle("TESTBL01 태풍 오는데 늦어?", "s-ref", None, lambda req: None)
    assert r.reply == "조회" and seen == []


def test_broker_only_has_official_tail():
    from backend.app.services.chat import chat as svc
    assert svc.BROKER_ONLY.endswith(rule("broker_referral")) and "관세사" in svc.BROKER_ONLY


def test_chat_broker_topic_without_cargo_is_fixed_even_without_agent(monkeypatch):
    """에이전트를 못 쓰는 전 방식에서도 세액 질문은 관세사 고정 안내다 (재생 서버 실측)."""
    from backend.app.services.chat import chat as svc
    monkeypatch.setattr(svc, "agent_enabled", lambda: False)
    monkeypatch.setattr(svc, "_classic", lambda *a, **k: pytest.fail("세액 질문은 전 방식으로 가지 않는다"))
    r = svc.handle("관세 얼마 나와?", "s-ref", None, lambda req: None)
    assert r.reply == svc.BROKER_ONLY


def test_chat_broker_word_in_broker_name_is_not_tax(monkeypatch):
    """'관세사'는 세액 주제가 아니다 (BROKER_TOPIC 관세(?!사))."""
    from backend.app.services.chat import chat as svc
    monkeypatch.setattr(svc, "agent_enabled", lambda: False)
    monkeypatch.setattr(svc, "_classic", lambda *a, **k: svc.ChatResult(kind="message", reply="전 방식"))
    assert svc.handle("관세사는 어떻게 찾아?", "s-ref", None, lambda req: None).reply == "전 방식"
