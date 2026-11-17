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


# --- 켠 길 대 끈 길 비교: 기준마다 깨지는 쪽 (계획 8c R-186) ---

from marvia.eval.run import ship_values  # noqa: E402

ITEMS = {i.id: i for i in load_set(SET_V4_PATH).items}
OLD = [i for i in ITEMS.values() if not i.vessel_only]  # v3 30문항
NEW = [i for i in ITEMS.values() if i.vessel_only]
GOLD = [i for i in OLD if i.gold]  # 정답 근거가 있는 12문항


def rows(
    wrong: int = 0, wrong_cited: int = 0, wrong_new: int = 0, calls: int = 4, with_new: bool = False, **more
):
    """v3 30줄(앞 wrong줄은 틀린 행동, 정답 근거 문항 앞 wrong_cited줄은 인용 없음)과 켠 길이면 새 12줄."""
    out = []
    cited_wrong = {i.id for i in GOLD[:wrong_cited]}
    for n, item in enumerate(OLD):
        calc = item.calc
        out.append({
            "id": item.id, "behaviour": item.behaviour[0] if n >= wrong else "unsupported", "leak": False,
            "cited": [] if item.id in cited_wrong else list(item.gold), "evidence": [],
            "real_llm_calls": calls,
            "calc": {"deadlines": [{"name": d.name, "due": d.due.isoformat()} for d in calc.deadlines],
                     "reimport": calc.reimport} if calc else {},
            "cargo_count": item.identify.cargos if item.identify else 0,
            "stages": list(item.identify.stages) if item.identify else [],
        })  # fmt: skip
    if with_new:
        for n, item in enumerate(NEW):
            out.append({"id": item.id, "behaviour": item.behaviour[0] if n >= wrong_new else "unsupported",
                        "leak": False, "cited": [], "evidence": [], "real_llm_calls": calls,
                        **more})  # fmt: skip
    return out


def result(vessel: str, problems=None, **kw):
    return {
        "meta": {"vessel": vessel, "problems": problems or []},
        "rows": rows(with_new=vessel == "on", **kw),
    }


def compared(on: dict, off: dict | None = None, n: int = 3) -> dict:
    return compare_vessel([on] * n, [off or result("off")] * n, ITEMS)


def test_the_clean_runs_pass_every_gate():
    done = compared(result("on"))
    assert done["ok"] and len(OLD) == 30 and len(NEW) == 12 and len(GOLD) == 12
    assert done["off_floor"]["ok"] and done["off_floor"]["floor"] == 0.8333


def test_behaviour_accuracy_may_be_one_twelfth_lower_but_not_more():
    # v3 30문항에서 둘 틀리면 0.0667 낮아 통과, 셋이면 0.1이라 넘는다
    assert compared(result("on", wrong=2))["behaviour_accuracy"]["ok"]
    assert not compared(result("on", wrong=3))["behaviour_accuracy"]["ok"]
    assert compared(result("on"), result("off", wrong=3))["behaviour_accuracy"]["ok"]  # 켠 길이 높으면 통과


def test_the_correct_citation_gate_has_the_same_slack_direction():
    # 정답 근거 12문항에서 하나 놓치면 1/12이고 그 폭까지는 통과, 둘이면 넘는다
    assert compared(result("on", wrong_cited=1))["correct_citation"]["ok"]
    assert not compared(result("on", wrong_cited=2))["correct_citation"]["ok"]


def test_the_call_ratio_gate_fails_above_one_and_a_quarter():
    assert compared(result("on", calls=5))["calls_median"]["ok"]  # 정확히 1.25배
    assert not compared(result("on", calls=6))["calls_median"]["ok"]


def test_the_new_items_need_eighty_percent_and_nine_of_twelve_is_not_enough():
    assert compared(result("on", wrong_new=2))["new_items_behaviour_accuracy"]["ok"]  # 10/12
    assert not compared(result("on", wrong_new=3))["new_items_behaviour_accuracy"]["ok"]  # 9/12
    assert not compared(result("on", wrong_new=3))["ok"]


def test_each_zero_gate_fails_on_one_count():
    for key, extra in (("detector", {"detector": 1}), ("assertive", {"assertive": 1}),
                       ("cap_stopped", {"stopped": "llm_calls"}), ("leaks", {"ship_leak": True}),
                       ("errors", {"error": "APIError"})):  # fmt: skip
        done = compared(result("on", **extra))
        assert not done[key]["ok"] and not done["ok"], key


def test_an_invalid_off_run_is_counted_as_an_error():
    done = compared(result("on"), result("off", problems=["--vessel off인데 그래프가 다르다"]))
    assert not done["errors"]["ok"] and not done["ok"]


def test_the_unattributed_count_is_reported_but_never_added_to_the_criterion():
    # MC55의 비교 꼴: 귀속 못 한 문장이 많아도 통과 기준은 그대로고 수만 따로 보인다
    done = compared(result("on", detector_unattributed=4))
    assert done["ok"] and done["detector"]["value"] == 0 and done["unattributed_sentences"] == 4 * 12 * 3


def test_the_off_floor_is_reported_without_deciding_the_comparison():
    done = compared(result("on"), result("off", wrong=6))  # 끈 길 24/30 = 0.8
    assert not done["off_floor"]["ok"] and done["off_floor"]["runs"] == [0.8] * 3
    assert done["behaviour_accuracy"]["ok"]  # 켠 길이 높으니 비교는 통과다


def test_the_hit_sentences_are_listed_in_the_output():
    hits = {"on1/N01": ["[BL1]의 판정은 경계예요."]}
    done = compare_vessel([result("on")], [result("off")], ITEMS, hits)
    assert done["detector_hit_sentences"] == hits


def test_ship_values_include_the_customs_names_that_no_candidate_has():
    # 11-17 R-186(X10). 세관이 준 배 이름(TESTVSL0003의 TEST NO SHIP)은 어느 후보 파일에도 없다
    values = ship_values()
    assert "TEST NO SHIP" in values and "QQTST1" in values and "999000001" in values


def test_the_detector_needs_a_token_or_a_trigger_word_in_the_sentence():
    # 11-17 R-186(X11). 토큰도 등급·판정·확신 낱말도 없는 문장은 이름이 있어도 세지 않는다
    one = [ev("[BL1]", "순항", "확실")]
    assert verdict_detector("부분 환불은 어렵고 경계가 필요해요.", one)["count"] == 0
    assert verdict_detector("판정은 경계예요.", one)["count"] == 1
    assert verdict_detector("[BL1]은 경계예요.", one)["count"] == 1
