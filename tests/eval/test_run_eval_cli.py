"""scripts/run_eval.py 명령의 경계 시험. 키·DB 없이 돈다."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

from marvia.tools.rules import load_rules

ROOT = Path(__file__).resolve().parents[2]
RULE = load_rules("eval")["ragas"]["contexts_rule"]  # 이름은 규칙 파일에 둔다


def test_sheet_refuses_to_write_answer_text_inside_the_repo():
    out = ROOT / "tests" / "sheet-should-not-exist.md"
    done = subprocess.run(
        [sys.executable, "scripts/run_eval.py", "sheet", "a.json", "a.raw.json", "--out", str(out)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert done.returncode != 0 and "저장소 안" in done.stderr
    assert not out.exists()


def agree(tmp_path: Path, grades: str, scores: list[dict], meta: dict | None = None):
    human, score = tmp_path / "h.yaml", tmp_path / "s.json"
    human.write_text(f"grades: {grades}\n", encoding="utf-8")
    score.write_text(json.dumps({"meta": meta or {}, "scores": scores}), encoding="utf-8")
    return subprocess.run(
        [sys.executable, "scripts/run_eval.py", "agree", str(human), str(score)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def test_agree_needs_every_human_item_scored_before_it_says_checked(tmp_path):
    grades = "{R1: {faithful: 1}, R2: {faithful: 1}}"
    done = agree(tmp_path, grades, [{"id": "R1", "faithfulness": 0.9}])
    out = json.loads(done.stdout)
    assert out["agreement"]["value"] == 1.0 and out["missing"] == ["R2"]
    assert out["labels"]["faithfulness"] == "LLM 채점, 사람 일치 미확인"
    both = agree(tmp_path, grades, [{"id": "R1", "faithfulness": 0.9}, {"id": "R2", "faithfulness": 0.9}])
    labels = json.loads(both.stdout)["labels"]
    assert labels["faithfulness"] == "LLM 채점, 사람 일치 확인"
    # [왜] 사람 채점은 충실도에만 있다. 정밀도·재현율은 일치를 본 적이 없어 미확인으로 남는다 (R-063)
    assert labels["context_precision"] == labels["context_recall"] == "LLM 채점, 사람 일치 미확인"


def test_agree_stops_with_the_item_name_when_a_human_grade_is_blank(tmp_path):
    done = agree(tmp_path, "{R1: {faithful: }}", [{"id": "R1", "faithfulness": 0.9}])
    assert done.returncode != 0 and "R1" in done.stderr and "Traceback" not in done.stderr


def test_domain_prompts_refuses_to_write_inside_the_repo(tmp_path):
    out = (
        ROOT / "tests" / "domain-prompts-should-not-exist"
    )  # ROOT는 코드가 쓰는 저장소 뿌리와 같은 파일 기준
    try:
        done = subprocess.run(
            [sys.executable, "scripts/run_eval.py", "domain-prompts", "--out", str(out)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        wrote = out.exists()
    finally:
        # [왜] 코드가 깨져 폴더가 생겨도 저장소에 남기지 않는다 (지우지 않고 옮긴다)
        if out.exists():
            shutil.move(out, tmp_path / out.name)
    assert done.returncode != 0 and "저장소 안" in done.stderr
    assert not wrote


def test_agree_leaves_calc_items_out_of_the_faithfulness_agreement(tmp_path):
    grades = "{R01: {faithful: 1}, R12: {faithful: 1}}"
    scores = [{"id": "R01", "faithfulness": 0.9}, {"id": "R12", "faithfulness": 0.0}]
    out = json.loads(agree(tmp_path, grades, scores).stdout)
    assert out["agreement"]["value"] == 1.0 and out["human_items"] == 1 and out["missing"] == []
    assert out["calc_excluded"] == ["R12"] and out["ragas"]["faithfulness_calc"]["value"] == 0.0
    assert "계산·화물 줄은 ragas 맥락에 없어 낮게 나옴" in out["note"]


def test_agree_keeps_calc_items_in_a_file_scored_with_cited_and_calc_contexts(tmp_path):
    grades = "{R01: {faithful: 1}, R12: {faithful: 1}}"
    scores = [{"id": "R01", "faithfulness": 0.9}, {"id": "R12", "faithfulness": 0.9}]
    out = json.loads(agree(tmp_path, grades, scores, {"contexts_rule": RULE}).stdout)
    assert out["contexts_rule"] == RULE and out["human_items"] == 2 and out["calc_excluded"] == []
    assert "faithfulness_calc" not in out["ragas"] and set(out["labels"]) == set(out["ragas"])
    old = json.loads(agree(tmp_path, grades, scores).stdout)
    assert old["contexts_rule"].startswith("없음")
    # [왜] 출력의 모든 ragas 칸에 라벨이 있어야 한다. 옛 규칙 파일의 faithfulness_calc도 미확인이다
    assert set(old["labels"]) == set(old["ragas"]) and "faithfulness_calc" in old["labels"]
    assert old["labels"]["faithfulness_calc"] == load_rules("eval")["judge"]["unchecked_label"]


def test_report_scores_with_the_chosen_set_and_warns_when_the_result_came_from_another_file():
    result = "eval/results/agent-claude-haiku-5-5.json"
    run = lambda *extra: subprocess.run(  # noqa: E731
        [sys.executable, "scripts/run_eval.py", "report", *extra, result],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    v1, v2 = run("--set", "v1"), run("--set", "v2")
    assert v1.returncode == 0 and "[주의]" not in v1.stdout and "지어낸 없음" in v1.stdout
    # [왜] 저장 결과의 set_sha256은 v1 파일의 것이다. v2로 채점하면 다른 파일이라고 알린다
    assert v2.returncode == 0 and "[주의]" in v2.stdout


def test_run_dry_run_accepts_an_unfrozen_v2_set(tmp_path):
    done = subprocess.run(
        [
            sys.executable,
            "scripts/run_eval.py",
            "run",
            "--set",
            "v2",
            "--out",
            str(tmp_path),
            "--commit",
            "t",
            "--dry-run",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0 and "합계" in done.stdout


def _v2_run(tmp_path, name, tag):
    """저장소에 둔 v1 결과를 v2 실행처럼 바꾼 사본 (meta가 v2 파일 sha, 줄에 behaviour_base)."""
    from marvia.eval.dataset import SET_V2_PATH, file_sha256

    data = json.loads((ROOT / "eval/results/agent-claude-haiku-5-5.json").read_text(encoding="utf-8"))
    data["meta"] |= {"set": "v2", "set_sha256": file_sha256(SET_V2_PATH), "tag": tag}
    for row in data["rows"]:
        row["behaviour_base"] = row["behaviour"]
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _cli(*args):
    return subprocess.run(
        [sys.executable, "scripts/run_eval.py", *map(str, args)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_report_labels_the_set_and_does_not_warn_for_the_v1_view_of_a_v2_run(tmp_path):
    run = _v2_run(tmp_path, "a.json", "v2r1")
    as_v1, as_v2 = _cli("report", "--set", "v1", run), _cli("report", "--set", "v2", run)
    assert as_v1.returncode == 0 and "v1 기준으로 본 v2 실행" in as_v1.stdout and "[주의]" not in as_v1.stdout
    assert as_v2.returncode == 0 and "v2 (sha" in as_v2.stdout and "[주의]" not in as_v2.stdout


def test_spread_prints_mean_and_range_and_refuses_mixed_set_files(tmp_path):
    first, second = _v2_run(tmp_path, "a.json", "v2r1"), _v2_run(tmp_path, "b.json", "v2r2")
    done = _cli("spread", first, second)
    assert done.returncode == 0 and "| mrr |" in done.stdout and "실행 2번" in done.stdout
    v1 = ROOT / "eval/results/agent-claude-haiku-5-5.json"
    mixed = _cli("spread", first, v1)
    assert mixed.returncode != 0 and "평가셋 파일이 다르다" in mixed.stderr
