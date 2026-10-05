"""채팅 프롬프트 규칙 확인 (10-05): 막연한 말에 날짜를 답하지 않기, 답은 항상 존댓말. 파일에 그 규칙 줄이 있는지만 본다."""
from pathlib import Path

PROMPT = (Path(__file__).resolve().parents[1] / "app" / "prompts" / "marvia-chat-agent.md").read_text(encoding="utf-8")


def test_vague_remark_rule_exists():
    assert "A vague remark or an emotion with no question" in PROMPT
    assert "only when the user asked about the date" in PROMPT


def test_polite_tone_rule_exists():
    assert "polite Korean ending in 습니다 or 요" in PROMPT
