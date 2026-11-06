"""scripts/run_eval.py 명령의 경계 시험. 키·DB 없이 돈다."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


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
    out = json.loads(agree(tmp_path, grades, scores, {"contexts_rule": "cited+calc"}).stdout)
    assert out["contexts_rule"] == "cited+calc" and out["human_items"] == 2 and out["calc_excluded"] == []
    assert "faithfulness_calc" not in out["ragas"]
    old = json.loads(agree(tmp_path, grades, scores).stdout)
    assert old["contexts_rule"].startswith("없음")
