"""평가 지표 시험 (done 3.2). 실행 결과 줄을 손으로 만들어 키 없이 돈다."""

from datetime import date

import pytest

from marvia.eval.dataset import SET_V2_PATH, SET_V3_PATH, Domain, Item, Route, load_set
from marvia.eval.metrics import (
    agreement,
    behaviour_accuracy,
    behaviour_ok,
    bucket,
    calc_ok,
    cap_stops,
    compare_table,
    compare_tables,
    contract_adherence,
    correct_citation,
    domain_table,
    false_not_found,
    false_sufficient,
    floors,
    free_answer_score,
    gold_in_evidence,
    gold_without_search,
    human_faithful,
    matches,
    mrr,
    ragas_means,
    recall_at_k,
    routing_accuracy,
    set_view,
    spread,
    spread_groups,
    spread_table,
    stray_articles,
    summarize,
    top_article_share,
    trajectory_pass,
    trajectory_violations,
    unscored,
    unsupported,
    unsupported_all,
    with_base_behaviour,
    wrong_evidence,
)
from marvia.tools.rules import load_rules

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
        "leak": False,
        "llm_calls": None,
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


def test_trajectory_pass_counts_supervisor_rows_and_reads_subagent_visits():
    # [왜] 수퍼바이저 길(계획 7b)도 도구를 부른다. 넘기기는 "sub:이름"으로 적혀 궤적 조건에 쓸 수 있다
    items = {
        "R1": item("R1", trajectory={"must": ["research|sub:law"], "order": [["sub:law", "search_law"]]}),
        "R2": item("R2", trajectory={"must": ["research|sub:law"]}),
    }
    rows = [
        row("R1", loop="supervisor", tools=["sub:law", "search_law"]),
        row("R2", loop="supervisor", tools=["sub:cargo", "calc_deadlines"]),  # 법령으로 넘기지 않았다
        row("R1", loop="agent", tools=["research", "search_law"]),  # 같은 조건을 에이전트 길도 넘는다
    ]
    assert trajectory_pass(rows, items, [], 12) == {"value": 0.6667, "n": 3}


def test_routing_accuracy_checks_visited_subagents_against_must_and_may():
    # [왜] 기대 서브에이전트(계획 7b): must는 꼭 들러야 하고, may는 들러도 틀리지 않다. 그 밖은 틀린 길이다
    items = {
        "R1": item("R1", route={"must": ["cargo"], "may": ["law"]}),
        "U1": item("U1", route={}),  # 서브에이전트 없이 수퍼바이저가 끝내야 하는 문항
        "S1": item("S1"),  # 기대가 없는 문항은 세지 않는다
    }
    rows = [
        row("R1", loop="supervisor", visits=["cargo"]),
        row("R1", loop="supervisor", visits=["cargo", "law", "cargo"]),  # 다시 들러도 된다
        row("R1", loop="supervisor", visits=["law"]),  # 꼭 들러야 할 곳을 빠뜨렸다
        row("R1", loop="supervisor", visits=["cargo", "item"]),  # 기대 밖 서브에이전트
        row("U1", loop="supervisor", visits=[]),
        row("U1", loop="supervisor", visits=["law"]),
        row("S1", loop="supervisor", visits=["law"]),
        row("R1", loop="supervisor", visits=[], error="APIError"),  # 오류 줄은 뺀다
        row("R1", loop="agent", visits=[]),  # 다른 길은 뺀다
    ]
    assert routing_accuracy(rows, items) == {"value": 0.5, "n": 6}
    assert routing_accuracy([row("R1", loop="agent", visits=[])], items) == {"value": None, "n": 0}


def test_summary_reports_routing_only_for_supervisor_rows():
    rows = [row("R1", loop="supervisor", visits=["law"], tools=["sub:law"], llm_calls=3)]
    items = ITEMS | {"R1": ITEMS["R1"].model_copy(update={"route": Route(must=["law"])})}
    assert summarize(rows, items, 8)["routing"] == {"value": 1.0, "n": 1}
    agent = [row("R1", loop="agent", tools=[], llm_calls=3)]
    assert summarize(agent, items, 8)["routing"] == {"value": None, "n": 0}


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
    assert hit("관세법 시행령 제9조와 관세법 제241조")  # 둘 다 있으면 맞는 쪽을 찾는다
    assert free_answer_score("관세법 시행령 제241조", Domain(article="관세법 시행령 제241조"))["article"]


