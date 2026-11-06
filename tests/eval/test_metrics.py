"""평가 지표 시험 (done 3.2). 실행 결과 줄을 손으로 만들어 키 없이 돈다."""

from datetime import date

import pytest

from marvia.eval.dataset import Domain, Item
from marvia.eval.metrics import (
    agreement,
    behaviour_accuracy,
    bucket,
    calc_ok,
    compare_table,
    correct_citation,
    domain_table,
    false_sufficient,
    free_answer_score,
    human_faithful,
    matches,
    mrr,
    ragas_means,
    recall_at_k,
    stray_articles,
    summarize,
    top_article_share,
    trajectory_pass,
    trajectory_violations,
    unscored,
    unsupported,
    unsupported_all,
    wrong_evidence,
)

A = "L001556@20261002#"
DUTY = {"name": "관세 납부기한", "due": "2026-11-17"}


def item(id: str, **fields) -> Item:
    base = {"id": id, "group": "related", "kind": "시험", "question": "질문", "behaviour": ["answer"]}
    return Item.model_validate(base | fields)


def row(id: str, **fields) -> dict:
    base = {
        "id": id,
        "behaviour": "answer",
        "cited": [],
        "evidence": [],
        "retrieved": [],
        "calc": {},
        "seconds": 1.0,
    }
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


def test_recall_and_mrr_follow_the_rag_rank():
    rows = [
        row("R1", retrieved=[A + "제100조", A + "제241조.3항"]),  # 2위
        row("R2", retrieved=[A + "제100조"] * 9 + [A + "제9조.1항.1호"]),  # 10위: R@8 밖
    ]
    assert recall_at_k(rows, ITEMS, 8) == {"value": 0.5, "n": 2}
    assert mrr(rows, ITEMS) == {"value": round((1 / 2 + 1 / 10) / 2, 4), "n": 2}


def test_evidence_bundle_does_not_lift_retrieval_scores():
    # [왜] get_provision 근거는 점수 1.0이라 묶음 맨 앞에 선다. 검색 순위가 아니다
    rows = [row("R1", evidence=[A + "제241조.3항"], retrieved=[A + "제100조"])]
    assert recall_at_k(rows, ITEMS, 8) == {"value": 0.0, "n": 1}
    assert mrr(rows, ITEMS) == {"value": 0.0, "n": 1}


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


def test_compare_table_has_one_line_per_run():
    rows = [
        row("R1", cited=[A + "제241조.3항"], evidence=[A + "제241조.3항"], real_llm_calls=3, cost_usd=0.01)
    ]
    result = {
        "meta": {"loop": "agent", "model": "m", "k": 8, "tag": "ctx"},
        "summary": summarize(rows, ITEMS, 8),
    }
    lines = compare_table([result, result]).splitlines()
    assert len(lines) == 4  # 머리, 구분, 실행 둘
    assert lines[2].startswith("| agent (ctx) | m | 1.00 (1) | 0.00 (1) |")


def test_agreement_buckets_the_judge_score_like_the_human_grade():
    human = {"R1": 1.0, "R2": 0.5, "R3": 0.0, "R4": 1.0}
    judge = {"R1": 0.9, "R2": 0.6, "R3": 0.7, "R4": None}  # R3는 0.5 칸, R4는 못 쟀다
    assert bucket(0.8, [0.8, 0.5]) == 1.0 and bucket(0.49, [0.8, 0.5]) == 0.0
    assert agreement(human, judge, [0.8, 0.5]) == {"value": 0.6667, "n": 3, "mean_abs_diff": 0.3}


def test_ragas_means_leave_out_missing_and_nan_scores():
    scores = [
        {"faithfulness": 1.0},
        {"faithfulness": float("nan")},
        {"faithfulness": None},
        {"faithfulness": 0.5},
    ]
    assert ragas_means(scores, ["faithfulness"]) == {"faithfulness": {"value": 0.75, "n": 2, "missing": 2}}


def test_human_faithful_names_the_items_with_a_blank_or_odd_grade():
    assert human_faithful({"R1": {"faithful": 1}, "R2": {"faithful": 0.5}}) == {"R1": 1.0, "R2": 0.5}
    with pytest.raises(ValueError, match="R2.*R3"):
        human_faithful({"R1": {"faithful": 1}, "R2": {"faithful": None}, "R3": {"faithful": 0.7}})


