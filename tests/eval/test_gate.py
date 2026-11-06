"""CI 평가 문 시험 (done 3.6). 저장소에 둔 실행 결과(파생 값)를 지금 코드로 다시 채점해 바닥값과 비교한다."""

import json

from marvia.eval.dataset import ROOT, SET_PATH, file_sha256, load_set
from marvia.eval.metrics import floors, gate_missing, gate_violations, summarize
from marvia.tools.rules import load_rules


def test_gate_flags_metrics_below_the_floor_and_metrics_not_measured():
    summary = {
        "errors": 0,
        "leaks": 1,
        "mrr": {"value": 0.5, "n": 10},
        "unsupported": {"value": None, "n": 0},
    }
    bounds = {"errors": {"max": 0}, "leaks": {"max": 0}, "mrr": {"min": 0.6}, "unsupported": {"max": 0.1}}
    assert gate_violations(summary, bounds) == [
        "leaks: 1 > 천장 0",
        "mrr: 0.5 < 바닥 0.6",
        "unsupported: 재지 못했다",
    ]


def test_floors_leave_one_item_of_room():
    metric = {"value": 0.8, "n": 10}
    summary = {key: metric for key in ["correct_citation", "behaviour_accuracy", "blocked_accuracy"]}
    summary |= {
        "calc_accuracy": {"value": None, "n": 0},
        "mrr": metric,
        "recall_at_8": metric,
        "trajectory": metric,
    }
    summary |= {"wrong_evidence": {"value": 0.1, "n": 20}, "unsupported": {"value": 0.0, "n": 16}}
    out = floors(summary, 8)
    assert out["correct_citation"] == {"min": 0.7} and out["recall_at_8"] == {"min": 0.7}
    assert out["trajectory"] == {"min": 0.7}
    assert out["wrong_evidence"] == {"max": 0.15} and out["unsupported"] == {"max": 0.07}
    assert "calc_accuracy" not in out and out["errors"] == {"max": 0} and out["leaks"] == {"max": 0}
    assert out["cap_breaches"] == {"max": 0}
    low = floors(summary | {"mrr": {"value": 0.0, "n": 12}, "unsupported": {"value": 1.0, "n": 3}}, 8)
    assert low["mrr"] == {"min": 0.0} and low["unsupported"] == {"max": 1.0}  # 0~1 밖으로 나가지 않는다


def test_gate_reports_required_keys_missing_from_the_floors():
    assert gate_missing({}) == ["errors", "leaks", "cap_breaches"]
    assert gate_missing({"errors": {"max": 0}, "leaks": {"max": 1}, "cap_breaches": {"max": 0}}) == ["leaks"]
    assert gate_missing(floors({k: {"value": 0.5, "n": 4} for k in _KEYS}, 8)) == []


_KEYS = ["correct_citation", "behaviour_accuracy", "blocked_accuracy", "calc_accuracy", "mrr", "recall_at_8"]
_KEYS += ["wrong_evidence", "unsupported", "trajectory"]


def test_committed_run_still_meets_its_floors():
    gate = load_rules("eval")["gate"]
    result = json.loads((ROOT / gate["file"]).read_text(encoding="utf-8"))
    # [왜] 평가셋이 바뀐 뒤의 저장 결과는 지금 정답으로 채점할 수 없다. 다시 돌려 결과를 바꾼다
    assert result["meta"]["set_sha256"] == file_sha256(SET_PATH)
    assert gate_missing(gate["floors"]) == []  # [왜] 빈 바닥값이면 아래 비교가 아무것도 보지 않고 통과한다
    items = {item.id: item for item in load_set().items}
    summary = summarize(result["rows"], items, result["meta"]["k"])
    assert gate_violations(summary, gate["floors"]) == []