def test_article_after_a_quoted_law_name_counts():
    # [왜] 한국 법령 인용에서 가장 흔한 꼴은 「관세법」 제241조다
    domain = Domain(article="관세법 제241조")
    for text in ["「관세법」 제241조에 따라", "『관세법』제241조", '"관세법" 제241조', "'관세법' 제241조"]:
        assert free_answer_score(text, domain)["article"], text
    assert not free_answer_score("「관세법 시행령」 제241조에 따라", domain)["article"]


def test_summarize_refuses_a_row_missing_a_required_field_instead_of_counting_zero():
    # [왜] 칸이 빠진 줄을 0(새는 번호 없음, 호출 없음)으로 세면 문이 조용히 통과한다 (R-063)
    for field in ("leak", "llm_calls"):
        bad = row("R1")
        del bad[field]
        with pytest.raises(ValueError, match=f"R1.*{field}"):
            summarize([bad], ITEMS, 8)


def test_cap_breaches_uses_the_larger_of_the_graph_count_and_the_real_count():
    # [왜] 오류 줄은 llm_calls가 None이지만 real_llm_calls는 이미 상한을 넘었을 수 있다
    over = row("R1", llm_calls=None, real_llm_calls=23)
    assert summarize([over, row("S1", llm_calls=3, real_llm_calls=3)], ITEMS, 8)["cap_breaches"] == 1


HEADING = "관세법 > 제9장 통관 > 제241조(수출ㆍ수입 또는 반송의 신고) [L001556@20261002#제241조.3항]"


@pytest.mark.parametrize(
    ("text", "article", "expected"),
    [
        (HEADING, "관세법 제241조", True),  # Marvia 자신의 인용 줄
        ("관세법 시행령 > 제9장 통관 > 제241조(신고)", "관세법 제241조", False),
        ("관세법 제241조 및 제9조", "관세법 제9조", True),
        ("관세법 제241조, 제226조", "관세법 제226조", True),
        ("관세법 제226조와 식물방역법 제10조", "관세법 제10조", False),
        ("관세법 제226조와 식물방역법 제10조", "관세법 제226조", True),
        ("**관세법** 제226조와 **식물방역법** 제10조", "관세법 제10조", False),
        ("**관세법** 제241조", "관세법 제241조", True),
        ("관세법: 제241조", "관세법 제241조", True),
        ("관세법 시행령 제241조", "관세법 제241조", False),
        ("「관세법 시행령」 제241조", "관세법 제241조", False),
        ("관세법은 이렇고, 관세법 시행령 제241조는", "관세법 제241조", False),
        ("「관세법」 제241조에 따라", "관세법 제241조", True),
        ("관세법 제241조의2", "관세법 제241조", False),
        ("구관세법 제241조", "관세법 제241조", False),
        ("관세법 제3조입니다. 제9조는 다른 법의 것이에요", "관세법 제9조", False),
        ("관세법\n제9조", "관세법 제9조", True),  # 줄바꿈 하나로는 범위가 끝나지 않는다
        ("관세법 제226조\n\n식물방역법 제10조", "관세법 제10조", False),
        ("관세법 제226조\n\n제10조는 다른 문단", "관세법 제10조", False),  # 빈 줄이 문단 끝이다
        ("관세법 제226조와 보세화물관리에 관한 고시 제10조", "관세법 제10조", False),
        ("관세법 제241조 및 「보세화물 관리에 관한 고시」 제9조", "관세법 제9조", False),
        ("관세법에 따른 신고방법은 제241조에 있다", "관세법 제241조", True),
        ("### 관세법\n- 제241조(수출ㆍ수입 또는 반송의 신고)", "관세법 제241조", True),
        ("관세법 제226조와 식물방역법 제10조", "관세법 제226조", True),
    ],
)
def test_article_is_looked_for_inside_the_scope_of_the_same_law(text, article, expected):
    assert free_answer_score(text, Domain(article=article))["article"] is expected


