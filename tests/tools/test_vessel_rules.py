"""배 식별 규칙과 스위치 시험 (계획 8b)."""

from marvia.config import Settings
from marvia.tools.rules import load_rules
from marvia.tools.vessel_match import Reason


def test_the_switch_is_off_unless_asked(monkeypatch):
    monkeypatch.delenv("MARVIA_VESSEL", raising=False)
    assert Settings(_env_file=None).vessel == "off"  # type: ignore[call-arg]
    monkeypatch.setenv("MARVIA_VESSEL", "on")
    assert Settings(_env_file=None).vessel == "on"  # type: ignore[call-arg]


def test_limits_and_texts_live_in_the_rules_file():
    rules = load_rules("vessel")
    assert rules["max_cargos"] == 3 and rules["max_candidates"] == 5 and rules["max_choices"] == 2
    # 선택 카드는 권고(배 없이 진행) 하나와 후보 둘까지: 설계 6.3의 선택지 2~3개
    assert 2 <= 1 + rules["max_choices"] <= 3
    assert "{token}" in rules["question"] and "{token}" in rules["assumption"]
    for text in (rules["question"], rules["assumption"], *rules["skip"].values()):
        assert (
            "{name}" not in text and "{call_sign}" not in text
        )  # 가정 글과 질문 머리에는 배 이름을 넣지 않는다


def test_every_reason_the_code_can_give_has_a_fixed_text():
    reasons = load_rules("vessel")["reasons"]
    # 배 확정 함수(8a)의 이유 전부와, 이 계획의 단계가 더하는 이유
    for name in Reason.__args__:  # type: ignore[attr-defined]
        assert name in reasons, name
    for name in (
        "no_clue",
        "lookup_failed",
        "over_cap",
        "another_question",
        "user_choice",
        "user_skipped",
        "no_answer",
    ):
        assert name in reasons, name
    labels = load_rules("vessel")["labels"]
    assert labels["no_grade"] == "등급 없음" and set(labels["eta_sources"]) == set(
        load_rules("verdict")["eta_priority"]
    )