def test_unscored_lists_human_items_without_a_judge_score():
    judge = {"R1": 0.9, "R2": None, "R3": float("nan")}
    assert unscored({"R1": 1.0, "R2": 1.0, "R3": 0.0, "R4": 1.0}, judge) == ["R2", "R3", "R4"]


def test_trajectory_checks_must_any_of_must_not_order_and_cap():
    spec = Item.model_validate(
        {
            "id": "T",
            "group": "related",
            "kind": "시험",
            "question": "q",
            "behaviour": ["answer"],
            "trajectory": {
                "must": ["calc_deadlines", "get_provision|search_law"],
                "must_not": ["ask_user"],
                "order": [["calc_deadlines", "get_provision"]],
                "max_calls": 3,
            },
        }
    ).trajectory
    never = ["watch_cargo"]
    assert trajectory_violations(["calc_deadlines", "get_provision"], spec, never, 12) == []
    assert trajectory_violations(
        ["get_provision", "calc_deadlines", "ask_user", "watch_cargo"], spec, never, 12
    ) == [
        "부르면 안 됨: ask_user",
        "부르면 안 됨: watch_cargo",
        "순서: calc_deadlines 다음에 get_provision",
        "호출 4번 > 상한 3",
    ]
    assert trajectory_violations(["search_law"], spec, never, 12) == ["불러야 함: calc_deadlines"]


def test_trajectory_pass_counts_only_agent_rows_without_errors():
    rows = [
        row("U1", loop="agent", tools=["decline"]),
        row("R1", loop="agent", tools=["watch_cargo"]),  # 저장소 밖 일을 했다
        row("R2", loop="agent", tools=[], error="APIError"),  # 오류 줄은 빼고 센다
        row("S1", loop="planner", tools=[]),
    ]
    assert trajectory_pass(rows, ITEMS, ["watch_cargo"], 12) == {"value": 0.5, "n": 2}


def test_rag_observations_from_the_rag_log_and_evidence_order():
    rag = [
        {"step": "grade", "sufficient": True, "units": [A + "제100조.1항"]},  # 정답 없이 "충분"
        {"step": "rewrite", "articles": ["제248조"]},  # 질문에도 정답에도 없는 조문
        {"step": "grade", "sufficient": True, "units": [A + "제241조.3항"]},
        {"step": "rewrite", "articles": ["제8조"]},  # also_ok 조문은 질문 밖이 아니다
    ]
    rows = [
        row("R1", rag=rag),
        row("S1", rag=[{"step": "grade", "sufficient": True, "units": [A + "제1조"]}]),
    ]
    assert stray_articles(rows, ITEMS) == {"value": 0.5, "n": 2}
    assert false_sufficient(rows, ITEMS) == {"value": 0.5, "n": 2}


def grade(*units: str) -> dict:
    return {"step": "grade", "sufficient": False, "units": list(units)}


def test_top_article_share_counts_only_the_first_grade_round():
    head = [A + "제27조.1항.1호"] * 7 + [A + "제20조.1항"]  # 8개 중 7개가 한 조문
    later = [A + "제1조", A + "제2조"]  # 둘째 묶음은 세지 않는다
    rows = [row("R1", rag=[grade(*head), grade(*later)]), row("R2", rag=[grade(A + "제1조", A + "제2조")])]
    got = top_article_share(rows, 8, 0.75)
    assert got == {"value": round((0.875 + 0.5) / 2, 4), "n": 2, "over": 1, "skipped": 0}


def test_top_article_share_short_head_and_rows_without_a_grade_round():
    short = [grade(A + "제9조.1항", A + "제9조.2항", A + "제10조")]  # 8개보다 짧은 첫 묶음
    rows = [row("R1", rag=short), row("R2", rag=[{"step": "rewrite", "articles": []}]), row("R3")]
    got = top_article_share(rows, 8, 0.75)
    assert got == {"value": round(2 / 3, 4), "n": 1, "over": 0, "skipped": 2}


def test_free_answer_score_finds_stage_date_and_article_in_any_common_form():
    domain = Domain(stage="반입신고", due=date(2026, 11, 26), article="관세법 제241조")
    text = "반입신고 단계라 2026년 11월 26일까지 신고해야 합니다 (관세법 241조 3항)."
    assert free_answer_score(text, domain) == {"stage": True, "due": True, "article": True}
    other = "11/26까지예요. 관세법 제241조의2에 따라."  # 단계 없음, 다른 날짜 꼴, 다른 조문
    assert free_answer_score(other, domain) == {"stage": False, "due": False, "article": False}
    assert free_answer_score("11월 26일", Domain(due=date(2026, 11, 26))) == {
        "stage": None,
        "due": True,
        "article": None,
    }


