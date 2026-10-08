"""웹 답의 근거 조각에 기관 이름(관세청)이 있어도 평범한 질문의 답은 버리지 않는다 (10-06 실측).
"B/L 번호는 어디에 있는 거야?"가 웹 근거 조각 "관세청 유니패스에 들어가셔서..." 때문에 BROKER_TOPIC에 걸려 고정 안내로 끝났다.
키 없이 돈다. 웹 글·주소는 모의값이다."""
import pytest

from backend.app.services.chat import chat as svc
from backend.app.services import llm
from backend.tests.integration.test_chat_agent import _agent, _no_classic, agent_path  # noqa: F401 - agent_path는 autouse 픽스처

TEXT = "B/L 번호만 알고 있으면 관세청 유니패스에 들어가셔서 번호를 입력합니다. 번호는 포워더가 보낸 도착 통지서에 적혀 있습니다."
RESULTS = [{"title": "B/L 번호 안내", "url": "https://a.example.test/bl", "text": TEXT}]
ANSWER = "B/L 번호는 포워더가 보낸 도착 통지서에서 확인할 수 있습니다."
QUOTE = "번호는 포워더가 보낸 도착 통지서에 적혀 있습니다"


def _run(monkeypatch, quote, answer):
    monkeypatch.setattr(llm, "web_search", lambda q: [dict(r) for r in RESULTS])
    monkeypatch.delenv("WEB_SEARCH", raising=False)
    _agent(monkeypatch, [("web_search", {"query": "선하증권 B/L 번호 위치"})], [(answer, "web", quote)])
    _no_classic(monkeypatch)
    return svc.handle("B/L 번호는 어디에 있는 거야?", "s1", None, lambda req: pytest.fail("조회하면 안 된다"))


def test_agency_name_in_quote_does_not_drop_web_answer(monkeypatch):
    quote = "B/L 번호만 알고 있으면 관세청 유니패스에 들어가셔서 번호를 입력합니다"
    r = _run(monkeypatch, quote, ANSWER)
    assert r.reply.startswith(ANSWER) and "웹 참고: " in r.reply


def test_duty_word_in_reply_is_still_dropped(monkeypatch):
    r = _run(monkeypatch, QUOTE, "이 번호가 있으면 세율을 알 수 있습니다.")
    assert "세율" not in r.reply and "웹 참고" not in r.reply
