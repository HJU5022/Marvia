"""채팅 프롬프트 규칙 확인 (10-05): 막연한 말에 날짜를 답하지 않기, 답은 항상 존댓말. 파일에 그 규칙 줄이 있는지만 본다."""
from pathlib import Path

PROMPT = (Path(__file__).resolve().parents[2] / "app" / "prompts" / "marvia-chat-agent.md").read_text(encoding="utf-8")


def test_vague_remark_rule_exists():
    assert "A vague remark or an emotion with no question" in PROMPT
    assert "only when the user asked about the date" in PROMPT


def test_polite_tone_rule_exists():
    assert "polite Korean ending in 요" in PROMPT and "never 습니다 or 입니다" in PROMPT  # 10-07 말투 통일


def test_unknown_person_rule_exists():
    """10-07 (트레이스 bc9c239a): 화면 화물과 이어지지 않는 사람·대상을 화물로 읽지 않고 도구 없이 되묻는다."""
    assert "Unknown person or thing" in PROMPT
    assert "never read it as the cargo on screen" in PROMPT


def test_follow_up_subject_scope_rule_exists():
    follow_up = (Path(__file__).resolve().parents[2] / "app" / "prompts" / "marvia-follow-up.md").read_text(encoding="utf-8")
    assert "If the subject of the question is not this cargo" in follow_up