def test_domain_table_counts_hits_per_tool():
    items = {"D1": item("D1", domain={"due": "2026-11-17", "article": "관세법 제9조"}), "S1": ITEMS["S1"]}
    answers = {"Marvia": {"D1": "2026-11-17까지 (관세법 제9조제1항제1호)"}, "도구": {"D1": "보름 안에 내요"}}
    lines = domain_table(answers, items).splitlines()
    assert lines[2] == "| Marvia | 0/0 | 1/1 | 1/1 | 1 |" and lines[3] == "| 도구 | 0/0 | 0/1 | 0/1 | 1 |"


def test_ragas_means_score_faithfulness_apart_for_items_with_calc_lines():
    scores = [
        {"id": "R01", "faithfulness": 1.0, "context_recall": 1.0},
        {"id": "R12", "faithfulness": 0.0, "context_recall": 0.5},
    ]
    out = ragas_means(scores, ["faithfulness", "context_recall"], calc_ids={"R12"})
    # [왜] 계산·화물 줄은 ragas 맥락에 없어, 계산 문항의 충실도는 채점자 의견 차이가 아닌 이유로 낮다
    assert out["faithfulness"]["value"] == 1.0 and out["faithfulness"]["n"] == 1
    assert out["faithfulness_calc"]["value"] == 0.0 and out["faithfulness_calc"]["n"] == 1
    assert out["context_recall"]["value"] == 0.75 and out["context_recall"]["n"] == 2


def test_summary_rounds_the_seconds_median_to_one_decimal():
    rows = [row("R1", seconds=18.7), row("U1", seconds=18.9)]  # 가운데 값 18.799999999999997
    assert summarize(rows, ITEMS, 8)["seconds_median"] == 18.8


def test_cargo_count_lines_show_the_found_count_for_the_named_items():
    from marvia.eval.metrics import cargo_count_lines

    result = {
        "meta": {"loop": "agent", "model": "m"},
        "rows": [{"id": "R09", "cargo_count": 2}, {"id": "R10", "cargo_count": 1}, {"id": "R01"}],
    }
    assert cargo_count_lines([result], ["R09", "R10"]) == ["agent m: R09 2건, R10 1건"]
    assert cargo_count_lines([result], ["R01"]) == ["agent m: R01 (기록 없음)"]


def test_unsupported_all_counts_every_item_not_only_those_that_should_be_answered():
    # [왜] 답하지 않아야 할 문항(U01~U04)에서 근거 없이 답한 것은 기존 비율에 보이지 않았다 (R-058)
    rows = [row("R1", behaviour="unsupported"), row("S1"), row("U1", behaviour="unsupported")]
    assert unsupported(rows, ITEMS) == {"value": 0.5, "n": 2}
    assert unsupported_all(rows) == {"value": 0.6667, "n": 3}
    assert unsupported_all([]) == {"value": None, "n": 0}


def test_article_must_follow_the_law_name_directly():
    # [왜] 법령 이름과 조문 번호를 따로 찾으면 "관세법 시행령 제241조"가 "관세법 제241조"로 통과했다 (R-063)
    domain = Domain(article="관세법 제241조")

    def hit(text: str) -> bool:
        return free_answer_score(text, domain)["article"]

    assert hit("관세법 제241조에 따라") and hit("관세법제241조") and hit("관세법 241조 3항")
    assert not hit("관세법 시행령 제241조에 따라")
    assert not hit("관세법 시행규칙 제241조에 따라")
    assert not hit("관세법은 이렇고 제241조는 따로 있다")
    assert hit("관세법 시행령 제9조와 관세법 제241조")  # 둘 다 있으면 맞는 쪽을 찾는다
    assert free_answer_score("관세법 시행령 제241조", Domain(article="관세법 시행령 제241조"))["article"]


def test_article_after_a_quoted_law_name_counts():
    # [왜] 한국 법령 인용에서 가장 흔한 꼴은 「관세법」 제241조다
    domain = Domain(article="관세법 제241조")
    for text in ["「관세법」 제241조에 따라", "『관세법』제241조", '"관세법" 제241조', "'관세법' 제241조"]:
        assert free_answer_score(text, domain)["article"], text
    assert not free_answer_score("「관세법 시행령」 제241조에 따라", domain)["article"]
