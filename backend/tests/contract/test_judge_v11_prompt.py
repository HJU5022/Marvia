"""판정 프롬프트(marvia-judge.md)가 V11 금지 낱말을 전부 알려 주는지 본다.

V11(services/judge/validate.py)은 통관 진행 평가 문장을 걸러 판정을 다시 부르게 한다. 프롬프트가 금지 낱말을 모르면 재시도로 시간과 돈이 든다.
낱말 목록의 원본은 skills/customs-stages/rules.md 이므로, 거기서 읽은 값이 프롬프트에 모두 적혀 있는지 대조한다. 키 없이 돈다.
"""
from pathlib import Path

from backend.app.services.judge.rules import rule

PROMPT = Path(__file__).resolve().parents[2] / "app" / "prompts" / "marvia-judge.md"


def test_prompt_lists_every_v11_word():
    text = PROMPT.read_text(encoding="utf-8")
    for word in rule("customs_assessment_words") + rule("customs_subject_words"):
        assert word in text, f"marvia-judge.md does not list V11 word: {word}"
