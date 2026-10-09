"""Skill 근거라고 낸 답에 Skill에 없는 핵심 낱말이 섞이면 3층(일반 설명)으로 낮춘다 (services/chat/chat.py skill_or_general).
재현: "B/L도 없고 포워더 연락 안 돼"에 Skill에 없는 "화물 인도증"이 꼬리표 없이 Skill 답처럼 나갔다."""
from backend.app.services.chat import chat as svc
from backend.tests.integration.test_chat_agent import KNOWLEDGE, QUOTE, _agent, agent_path  # noqa: F401 - agent_path는 autouse 픽스처
from backend.tests.integration.test_chat_tiers import _ask  # noqa: F401 - web_off는 픽스처


def test_skill_answer_with_outside_terms_gets_general_tag(monkeypatch):
    mixed = "포워더 도착 통지서의 배 이름과 항차로 확인하고, 화물 인도증 사본은 선사 고객센터에 요청해 보세요."
    _agent(monkeypatch, [], [(mixed, "skill", QUOTE)])
    r = _ask("포워더가 항차를 안 알려줘")
    assert r.reply == mixed  # 버리지 않고 일반 설명으로 내보낸다 (꼬리표는 없앴다)


def test_grounded_skill_answer_stays_untagged(monkeypatch):
    _agent(monkeypatch, [], [(KNOWLEDGE, "skill", QUOTE)])
    assert _ask("포워더가 항차를 안 알려줘").reply == KNOWLEDGE  # Skill에 있는 말만 쓴 답은 그대로 (1층)
