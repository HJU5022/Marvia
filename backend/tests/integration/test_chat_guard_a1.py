"""실험 A1: 사람 이름 되풀이 막기 테스트 (services/chat/chat.py person_names·echoes_person_name, 항상 켜짐).

화물·배와 상관없는 사람 이름("호준이", "민수 어디야?", "김대리한테 전달해야 돼")에 모델이 이름을 따라 쓴 답은 버리고
고정 문장으로 누구를 말하는지 되묻는다. 저장한 메모를 묻는 말(거래처 이름 등)의 답은 건드리지 않는다. LLM은 부르지 않는다 (가짜 chat_agent).
"""
import pytest

from backend.app.services.chat import chat as svc
from backend.app.services import llm
from backend.app.services.judge import validate
from backend.tests.integration.test_chat_agent import _agent, _no_classic
from backend.app.services.chat import ids as chat_ids

KNOWN = llm.skills_reference(llm.CHAT_AGENT_SKILLS) + svc.OTHER_REPLY + validate.GENERAL_TERMS


@pytest.mark.parametrize("message,name", [("호준이", "호준"), ("민수 어디야?", "민수"), ("김대리한테 전달해야 돼", "김대리"),
                                          ("민수야", "민수"), ("김대리", "김대리")])
def test_person_like_words_are_found(message, name):
    assert name in chat_ids.person_names(message, KNOWN)


@pytest.mark.parametrize("message", ["아 짜증나", "ㅋㅋㅋ", "망했다", "힘들다", "B/L 번호는 어디서 찾아?", "통관 며칠 걸려?", "이 배 어디야?", "D/O가 뭐야?"])
def test_ordinary_messages_have_no_person_name(message):
    assert chat_ids.person_names(message, KNOWN) == []


def test_echo_is_detected_only_when_the_reply_writes_the_name():
    assert svc.echoes_person_name("호준이", "호준이가 누구인지 알려 주세요.", KNOWN)
    assert not svc.echoes_person_name("호준이", "누구를 말씀하시는지 알려 주세요.", KNOWN)


def test_guard_replaces_name_echo_with_fixed_question(monkeypatch):
    _no_classic(monkeypatch)
    _agent(monkeypatch, [], [("호준이가 누구인지 알려 주세요.", "unrelated", "")])
    r = svc.handle("호준이", "s1", None, lambda req: pytest.fail("조회하면 안 된다"))
    assert r.reply == svc.PERSON_ASK and "호준" not in r.reply


def test_guard_keeps_a_reply_without_the_name(monkeypatch):
    _no_classic(monkeypatch)
    _agent(monkeypatch, [], [("누구를 말씀하시는지 알려 주세요.", "unrelated", "")])
    r = svc.handle("호준이", "s1", None, lambda req: pytest.fail("조회하면 안 된다"))
    assert r.reply == "누구를 말씀하시는지 알려 주세요."


def test_recall_memo_answer_with_company_name_is_untouched(monkeypatch):
    """거래처 이름이 든 recall_memo 답은 A1이 건드리지 않는다 (실사용 81 기능 보호)."""
    from backend.tests.integration.test_chat_recall_memo import ask
    r, _ = ask(monkeypatch, "삼성 전화번호 뭐였지", "테스트로지스의 전화번호는 051-000-0001이에요.", {"topic": "contact", "query": None})
    assert r.reply == "테스트로지스의 전화번호는 051-000-0001이에요." and r.reply != svc.PERSON_ASK


def test_memo_question_without_tool_is_not_replaced_by_person_ask(monkeypatch):
    """모델이 도구 없이 잡담 답을 냈어도 저장 메모를 묻는 문장이면 이름 되풀이 막기가 대신 나서지 않는다."""
    monkeypatch.setattr(svc, "_load_memo", lambda uid: ([], {}))
    _no_classic(monkeypatch)
    _agent(monkeypatch, [], [("삼성 전화번호는 저장된 게 없어요.", "unrelated", "")])
    r = svc.handle("삼성 전화번호 뭐였지", "s1", None, lambda req: None, user_id="user-1")
    assert r.reply != svc.PERSON_ASK


def test_bl_and_ship_text_is_not_a_person_name():
    """B/L 자리표시자와 영문 배 이름은 한글 낱말만 보는 이름 찾기에 걸리지 않는다."""
    assert chat_ids.person_names("[BL1] 어디야?", KNOWN) == []
    assert chat_ids.person_names("HONGKONG VOYAGER 어디야?", KNOWN) == []
