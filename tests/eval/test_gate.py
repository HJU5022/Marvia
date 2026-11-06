"""CI 평가 문 시험 (done 3.6). 저장소에 둔 실행 결과(파생 값)를 지금 코드로 다시 채점해 바닥값과 비교한다."""

import json
import subprocess
import sys

import pytest

from marvia.eval.dataset import ROOT, SETS, file_sha256, load_set
from marvia.eval.metrics import (
    floors,
    gate_block,
    gate_missing,
    gate_uncovered,
    gate_violations,
    summarize,
)
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
    assert gate["set"] in SETS  # [왜] 문 파일을 어느 평가셋으로 채점하는지 규칙 파일이 이름으로 말한다
    # [왜] 평가셋이 바뀐 뒤의 저장 결과는 지금 정답으로 채점할 수 없다. 다시 돌려 결과를 바꾼다
    assert result["meta"]["set_sha256"] == file_sha256(SETS[gate["set"]])
    assert gate_missing(gate["floors"]) == []  # [왜] 빈 바닥값이면 아래 비교가 아무것도 보지 않고 통과한다
    items = {item.id: item for item in load_set(SETS[gate["set"]]).items}
    assert gate_uncovered(result["rows"], items) == []  # [왜] 일부만 담은 파일은 그 일부로만 판정돼 통과한다
    summary = summarize(result["rows"], items, result["meta"]["k"])
    assert gate_violations(summary, gate["floors"]) == []


def test_gate_file_missing_an_item_or_repeating_one_is_not_covering_the_set(tmp_path):
    gate = load_rules("eval")["gate"]
    full = json.loads((ROOT / gate["file"]).read_text(encoding="utf-8"))
    items = {item.id: item for item in load_set(SETS[gate["set"]]).items}
    trimmed = tmp_path / "trimmed.json"  # 상한에서 멈춘 일부 결과를 흉내 낸다
    trimmed.write_text(json.dumps(full | {"rows": full["rows"][:-1]}), encoding="utf-8")
    rows = json.loads(trimmed.read_text(encoding="utf-8"))["rows"]
    assert gate_uncovered(rows, items) == [f"빠짐: {full['rows'][-1]['id']}"]
    assert gate_uncovered(full["rows"] + full["rows"][:1], items) == [f"겹침: {full['rows'][0]['id']}"]


def test_gate_floors_are_exactly_what_the_code_makes_from_the_gate_file():
    # [왜] 바닥값을 손으로 낮추면 CI 문이 조용히 느슨해진다 (R-060). 코드가 만든 값과 같아야 한다
    gate = load_rules("eval")["gate"]
    result = json.loads((ROOT / gate["file"]).read_text(encoding="utf-8"))
    items = {item.id: item for item in load_set(SETS[gate["set"]]).items}
    summary = summarize(result["rows"], items, result["meta"]["k"])
    assert gate["floors"] == floors(summary, result["meta"]["k"], gate["set"])


def test_stored_summary_equals_the_rescored_one_for_every_metric_it_has():
    gate = load_rules("eval")["gate"]
    result = json.loads((ROOT / gate["file"]).read_text(encoding="utf-8"))
    items = {item.id: item for item in load_set(SETS[gate["set"]]).items}
    again = summarize(result["rows"], items, result["meta"]["k"])
    assert {k: again[k] for k in result["summary"]} == result["summary"]


OLD = {"file": "f.json", "floors": {"errors": {"max": 0}, "mrr": {"min": 0.5}, "unsupported": {"max": 0.1}}}


def test_a_looser_floor_needs_a_ruling_and_is_recorded_with_it():
    lower = OLD["floors"] | {"mrr": {"min": 0.4}, "unsupported": {"max": 0.2}}
    with pytest.raises(ValueError, match="mrr"):
        gate_block("f.json", lower, OLD, None, "2026-11-06")
    block = gate_block("f.json", lower, OLD, "평가셋 v2로 바뀜", "2026-11-06")
    assert block["rulings"] == [
        {"date": "2026-11-06", "metric": "mrr", "old": 0.5, "new": 0.4, "reason": "평가셋 v2로 바뀜"},
        {"date": "2026-11-06", "metric": "unsupported", "old": 0.1, "new": 0.2, "reason": "평가셋 v2로 바뀜"},
    ]


def test_a_tighter_floor_needs_no_ruling_and_keeps_the_earlier_rulings():
    tighter = OLD["floors"] | {"mrr": {"min": 0.6}}
    kept = [{"date": "2026-10-01", "metric": "mrr", "old": 0.6, "new": 0.5, "reason": "x"}]
    block = gate_block("f.json", tighter, OLD | {"rulings": kept}, None, "2026-11-06")
    assert block["floors"]["mrr"] == {"min": 0.6} and block["rulings"] == kept


def test_floors_write_refuses_a_looser_floor_without_a_ruling_and_leaves_the_rules_alone(tmp_path):
    gate = load_rules("eval")["gate"]
    result = json.loads((ROOT / gate["file"]).read_text(encoding="utf-8"))
    for row in result["rows"]:
        row["cited"] = []  # 정답 근거 인용률이 내려간다
    worse = tmp_path / "worse.json"
    worse.write_text(json.dumps(result), encoding="utf-8")
    rules = ROOT / "rules" / "eval.yaml"
    before = rules.read_text(encoding="utf-8")
    try:
        done = subprocess.run(
            [sys.executable, "scripts/run_eval.py", "floors", str(worse), "--write"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
    finally:
        # [왜] 거절이 깨지면 진짜 규칙 파일을 덮어쓴다. 읽어 둔 뒤 되돌려, 단언이 실패해도 파일은 온전하다
        after = rules.read_text(encoding="utf-8")
        rules.write_text(before, encoding="utf-8")
    assert done.returncode != 0 and "--ruling" in done.stderr and "correct_citation" in done.stderr
    assert after == before


def test_a_ruling_with_a_line_break_is_refused():
    # [왜] 빈 줄이 든 이유는 YAML 여러 줄 글이 되어 다음 --write가 gate 묶음을 중간에서 자른다
    with pytest.raises(ValueError, match="줄바꿈"):
        gate_block("f.json", OLD["floors"] | {"mrr": {"min": 0.4}}, OLD, "a\n\nb", "2026-11-06")


def test_gate_block_records_the_set_it_was_built_on():
    block = gate_block("f.json", OLD["floors"], OLD, None, "2026-11-06", "v2")
    assert list(block) == ["file", "set", "floors"] and block["set"] == "v2"
    assert "set" not in gate_block("f.json", OLD["floors"], OLD, None, "2026-11-06")


def test_floors_command_refuses_a_result_that_was_run_on_another_set_file():
    gate = load_rules("eval")["gate"]
    done = subprocess.run(
        [sys.executable, "scripts/run_eval.py", "floors", gate["file"], "--set", "v2"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert done.returncode != 0 and "평가셋" in done.stderr + done.stdout
