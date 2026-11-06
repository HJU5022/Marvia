"""평가 지표 시험 (done 3.2). 실행 결과 줄을 손으로 만들어 키 없이 돈다."""

from marvia.eval.dataset import Item
from marvia.eval.metrics import (
    behaviour_accuracy,
    calc_ok,
    correct_citation,
    matches,
    mrr,
    recall_at_k,
    summarize,
    unsupported,
    wrong_evidence,
)

A = "L001556@20261002#"
DUTY = {"name": "관세 납부기한", "due": "2026-11-17"}


def item(id: str, **fields) -> Item:
    base = {"id": id, "group": "related", "kind": "시험", "question": "질문", "behaviour": ["answer"]}
    return Item.model_validate(base | fields)


def row(id: str, **fields) -> dict:
    base = {"id": id, "behaviour": "answer", "cited": [], "evidence": [], "calc": {}, "seconds": 1.0}
    return base | fields


ITEMS = {
    "R1": item("R1", gold=[A + "제241조.3항"], also_ok=[A + "제8조"]),
    "R2": item("R2", gold=[A + "제9조.1항"], calc={"deadlines": [DUTY]}),
    "S1": item("S1"),  # 정답 근거 없는 관련 문항 (화물 상태)
    "U1": item("U1", group="unrelated", behaviour=["decline"]),
    "B1": item("B1", group="blocked", behaviour=["choice", "answer"], calc={"reimport": "사실 부족"}),
}


def test_matches_counts_lower_units_but_not_look_alike_articles():
    assert matches(A + "제241조.3항", [A + "제241조"])
    assert matches(A + "제241조", [A + "제241조"])
    assert not matches(A + "제241조의2", [A + "제241조"])
    assert not matches(A + "제24조.1항", [A + "제241조"])


def test_citation_rates_skip_items_without_gold_and_count_unrelated_citations_as_wrong():
    rows = [
        row("R1", cited=[A + "제241조.3항", A + "제8조.1항"]),  # 정답 + also_ok
        row("R2", cited=[A + "제100조"]),  # 정답 없음, 틀린 인용 하나
        row("S1", cited=[A + "제100조"]),  # 정답 없는 관련 문항: 세지 않는다
        row("U1", behaviour="unsupported", cited=[A + "제241조.3항"]),  # 비관련: 인용하면 틀림
    ]
    assert correct_citation(rows, ITEMS) == {"value": 0.5, "n": 2}
    assert wrong_evidence(rows, ITEMS) == {"value": 0.5, "n": 4}


def test_answer_counts_as_right_behaviour_only_with_the_code_calc():
    asked = row("B1", behaviour="choice")
    guessed = row("B1", calc={"reimport": "서류검사 요건 충족"})
    honest = row("B1", calc={"reimport": "사실 부족"})
    assert behaviour_accuracy([asked, guessed, honest], ITEMS) == {"value": 0.6667, "n": 3}
    assert calc_ok(row("R2", calc={"deadlines": [DUTY]}), ITEMS["R2"])
    assert calc_ok(row("R1"), ITEMS["R1"]) is None  # 정답 계산이 없는 문항


def test_blocked_accuracy_looks_only_at_that_group():
    rows = [row("B1", behaviour="choice"), row("U1", behaviour="unsupported")]
    assert behaviour_accuracy(rows, ITEMS, "blocked") == {"value": 1.0, "n": 1}
    assert behaviour_accuracy(rows, ITEMS, "unrelated") == {"value": 0.0, "n": 1}


def test_unsupported_rate_counts_only_items_that_should_be_answered():
    rows = [row("R1", behaviour="unsupported"), row("S1"), row("U1", behaviour="unsupported")]
    assert unsupported(rows, ITEMS) == {"value": 0.5, "n": 2}


def test_recall_and_mrr_follow_the_evidence_order():
    rows = [
        row("R1", evidence=[A + "제100조", A + "제241조.3항"]),  # 2위
        row("R2", evidence=[A + "제100조"] * 9 + [A + "제9조.1항.1호"]),  # 10위: R@8 밖
    ]
    assert recall_at_k(rows, ITEMS, 8) == {"value": 0.5, "n": 2}
    assert mrr(rows, ITEMS) == {"value": round((1 / 2 + 1 / 10) / 2, 4), "n": 2}


def test_metric_without_items_is_none_not_zero():
    assert correct_citation([row("S1")], ITEMS) == {"value": None, "n": 0}
    assert mrr([], ITEMS) == {"value": None, "n": 0}


def test_summary_counts_errors_leaks_cost_and_calls():
    rows = [
        row("R1", real_llm_calls=5, cost_usd=0.01, leak=False),
        row("U1", behaviour="decline", real_llm_calls=1, cost_usd=0.002, error="APIError"),
        row("S1", real_llm_calls=9, cost_usd=None, leak=True),
    ]
    out = summarize(rows, ITEMS, 8)
    assert (out["n"], out["errors"], out["leaks"], out["cost_usd"]) == (3, 1, 1, 0.012)
    assert (out["llm_calls_median"], out["llm_calls_max"]) == (5, 9)
    assert out["behaviours"] == {"answer": 2, "decline": 1}
    assert out["recall_at_8"] == {"value": 0.0, "n": 1}


def test_summary_uses_the_same_statistics_for_both_loops():
    # [왜] 두 길 비교는 같은 자로 잰다: 실제 호출 중앙값·최대, 비용, 근거 있는 답, 상한 넘음 (R-040)
    rows = [
        row("R1", cited=[A + "제241조.3항"], llm_calls=9, real_llm_calls=9, cost_usd=0.004),
        # 그래프가 센 호출이 상한 20 + 작성자 2를 넘었다
        row("R2", calc={"deadlines": [DUTY]}, llm_calls=23, real_llm_calls=23, cost_usd=0.01),
        # 화물 사실만 있는 답: 근거 있는 답은 아니다
        row("S1", llm_calls=3, real_llm_calls=3, cost_usd=0.001),
    ]
    out = summarize(rows, ITEMS, 8)
    assert out["evidence_backed"] == {"value": 0.6667, "n": 3}
    assert (out["cap_breaches"], out["llm_calls_median"], out["llm_calls_max"]) == (1, 9, 23)
    assert (out["cost_per_item_mean"], out["cost_per_item_max"]) == (0.005, 0.01)


def test_evidence_backed_counts_only_answers_and_survives_error_rows():
    # [왜] 거절·되물음·안내 줄은 분모에 넣지 않는다. 오류 줄은 calc가 None이어도 터지지 않는다
    rows = [
        row("R1", cited=[A + "제241조.3항"]),
        row("S1"),
        row("R2", behaviour="unsupported"),  # 근거 없는 답: 분모에 들어가고 근거 있는 답이 아니다
        row("S1", behaviour="guide", cited=[A + "제8조.1항"]),  # 포워더 안내: 분모에서 뺀다
        row("U1", behaviour="decline"),
        row("B1", behaviour="choice"),
        row("R2", behaviour="error", calc=None),
    ]
    assert summarize(rows, ITEMS, 8)["evidence_backed"] == {"value": 0.3333, "n": 3}
    assert summarize([row("U1", behaviour="decline")], ITEMS, 8)["evidence_backed"] == {"value": None, "n": 0}


def test_wrong_evidence_counts_a_repeated_citation_once():
    rows = [row("R1", cited=[A + "제241조.3항"]), row("R2", cited=[A + "제100조", A + "제100조"])]
    assert wrong_evidence(rows, ITEMS) == {"value": 0.5, "n": 2}