def test_every_corpus_heading_counts_for_its_own_law_and_article():
    # [왜] Marvia는 인용 줄에 근거의 제목 경로를 쓴다. 그 줄이 자기 법령·조문으로 세어져야 한다 (RI-1)
    import json
    import re

    from marvia.eval.dataset import CORPUS_UNITS

    misses = []
    for path in sorted(CORPUS_UNITS.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            unit = json.loads(line)
            found = re.search(r"#(제\d+조(?:의\d+)?)", unit["unit_id"])
            if found:
                article = f"{unit['law_name']} {found.group(1)}"
                if not free_answer_score(unit["heading"], Domain(article=article))["article"]:
                    misses.append((unit["unit_id"], unit["heading"]))
    assert misses == []


def test_identify_expectation_needs_the_same_cargo_count_and_stages():
    want = item("I1", identify={"cargos": 2, "stages": ["반입신고", "수입신고"]})
    ok = row("I1", cargo_count=2, stages=["수입신고", "반입신고"])  # 순서는 상관없다
    assert behaviour_ok(ok, want)
    assert not behaviour_ok(ok | {"cargo_count": 1}, want)
    assert not behaviour_ok(ok | {"stages": ["반입신고", "반입신고"]}, want)
    assert not behaviour_ok(row("I1"), want)  # 칸이 없는 옛 줄은 맞다고 보지 않는다
    assert behaviour_ok(row("S1"), ITEMS["S1"])  # identify가 없으면 행동만 본다


def test_not_found_lead_on_an_item_that_should_be_answered_is_wrong():
    # [왜] "없음"을 남발해 점수가 오르는 길을 막는다
    assert not behaviour_ok(row("S1", behaviour="not_found"), ITEMS["S1"])
    honest = item("H1", group="unrelated", behaviour=["not_found", "partial"])
    assert behaviour_ok(row("H1", behaviour="not_found"), honest)
    assert not behaviour_ok(row("H1", behaviour="unsupported"), honest)


def test_false_not_found_counts_not_found_rows_on_items_that_do_not_expect_it():
    items = ITEMS | {"H1": item("H1", group="unrelated", behaviour=["not_found", "partial"])}
    rows = [row("S1", behaviour="not_found"), row("R1"), row("H1", behaviour="not_found")]
    assert false_not_found(rows, items) == {"value": 0.5, "n": 2, "count": 1}  # S1, R1 중 S1
    assert false_not_found([row("H1", behaviour="not_found")], items) == {"value": None, "n": 0, "count": 0}
    summary = summarize([row("S1", behaviour="not_found")], items, 8)
    assert summary["false_not_found"]["count"] == 1 and "없다고 잘못 답함" in compare_table(
        [{"meta": {"loop": "agent", "model": "m", "k": 8}, "summary": summary}]
    )


def test_base_behaviour_scores_a_v2_row_the_way_v1_would():
    v1_item = item("U1x", group="unrelated", behaviour=["unsupported", "partial"])
    rows = [row("U1x", behaviour="not_found", behaviour_base="unsupported")]
    assert behaviour_accuracy(rows, {"U1x": v1_item}) == {"value": 0.0, "n": 1}
    assert behaviour_accuracy(with_base_behaviour(rows), {"U1x": v1_item}) == {"value": 1.0, "n": 1}
    old = row("S1")  # behaviour_base가 없는 v1 줄은 그대로다
    assert with_base_behaviour([old]) == [old]
    assert rows[0]["behaviour"] == "not_found"  # 원본은 바꾸지 않는다


def _result(tag, sha, loop="agent", model="m", commit="c1", **summary):
    return {
        "meta": {
            "loop": loop,
            "model": model,
            "tag": tag,
            "set": "v2",
            "set_sha256": sha,
            "commit": commit,
            "k": 8,
        },
        "summary": summary,
    }


def test_spread_gives_mean_min_max_and_denominators_for_each_shared_metric():
    runs = [
        {"errors": 0, "mrr": {"value": 0.4, "n": 10}, "only_here": 1},
        {"errors": 2, "mrr": {"value": 0.6, "n": 10}},
        {"errors": 1, "mrr": {"value": None, "n": 0}, "behaviours": {"answer": 3}},
    ]
    out = spread(runs)
    assert out["errors"] == {"mean": 1.0, "min": 0, "max": 2, "runs": 3, "n": []}
    # [왜] 못 잰 실행(None)은 평균에서 빼고, 몇 번 쟀는지는 runs로 보인다
    assert out["mrr"] == {"mean": 0.5, "min": 0.4, "max": 0.6, "runs": 2, "n": [10]}
    assert "only_here" not in out and "behaviours" not in out  # 모든 실행에 있고 숫자인 지표만


def test_spread_groups_by_loop_model_commit_and_graph_and_refuses_mixed_set_files():
    a = [_result("v2r1", "aa"), _result("v2r2", "aa"), _result("x", "aa", loop="planner")]
    groups = spread_groups(a)
    # [왜] 옛 결과 파일에는 meta.graph가 없다. "off"로 묶어 지금 묶음이 바뀌지 않는다
    assert sorted(groups) == [("agent", "m", "c1", "off", "direct"), ("planner", "m", "c1", "off", "direct")]
    assert len(groups[("agent", "m", "c1", "off", "direct")]) == 2
    # [왜] 같은 길·모델·평가셋이어도 커밋이 다르면 다른 코드의 결과라 따로 센다
    apart = spread_groups([_result("v2r1", "aa"), _result("v2r2", "aa", commit="c2")])
    assert sorted(apart) == [("agent", "m", "c1", "off", "direct"), ("agent", "m", "c2", "off", "direct")]
    # [왜] 설정 A(off)와 B(on)는 같은 커밋에서 돈다. 한 평균으로 섞으면 비교가 사라진다 (계획 3b)
    off, on = _result("3bA-t1", "aa"), _result("3bB-t1", "aa")
    on["meta"]["graph"] = "on"
    split = spread_groups([off, on])
    assert sorted(split) == [("agent", "m", "c1", "off", "direct"), ("agent", "m", "c1", "on", "direct")]
    assert "그래프 on" in spread_table([on], "aa", {})
    assert "그래프 off" in spread_table([off], "aa", {})
    # [왜] 같은 커밋·설정이라도 검색 길(direct·mcp)이 다르면 graph_added의 뜻이 달라 따로 센다.
    #      옛 결과 파일에는 meta.rag_via가 없다(그때는 direct뿐이었다)
    via = _result("v2r3", "aa")
    via["meta"]["rag_via"] = "mcp"
    both = spread_groups([_result("v2r1", "aa"), via])
    assert sorted(both) == [("agent", "m", "c1", "off", "direct"), ("agent", "m", "c1", "off", "mcp")]
    assert "검색 mcp" in spread_table([via], "aa", {}) and "검색 direct" in spread_table([off], "aa", {})
    bad = _result("3bA-t2", "aa")
    bad["meta"]["problems"] = ["leaks 1"]
    with pytest.raises(ValueError, match="무효 실행"):
        spread_groups([off, bad])
    with pytest.raises(ValueError, match="평가셋 파일이 다르다"):
        spread_groups([_result("v2r1", "aa"), _result("v2r2", "bb")])


def test_spread_table_names_the_files_and_uses_the_report_labels():
    group = [_result("v2r1", "aa"), _result("v2r2", "aa")]
    stats = spread(
        [{"behaviour_accuracy": {"value": 0.5, "n": 4}, "false_not_found": {"value": 0.0, "n": 9}}] * 2
    )
    text = spread_table(group, "aa", stats)
    assert "v2r1" in text and "v2r2" in text and "c1" in text  # 어떤 파일 어느 커밋을 평균했나
    assert "행동 정확도" in text and "없다고 잘못 답함" in text  # report와 같은 이름
    assert "behaviour_accuracy" not in text and "false_not_found" not in text


def test_set_view_names_the_set_and_tells_a_v1_view_of_a_v2_run_from_a_foreign_file():
    v2_rows = [{"id": "U05", "behaviour_base": "unsupported"}]
    own = set_view({"set": "v2", "set_sha256": "b" * 64}, v2_rows, "v2", "b" * 64)
    assert own == ("v2 (sha bbbbbbbbbbbb)로 채점", False)
    view = set_view({"set": "v2", "set_sha256": "b" * 64}, v2_rows, "v1", "a" * 64)
    assert view[1] is False and "v1 기준으로 본 v2 실행" in view[0]
    # [왜] behaviour_base가 없는 줄이나 v2가 아닌 파일의 결과는 옛 결과 경고를 그대로 낸다
    assert set_view({"set": "v2", "set_sha256": "b" * 64}, [{"id": "U05"}], "v1", "a" * 64)[1] is True
    assert set_view({"set": "v1", "set_sha256": "c" * 64}, v2_rows, "v1", "a" * 64)[1] is True
    assert set_view({"set": "v1", "set_sha256": "a" * 64}, [{"id": "R01"}], "v1", "a" * 64)[1] is False


def test_a_run_on_v2_or_v3_can_be_read_by_the_other_standard_without_a_warning():
    # [왜] v3는 v2와 질문이 같고 채점 칸만 다르다. 줄에는 관찰한 값(인용, 근거, 도구)만 있어
    #      같은 줄을 두 기준으로 셀 수 있다. 다른 판(v1)과는 전처럼 경고한다 (계획 7b)
    v3_run = {"set": "v3", "set_sha256": "c" * 64}
    assert set_view(v3_run, [], "v2", "b" * 64) == (
        "v2 기준으로 본 v3 실행 (실행 판 v3 sha cccccccccccc, 채점 v2 sha bbbbbbbbbbbb)",
        False,
    )
    v2_run = {"set": "v2", "set_sha256": "b" * 64}
    assert set_view(v2_run, [], "v3", "c" * 64)[0].startswith("v3 기준으로 본 v2 실행")
    assert set_view(v2_run, [], "v3", "c" * 64)[1] is False
    assert set_view(v3_run, [], "v1", "a" * 64)[1] is True
    assert set_view({"set": "v1", "set_sha256": "a" * 64}, [], "v3", "c" * 64)[1] is True


def test_the_same_row_scores_differently_by_the_v2_and_v3_gold():
    v2 = {i.id: i for i in load_set(SET_V2_PATH).items}
    v3 = {i.id: i for i in load_set(SET_V3_PATH).items}
    annex = "L012500@20260930#별표9.2호.가목.7)"  # 재수입 서류검사 대상을 정한 별표 단위
    rows = [row("R07", cited=[annex], evidence=[annex], retrieved=[annex])]
    assert correct_citation(rows, v2)["value"] == 0.0 and correct_citation(rows, v3)["value"] == 1.0
    assert wrong_evidence(rows, v2)["value"] == 1.0 and wrong_evidence(rows, v3)["value"] == 0.0
    assert recall_at_k(rows, v2, 8)["value"] == 0.0 and recall_at_k(rows, v3, 8)["value"] == 0.5


def test_floors_add_the_false_not_found_ceiling_only_for_a_v2_gate():
    metric = {"value": 0.8, "n": 10}
    summary = {key: metric for key in ["correct_citation", "behaviour_accuracy", "blocked_accuracy"]}
    summary |= {"calc_accuracy": metric, "mrr": metric, "recall_at_8": metric, "trajectory": metric}
    summary |= {"wrong_evidence": metric, "unsupported": {"value": 0.0, "n": 16}}
    summary |= {"false_not_found": {"value": 0.0, "n": 20, "count": 0}}
    assert "false_not_found" not in floors(summary, 8)  # v1 문은 그대로
    assert floors(summary, 8, "v2")["false_not_found"] == {"max": 0.05}  # 한 문항(1/20)만큼
    summary["false_not_found"] = {"value": None, "n": 0, "count": 0}
    assert "false_not_found" not in floors(summary, 8, "v2")


def test_runs_measured_through_the_cli_are_never_averaged_with_api_runs():
    api, cli = _result("t1", "aa"), _result("c1", "aa")
    cli["meta"]["llm_via"] = "cli"
    # [왜] 옛 결과 파일에는 meta.llm_via가 없다. 그때는 API뿐이었다
    with pytest.raises(ValueError, match="LLM 길이 다르다"):
        spread_groups([api, cli])
    assert len(spread_groups([cli, cli])) == 1
    assert "LLM cli" in spread_table([cli], "aa", {}) and "LLM api" in spread_table([api], "aa", {})


def test_gold_items_that_never_searched_are_counted_so_a_quiet_tool_failure_shows():
    # [왜] 도구 길이 조용히 죽은 실행은 오류 0으로 끝났다(11-12).
    #      근거가 있어야 할 문항이 검색·조회 없이 끝난 수를 센다
    rows = [
        row("R1", loop="agent", tools=["write_todos"]),  # 정답 근거 문항인데 검색·조회 0
        row("R2", loop="agent", tools=["lookup_cargo", "get_provision"]),  # 조문 조회도 조회다
        row("S1", loop="agent", tools=[]),  # 정답 근거 없는 문항: 세지 않는다
        row("B1", loop="agent", tools=[]),
    ]
    assert gold_without_search(rows, ITEMS, ["search_law", "get_provision", "research"]) == {
        "value": 1,
        "n": 2,
        "ids": ["R1"],
    }
    # 오류 줄(errors가 센다)과 계획자 길(도구를 부르지 않는다)은 뺀다. 줄이 없으면 못 잰 것이다
    others = [row("R1", loop="agent", tools=[], error="CLIFailed"), row("R2", loop="planner", tools=[])]
    assert gold_without_search(others, ITEMS, ["search_law"]) == {"value": None, "n": 0, "ids": []}
    # 수퍼바이저 길(계획 7b)도 센다. 서브에이전트 안에서 부른 검색은 줄의 tools에 풀려 있다
    routed = [
        row("R1", loop="supervisor", tools=["sub:law", "search_law"]),
        row("R2", loop="supervisor", tools=["sub:cargo", "calc_deadlines"]),  # 넘겼지만 검색·조회 0
    ]
    assert gold_without_search(routed, ITEMS, ["search_law", "get_provision"])["ids"] == ["R2"]
    summary = summarize(rows, ITEMS, 8)
    assert summary["gold_without_search"]["value"] == 1
    result = {"meta": {"loop": "agent", "model": "m", "k": 8}, "summary": summary}
    assert "근거 문항 중 검색·조회 0" in compare_table([result])


def test_contract_adherence_is_first_try_structured_calls_over_all_structured_calls():
    rows = [
        row("R1", contract={"calls": 6, "first_try": 6}),
        row("R2", contract={"calls": 4, "first_try": 3}),
        row("S1"),  # 칸이 없는 옛 줄은 세지 않는다
    ]
    assert contract_adherence(rows) == {"value": 0.9, "n": 10, "no_answer": 0, "unknown": 0, "requests": {}}
    assert contract_adherence([row("S1")])["value"] is None
    # 분모에서 뺀 호출 수, 알 수 없음, 구조화 호출마다의 API 요청 수 분포를 비율 옆에 낸다
    more = [
        row("R1", contract={"calls": 4, "first_try": 3, "no_answer": 2, "unknown": 1, "requests": {"2": 3}}),
        row("R2", contract={"calls": 1, "first_try": 0, "no_answer": 0, "unknown": 0, "requests": {"3": 1}}),
    ]
    want = {"value": 0.6, "n": 5, "no_answer": 2, "unknown": 1, "requests": {"2": 3, "3": 1}}
    assert contract_adherence(more) == want
    assert summarize(more, ITEMS, 8)["contract_adherence"] == want


def test_gold_in_evidence_counts_items_whose_writer_bundle_holds_a_gold_unit():
    # [왜] R@k는 첫 검색 묶음(retrieved)만 센다. 나중 검색이나 조문 조회로 정답을 찾은 문항은 여기서 보인다
    rows = [
        row("R1", retrieved=[], evidence=[A + "제100조", A + "제241조.3항"]),  # 조문 조회로 찾았다
        row("R2", retrieved=[A + "제9조.1항"], evidence=[A + "제100조"]),  # 작성자는 정답을 못 봤다
        row("S1", evidence=[A + "제241조.3항"]),  # 정답 근거 없는 문항: 세지 않는다
    ]
    assert gold_in_evidence(rows, ITEMS) == {"value": 0.5, "n": 2}
    assert recall_at_k(rows, ITEMS, 8) == {"value": 0.5, "n": 2}
    assert summarize(rows, ITEMS, 8)["gold_in_evidence"] == {"value": 0.5, "n": 2}
    result = {"meta": {"loop": "agent", "model": "m", "k": 8}, "summary": summarize(rows, ITEMS, 8)}
    assert "근거 묶음 안 정답" in compare_table([result])


def test_gold_in_evidence_is_the_share_of_gold_units_covered_like_recall():
    # [왜] R@k와 같은 꼴(정답 근거를 덮은 몫의 문항 평균)이어야 둘을 나란히 볼 수 있다.
    #      정답이 둘인데 하나만 봤으면 0.5다
    items = ITEMS | {"R3": item("R3", gold=[A + "제241조.3항", A + "제9조.1항"])}
    rows = [row("R3", evidence=[A + "제241조.3항"]), row("R1", evidence=[A + "제241조.3항"])]
    assert gold_in_evidence(rows, items) == {"value": 0.75, "n": 2}


def test_cap_stops_counts_rows_that_ended_at_the_llm_call_cap():
    cap = load_rules("agent")["loop"]["max_llm_calls"]
    rows = [
        row("R1", stopped="llm_calls", behaviour="partial"),  # 에이전트 루프가 상한에서 멈췄다
        # 조사 서브에이전트가 상한에 닿았다. 옛 줄(stopped 칸 없음)도 실패 기록으로 센다
        row("R2", failed=[f"research: LLM 호출 한도({cap}회)에 닿았어요"]),
        row(
            "S1", loop="planner", behaviour="partial", llm_calls=cap
        ),  # 계획자 길은 표시 없이 부분 답으로 간다
        row("U1", stopped="llm_failed", behaviour="partial", llm_calls=3),  # 모델 실패는 상한이 아니다
        row("B1", llm_calls=cap),  # 상한만큼 부르고 답을 냈다
    ]
    assert cap_stops(rows) == 3
    assert summarize(rows, ITEMS, 8)["cap_stops"] == 3
    # 수퍼바이저 길(계획 7b): 수퍼바이저든 서브에이전트든 상한에 닿으면 stopped 칸과 실패 기록에 남는다
    supervisor = [
        row("R1", loop="supervisor", stopped="llm_calls", behaviour="partial", llm_calls=cap),
        row(
            "R2", loop="supervisor", stopped="llm_calls", failed=[f"cargo: LLM 호출 한도({cap}회)에 닿았어요"]
        ),
        row("S1", loop="supervisor", behaviour="answer", llm_calls=cap),  # 상한만큼 부르고 답을 냈다
    ]
    assert cap_stops(supervisor) == 2


def spent(id: str, calls: int, tokens_in: int, **fields) -> dict:
    tokens = {"m": {"in": tokens_in, "out": tokens_in // 10}}
    return row(id, real_llm_calls=calls, tokens=tokens, cost_usd=0.01, **fields)


def test_summary_gives_p50_and_p95_of_llm_calls_and_tokens_per_item():
    # 가까운 순위 법: 값 20개의 p50은 10번째, p95는 19번째 값이다
    rows = [spent("R1", calls=n, tokens_in=n * 1000) for n in range(1, 21)]
    summary = summarize(rows, ITEMS, 8)
    assert (summary["llm_calls_p50"], summary["llm_calls_p95"]) == (10, 19)
    assert (summary["tokens_in_p50"], summary["tokens_in_p95"]) == (10000, 19000)
    assert (summary["tokens_out_p50"], summary["tokens_out_p95"]) == (1000, 1900)
    assert summarize([row("R1")], ITEMS, 8)["llm_calls_p95"] is None  # 호출 수가 없는 줄뿐이면 못 잰 것이다
    result = {"meta": {"loop": "agent", "model": "m", "k": 8}, "summary": summary}
    assert "LLM 호출 p50·p95" in compare_table([result]) and "| 10·19 |" in compare_table([result])


def test_cost_and_time_are_reported_only_for_runs_measured_through_the_api():
    label = load_rules("eval")["summary"]["not_measured"]
    api = summarize([spent("R1", calls=3, tokens_in=1000, llm_via="api")], ITEMS, 8)
    assert api["cost_usd"] == 0.01 and api["seconds_median"] == 1.0
    old = summarize([spent("R1", calls=3, tokens_in=1000)], ITEMS, 8)  # 옛 줄에는 llm_via가 없다(API)
    assert old["cost_usd"] == 0.01
    # [왜] claude -p 줄은 청구액이 없고 시간에 CLI 시작 시간이 섞인다. 숫자 대신 재지 않았다고 낸다
    cli = summarize([spent("R1", calls=3, tokens_in=1000, llm_via="cli") | {"cost_usd": None}], ITEMS, 8)
    for key in ("cost_usd", "cost_per_item_mean", "cost_per_item_max", "seconds_median"):
        assert cli[key] == label
    assert cli["llm_calls_p50"] == 3  # 호출 수와 토큰은 cli 줄에서도 센다
    result = {"meta": {"loop": "agent", "model": "m", "k": 8}, "summary": cli}
    assert f"| {label} | {label} |" in compare_table([result])
    assert "cost_usd" not in spread([cli, cli])  # 숫자가 아닌 칸은 평균에 넣지 않는다


def path_result(via: str | None, tag: str) -> dict:
    pack = {"calls": 10, "first_try": 9, "no_answer": 2, "unknown": 1, "requests": {"2": 9, "3": 1}}
    summary = summarize([row("R1", contract=pack, real_llm_calls=3, tokens={})], ITEMS, 8)
    meta = {"loop": "agent", "model": "m", "k": 8, "tag": tag} | ({"llm_via": via} if via else {})
    return {"meta": meta, "summary": summary}


def test_report_table_shows_contract_adherence_with_its_denominator_and_left_out_calls():
    table = compare_table([path_result("cli", "c1")])
    assert "출력 계약 준수율(분모) · 뺀 호출 · 알 수 없음" in table and "| 0.90 (10) · 2 · 1 |" in table
    old = {"meta": {"loop": "agent", "model": "m", "k": 8}, "summary": summarize([row("R1")], ITEMS, 8)}
    assert "| - |" in compare_table([old])  # 칸이 없는 옛 줄은 못 잰 것이다


def test_runs_measured_through_different_llm_paths_never_share_a_table():
    api, cli, old = path_result("api", "a1"), path_result("cli", "c1"), path_result(None, "old")
    # [왜] 출력 계약 준수율은 두 길에서 뜻이 다르다(API는 스키마 강제, cli는 안쪽 다시 시키기를 셈).
    #      입력 조건도 달라 다른 칸도 나란히 견주지 않는다
    with pytest.raises(ValueError, match="LLM 길"):
        compare_table([api, cli])
    text = compare_tables([api, cli, old])
    first, second = text.split("\n\nLLM 길: cli")
    assert first.startswith("LLM 길: api") and "a1" in first and "old" in first and "c1" not in first
    assert "c1" in second and "a1" not in second
    assert compare_tables([api]) == compare_table([api])  # 길이 하나면 머리글 없이 표만 낸다
