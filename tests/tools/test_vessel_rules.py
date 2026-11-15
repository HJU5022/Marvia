"""배 식별 규칙과 스위치 시험 (계획 8b)."""

from marvia.config import Settings
from marvia.identify.models import CargoFacts, ToolError
from marvia.tools import shipfinder
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


def test_vessel_demo_cargos_are_made_up_and_cover_the_cases():
    # [왜] 배 식별 화면을 키 없이 보이려면 배로 이어지는 재생 화물이 있어야 한다. 기존 다섯 화물은 그대로 둔다
    from marvia.tools import mof
    from marvia.tools.ports import port
    from marvia.tools.unipass_replay import lookup_cargo

    seen = {}
    for n in range(1, 8):
        facts = lookup_cargo(f"TESTVSL000{n}")
        assert isinstance(facts, CargoFacts), n
        assert facts.port_code and facts.entry_date and (facts.vessel_name or "").startswith("TEST ")
        assert facts.mrn is None or facts.mrn.startswith("26TEST")
        seen[n] = facts
    busan = port("KRPUS")
    assert busan is not None and seen[1].entry_date is not None
    listed = mof.plans_near(busan, seen[1].entry_date)
    assert isinstance(listed, list)

    def report(n: int):
        mrn = seen[n].mrn
        return mof.plan_by_mrn(listed, mrn) if mrn else None

    assert (
        seen[1].mrn == "26TEST0001I" and (report(1) or object()).call_sign == "QQTST1"
    )  # MRN으로 호출부호에 닿는다
    assert seen[2].mrn is not None and report(2) is None  # MRN으로 닿지 못하고 같은 이름의 후보가 여럿
    assert seen[3].port_code == "KRINC"  # 확인 전 항만, 후보 없음
    assert (
        report(4) is not None and not report(4).call_sign
    )  # MRN의 신고에 호출부호가 없다: 서류로 확정하는 길
    assert seen[5].mrn is None  # 한 척인데 MRN이 없다: 서류가 맞아도 되묻는다
    assert seen[6].stage == "반입신고" and seen[6].mrn == seen[1].mrn  # 배에서 내린 화물
    assert (report(7) or object()).call_sign == "QQTWN"  # 호출부호가 같은 배가 둘이다
    hits = shipfinder.vessel_candidates(seen[4].vessel_name or "")
    assert isinstance(hits, list) and [h.mmsi for h in hits] == [999000004]  # 한 척, 서류는 맞고 위치는 없다
    assert isinstance(shipfinder.vessel_position(999000004), ToolError)
    five = shipfinder.vessel_candidates(seen[5].vessel_name or "")
    assert isinstance(five, list) and [h.mmsi for h in five] == [999000005]
    twins = shipfinder.vessel_candidates("QQTWN")
    assert isinstance(twins, list) and [h.mmsi for h in twins] == [999000007, 999000008]
    assert shipfinder.vessel_candidates(seen[3].vessel_name or "") == []
