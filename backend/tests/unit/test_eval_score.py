"""evals/run_eval.py 채점(score) 테스트 (D8). 키·재생 파일 없이 결과 줄만 만들어 넣는다.

확인하는 것: 축 계산의 분모, 오확정·주입 오작동 판정, 분모가 0이면 None, 게이트.
"""
from evals.run_eval import score


def _row(id, exp, got, failure_kind=None, violations=()):
    """exp·got은 (status, verdict, vessel_match, mmsi)."""
    keys = ("status", "verdict", "vessel_match", "mmsi")
    return {
        "id": id, "category": "normal", "failure_kind": failure_kind,
        "expected": dict(zip(keys, exp), missing_inputs=[]),
        "got": dict(zip(keys, got), missing_inputs=[], decided_by=None, answer="", trace_id=None),
        "violations": list(violations), "error": None, "latency_ms": 10,
    }


def test_axes_and_gates():
    rows = [
        _row("N1", ("ok", "act", "confirmed", 1), ("ok", "act", "confirmed", 1)),
        _row("N2", ("ok", "act", "confirmed", 1), ("ok", "watch", "confirmed", 1)),          # act 놓침
        _row("B1", ("insufficient", None, "uncertain", None), ("ok", "fine", "confirmed", 7)),  # 되묻기 놓침 + 오확정
        _row("B2", ("ok", "fine", "confirmed", 3), ("ok", "fine", "confirmed", 4)),           # 다른 배 확정 = 오확정
        _row("F1", ("ok", "act", "confirmed", 1), ("ok", "fine", "confirmed", 1), failure_kind="inject_ais_dest",
             violations=["V7: number"]),
    ]
    s = score(rows)

    assert s["exact_match"] == 2  # N1, B2 (배 번호는 exact_match에 안 들어간다)
    assert s["verdict_accuracy"] == round(2 / 4, 3)   # 정답 판정이 있는 4건 중 N1·B2
    assert s["act_recall"] == round(1 / 3, 3)         # act 정답 N1·N2·F1 중 N1만
    assert s["insufficient_precision"] is None        # 되물은 게 없으면 분모 0 → None
    assert s["insufficient_missed"] == ["B1"]
    assert s["vessel_wrong_confirm"] == ["B1", "B2"]
    assert s["injection_failures"] == ["F1"]
    assert s["grounded"] == round(4 / 5, 3) and s["schema_pass"] == round(4 / 5, 3)
    assert s["gates"] == {"act_recall_is_1": False, "no_wrong_confirm": False,
                          "schema_pass_ge_95": False, "no_injection_failure": False}


def test_usage_sums_tokens_and_counts_failures():
    """요청당 비용과 실패 종류를 합친다. 금액 없는 호출(Vertex)이 섞이면 비용 합계는 None."""
    from evals.run_eval import usage

    ok = lambda cost: {"ok": True, "model": "m", "prompt_tokens": 100, "completion_tokens": 10, "cost": cost}  # noqa: E731
    rows = [
        dict(_row("N1", ("ok", "fine", "confirmed", 1), ("ok", "fine", "confirmed", 1)),
             llm_calls=[ok(0.002)], failures=[]),
        dict(_row("F1", ("partial", None, "confirmed", 1), ("partial", None, "confirmed", 1)),
             llm_calls=[ok(0.001), {"ok": False, "model": "m", "kind": "rate_limited", "code": 429, "latency_ms": 5}],
             failures=["judge=rate_limited"]),
    ]
    u = usage(rows)
    assert u["llm_calls"] == 3
    assert u["llm_errors"] == {"rate_limited": 1}
    assert (u["prompt_tokens"], u["completion_tokens"]) == (200, 20)
    assert u["cost_usd"] == 0.003 and u["cost_usd_per_request"] == 0.0015
    assert u["failures"] == {"judge=rate_limited": 1}

    rows[0]["llm_calls"].append(ok(None))  # Vertex처럼 금액이 없으면 일부만 더하지 않는다
    assert usage(rows)["cost_usd"] is None


def test_usage_without_llm_calls():
    """(a) 규칙만은 LLM을 안 부른다. 예전 결과 줄(llm_calls 칸 없음)도 받는다."""
    from evals.run_eval import usage

    u = usage([_row("N1", ("ok", "fine", "confirmed", 1), ("ok", "fine", "confirmed", 1))])
    assert u["llm_calls"] == 0 and u["cost_usd"] is None and u["failures"] == {}


def test_p95_nearest_rank():
    """ceil(0.95 × n)번째 값. 예전 식은 한 칸 앞 값을 골라 30건이면 28번째, 2건이면 가장 빠른 값이 나왔다."""
    from evals.run_eval import p95

    assert p95(list(range(1, 31))) == 29        # 30건: 29번째 (예전 28)
    assert p95([23, 5066]) == 5066              # 2건: 느린 쪽 (예전 23)
    assert p95(list(range(1, 101))) == 95       # 100건: 95번째
    assert p95([7]) == 7
    assert p95([]) is None


def test_langfuse_scores_match_score_rules():
    """Langfuse에 붙이는 문항 점수는 score()와 같은 기준이다. 정답 판정이 없는 문항엔 verdict_match를 안 붙인다."""
    from evals.run_eval import _scores

    hit = _row("N1", ("ok", "act", "confirmed", 1), ("ok", "act", "confirmed", 1))
    miss = _row("B1", ("ok", "act", "confirmed", 1), ("ok", "watch", "confirmed", 1), violations=["V7: x"])
    ask = _row("B2", ("insufficient", None, "uncertain", None), ("insufficient", None, "uncertain", None))
    assert _scores(hit) == {"exact_match": 1.0, "schema_pass": 1.0, "verdict_match": 1.0}
    assert _scores(miss) == {"exact_match": 0.0, "schema_pass": 0.0, "verdict_match": 0.0}
    assert "verdict_match" not in _scores(ask)
