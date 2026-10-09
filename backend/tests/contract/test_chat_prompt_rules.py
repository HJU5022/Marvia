"""채팅 프롬프트 규칙 확인: 막연한 말에 날짜를 답하지 않기, 답은 항상 존댓말. 파일에 그 규칙 줄이 있는지만 본다."""
from pathlib import Path

PROMPT = (Path(__file__).resolve().parents[2] / "app" / "prompts" / "marvia-chat-agent.md").read_text(encoding="utf-8")


def test_vague_remark_rule_exists():
    assert "A vague remark or an emotion with no question" in PROMPT
    assert "only when the user asked about the date" in PROMPT


def test_polite_tone_rule_exists():
    assert "polite Korean ending in 요" in PROMPT and "never 습니다 or 입니다" in PROMPT  # 말투 통일


def test_unknown_person_rule_exists():
    """(트레이스 bc9c239a): 화면 화물과 이어지지 않는 사람·대상을 화물로 읽지 않고 도구 없이 되묻는다."""
    assert "Unknown person or thing" in PROMPT
    assert "never read it as the cargo on screen" in PROMPT


def test_follow_up_subject_scope_rule_exists():
    follow_up = (Path(__file__).resolve().parents[2] / "app" / "prompts" / "marvia-follow-up.md").read_text(encoding="utf-8")
    assert "If the subject of the question is not this cargo" in follow_up


def test_service_name_spelling_rule_exists():
    """v16: 서비스 이름 표기는 마르비아 하나로 고정한다 (services/chat/texts.py 고정 문구와 같은 철자)."""
    assert '"마르비아"' in PROMPT and 'never "마비아"' in PROMPT


def test_no_web_search_in_prompt():
    """v16: 웹 검색 도구를 없앴다 (docs/adr/0020). 프롬프트에 도구 이름과 web 답 종류가 남지 않는다."""
    assert "web_search" not in PROMPT
    assert "  - web:" not in PROMPT
