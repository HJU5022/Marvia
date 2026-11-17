"""켠 길의 판정 지표 시험 (계획 8c T9, CC11, D22). 키 없이 돈다."""

from datetime import date

from marvia.eval.dataset import SET_V4_PATH, ExpectVerdict, load_set
from marvia.eval.metrics import (
    assertive_violations,
    compare_vessel,
    ship_value_hits,
    verdict_detector,
    vessel_totals,
)
from marvia.graph.schemas import Draft
from marvia.graph.verify import verify


def ev(token: str, grade: str, confidence: str) -> ExpectVerdict:
    return ExpectVerdict(token=token, grade=grade, confidence=confidence)  # type: ignore[arg-type]


CAUTION = [ev("[BL1]", "주의", "부분")]
TWO = [ev("[BL1]", "주의", "부분"), ev("[BL2]", "경계", "확실")]


def test_the_metric_counts_a_wrong_grade_name_in_the_answer():
    found = verdict_detector("[BL1]의 등급은 순항이에요. [BL1]의 확신은 부분이에요.", CAUTION)
    assert found["count"] == 1 and found["sentences"] == ["[BL1]의 등급은 순항이에요."]
    assert verdict_detector("[BL1]의 등급은 주의, 확신은 부분이에요.", CAUTION)["count"] == 0


def test_the_metric_counts_assertive_words_for_a_partial_cargo():
    assert assertive_violations("[BL1]은 분명히 제때 와요.", CAUTION) == ["[BL1]은 분명히 제때 와요."]
    assert assertive_violations("[BL1]은 제때 올 것으로 보여요.", CAUTION) == []
    assert assertive_violations("[BL1]은 분명히 와요.", [ev("[BL1]", "순항", "확실")]) == []


def test_ship_values_count_as_leaks():
    assert ship_value_hits(["the ship is test cargo a"], ["TEST CARGO A", "QQTST1"]) == ["TEST CARGO A"]
    assert ship_value_hits(["nothing here"], ["TEST CARGO A"]) == []


def test_the_detector_counts_a_wrong_name_the_verifier_pattern_misses():
    # 검증자는 "등급" 바로 옆의 이름만 본다. "판정은 경계예요"는 지나가고 탐지기는 센다
    answer = "[BL1]의 판정은 경계예요."
    row = {
        "token": "[BL1]",
        "grade": "fine",
        "confidence": "partial",
        "trusted_eta": None,
        "margin_days": None,
    }
    verdict = Draft(answer=answer, citations=[], next_options=[], forwarder_message="")
    assert verify(verdict, [], {}, [], {}, date(2026, 9, 22), verdicts=[{**row, "schedule": None}]) == []
    assert verdict_detector(answer, CAUTION)["count"] == 1


def test_the_detector_lists_every_hit_sentence():
    answer = "[BL1]의 등급은 순항이에요. 괜찮아요. [BL1]의 확신은 확실이에요."
    found = verdict_detector(answer, CAUTION)
    assert found["count"] == 2 and found["sentences"] == [
        "[BL1]의 등급은 순항이에요.",
        "[BL1]의 확신은 확실이에요.",
    ]


def test_a_hit_that_looks_like_a_detector_error_still_counts():
    # "부분적으로"는 일상어지만 판정 낱말이 든 문장에서는 센다. 나중에 빼지 않는다 (사전 등록)
    assert (
        verdict_detector("[BL1]의 판정을 부분적으로 알려 드려요.", [ev("[BL1]", "순항", "확실")])["count"]
        == 1
    )


def test_the_detector_on_two_cargos_counts_a_tokenless_sentence_only_when_it_differs_from_every_cargo():
    assert verdict_detector("판정은 경계예요.", TWO)["count"] == 0  # 둘째 화물의 값이다
    assert verdict_detector("판정은 순항이에요.", TWO)["count"] == 1  # 어느 화물과도 다르다


def test_the_unattributed_count_is_reported_and_not_added_to_the_criterion():
    found = verdict_detector("판정은 경계예요. 확신은 부분이에요.", TWO)
    assert found["unattributed"] == 2 and found["count"] == 0


def test_the_vessel_comparison_applies_the_preregistered_criteria():
    items = {i.id: i for i in load_set(SET_V4_PATH).items}
    old = next(i for i in items.values() if not i.vessel_only)
    new = next(i for i in items.values() if i.vessel_only)

    def run(vessel, behaviour="answer", **more):
        row = {
            "id": old.id,
            "behaviour": behaviour,
            "real_llm_calls": 4,
            "leak": False,
            "cited": [],
            "evidence": [],
        }
        fresh = {**row, "id": new.id, "behaviour": new.behaviour[0], **more}
        return {"meta": {"vessel": vessel}, "rows": [row, fresh] if vessel == "on" else [row]}

    on, off = [run("on")] * 5, [run("off")] * 5
    done = compare_vessel(on, off, items)
    assert done["detector"] == {"value": 0, "verifier_form": 0, "ok": True} and done["leaks"]["ok"]
    assert done["calls_median"]["ok"] and done["new_items_behaviour_accuracy"]["ok"]
    bad = compare_vessel([run("on", detector=1)] * 5, off, items)
    assert not bad["detector"]["ok"] and not bad["ok"]
    assert not compare_vessel([run("on", ship_leak=True)] * 5, off, items)["leaks"]["ok"]
    assert not compare_vessel([run("on", assertive=1)] * 5, off, items)["assertive"]["ok"]
    assert vessel_totals([{"detector": 2}, {"detector": 1, "ship_leak": True}])["detector"] == 3
