"""scripts/run_eval.py 명령의 경계 시험. 키·DB 없이 돈다."""

import json
import os
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
    assert v1.returncode == 0 and "[주의]" not in v1.stdout and "없다고 잘못 답함" in v1.stdout
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
            "--graph",
            "off",
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
    data["meta"] |= {"set": "v2", "set_sha256": file_sha256(SET_V2_PATH), "tag": tag, "commit": "c2c068d"}
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
    assert done.returncode == 0 and "| MRR |" in done.stdout and "실행 2번" in done.stdout
    v1 = json.loads((ROOT / "eval/results/agent-claude-haiku-5-5.json").read_text(encoding="utf-8"))
    v1["meta"]["commit"] = "c2c068d"  # 커밋이 같아야 같은 묶음이다
    foreign = tmp_path / "v1.json"
    foreign.write_text(json.dumps(v1), encoding="utf-8")
    mixed = _cli("spread", first, foreign)
    assert mixed.returncode != 0 and "평가셋 파일이 다르다" in mixed.stderr


def test_report_line_names_the_tag_and_the_default_set_is_v2(tmp_path):
    run = _v2_run(tmp_path, "a.json", "v2r1")
    done = _cli("report", run)  # --set을 안 주면 v2다
    assert "- agent-claude-haiku-5-5-v2r1: v2 (sha" in done.stdout and "[주의]" not in done.stdout


def test_spread_lists_files_and_defaults_to_v2_and_groups_by_commit(tmp_path):
    first, second = _v2_run(tmp_path, "a.json", "v2r1"), _v2_run(tmp_path, "b.json", "v2r2")
    data = json.loads(second.read_text(encoding="utf-8"))
    data["meta"]["commit"] = "other00"
    third = tmp_path / "c.json"
    third.write_text(json.dumps(data), encoding="utf-8")
    done = _cli("spread", first, second, third)
    assert done.returncode == 0 and "행동 정확도" in done.stdout and "없다고 잘못 답함" in done.stdout
    assert done.stdout.count("### ") == 2 and "c2c068d" in done.stdout and "other00" in done.stdout


def test_spread_set_v1_scores_v2_runs_on_behaviour_base_and_refuses_runs_without_it(tmp_path):
    run = _v2_run(tmp_path, "a.json", "v2r1")
    view = _cli("spread", "--set", "v1", run)
    assert view.returncode == 0 and "v1 기준으로 본 v2 실행" in view.stdout
    data = json.loads(run.read_text(encoding="utf-8"))
    for row in data["rows"]:
        del row["behaviour_base"]
    bare = tmp_path / "bare.json"
    bare.write_text(json.dumps(data), encoding="utf-8")
    refused = _cli("spread", "--set", "v1", bare)
    assert refused.returncode != 0 and "behaviour_base" in refused.stderr
    v1_file = ROOT / "eval/results/agent-claude-haiku-5-5.json"
    assert _cli("spread", v1_file).returncode != 0  # 기본 v2로는 v1 파일을 채점하지 않는다


def test_run_requires_graph_and_stops_before_any_spend_when_it_differs_from_the_real_setting(tmp_path):
    base = ["run", "--out", tmp_path / "o", "--commit", "t"]
    missing = _cli(*base)
    assert missing.returncode == 2 and "--graph" in missing.stderr
    # [왜] MARVIA_GRAPH가 Docker 안까지 안 넘어가면 "켬" 실행이 꺼진 채 돈다. 돈 쓰기 전에 멈춘다
    env = {**os.environ, "MARVIA_GRAPH": "off"}
    done = subprocess.run(
        [sys.executable, "scripts/run_eval.py", *map(str, base), "--graph", "on"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert done.returncode == 1 and "[멈춤] --graph on인데 실제 설정(MARVIA_GRAPH)은 off다" in done.stderr


def test_run_on_the_cli_path_prints_no_cost_estimate(tmp_path):
    # [왜] 구독의 claude -p로 부르면 청구액이 없다. 어림 비용과 쓴 돈을 찍으면 잰 값처럼 읽힌다
    args = [
        "scripts/run_eval.py",
        "run",
        "--out",
        str(tmp_path),
        "--commit",
        "t",
        "--graph",
        "off",
        "--dry-run",
    ]
    done = subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=os.environ | {"MARVIA_LLM_VIA": "cli"},
    )
    assert done.returncode == 0, done.stderr
    assert "어림 비용" not in done.stdout and "합계" not in done.stdout and "$" not in done.stdout
    assert "claude -p" in done.stdout
    api = subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=os.environ | {"MARVIA_LLM_VIA": "api"},
    )
    assert "어림 비용" in api.stdout


def verdict_files(
    tmp_path: Path,
    loop: str,
    commit: str,
    set_sha: str,
    n: int = 5,
    llm_via: str = "cli",
    model: str = "claude-haiku-5-5",
    problems: list[str] | None = None,
    tag: str = "r",
) -> list[str]:
    """판정 명령에 줄 결과 파일 n개. 줄은 R01 하나(답했고 인용은 없다)."""
    row = {"id": "R01", "loop": loop, "behaviour": "answer", "cited": [], "evidence": [], "retrieved": []}
    row |= {"calc": {}, "llm_calls": 5, "failed": [], "leak": False, "error": None}
    meta = {"loop": loop, "commit": commit, "set": "v3", "set_sha256": set_sha, "model": model}
    meta |= {"llm_via": llm_via, "problems": problems or []}
    paths = []
    for i in range(n):
        path = tmp_path / f"{loop}-{commit}-{llm_via}-{model}-{tag}{i}.json"
        path.write_text(json.dumps({"meta": meta | {"tag": f"{tag}{i}"}, "rows": [row]}), encoding="utf-8")
        paths.append(str(path))
    return paths


def verdict(*args: str):
    return subprocess.run(
        [sys.executable, "scripts/run_eval.py", "verdict", *args], cwd=ROOT, capture_output=True, text=True
    )


def test_verdict_prints_the_registered_comparison_for_five_runs_per_path(tmp_path):
    from marvia.eval.dataset import SET_V3_PATH, file_sha256

    sha = file_sha256(SET_V3_PATH)
    agent = verdict_files(tmp_path, "agent", "abc1234", sha)
    supervisor = verdict_files(tmp_path, "supervisor", "abc1234", sha)
    done = verdict("--agent", *agent, "--supervisor", *supervisor)
    out = json.loads(done.stdout)
    assert out["verdict"] == "구분 못 함" and out["set"] == "v3" and out["commit"] == "abc1234"
    assert out["right_items"]["behaviour"] == {"agent": 1, "supervisor": 1}
    # [왜] 사전 검사도 같은 명령이 낸다. 줄이 R01 하나(행동 맞음, 인용 없음)라 저장 범위 밖이다
    assert out["llm_via"] == "cli" and out["model"] == "claude-haiku-5-5" and out["invalid_runs"] == []
    assert out["precheck"]["behaviour_accuracy"]["mean"] == 1.0
    assert out["precheck"]["correct_citation"] == {"mean": 0.0, "low": -0.3333, "high": 1.8333, "ok": True}


def test_verdict_refuses_runs_of_another_commit_set_or_path(tmp_path):
    from marvia.eval.dataset import SET_V3_PATH, file_sha256

    sha = file_sha256(SET_V3_PATH)
    agent = verdict_files(tmp_path, "agent", "abc1234", sha)
    other_commit = verdict_files(tmp_path, "supervisor", "def5678", sha)
    done = verdict("--agent", *agent, "--supervisor", *other_commit)
    assert done.returncode != 0 and "실행 조건이 다르다" in done.stderr and "Traceback" not in done.stderr
    other_set = verdict_files(tmp_path, "supervisor", "abc1234", "0" * 64)
    done = verdict("--agent", *agent, "--supervisor", *other_set)
    assert done.returncode != 0 and "평가셋" in done.stderr
    done = verdict("--agent", *agent, "--supervisor", *agent)
    assert done.returncode != 0 and "supervisor" in done.stderr
    by_api = verdict_files(tmp_path, "supervisor", "abc1234", sha, llm_via="api")
    done = verdict("--agent", *agent, "--supervisor", *by_api)
    assert done.returncode != 0 and "LLM 길이 섞였다" in done.stderr
    other_model = verdict_files(tmp_path, "supervisor", "abc1234", sha, model="claude-sonnet-5-5")
    done = verdict("--agent", *agent, "--supervisor", *other_model)
    assert done.returncode != 0 and "실행 조건이 다르다" in done.stderr


def test_verdict_refuses_an_invalid_run_and_lists_the_ones_that_were_rerun(tmp_path):
    from marvia.eval.dataset import SET_V3_PATH, file_sha256

    sha = file_sha256(SET_V3_PATH)
    agent = verdict_files(tmp_path, "agent", "abc1234", sha)
    supervisor = verdict_files(tmp_path, "supervisor", "abc1234", sha)
    broken = verdict_files(tmp_path, "supervisor", "abc1234", sha, n=1, problems=["errors 1"], tag="x")
    # 무효 실행(meta.problems가 있다)을 판정에 넣으면 거절한다
    done = verdict("--agent", *agent, "--supervisor", *supervisor[:4], *broken)
    assert done.returncode != 0 and "무효 실행" in done.stderr
    # 다시 돈 실행으로 판정하고, 무효였던 실행은 까닭과 함께 적는다
    done = verdict("--agent", *agent, "--supervisor", *supervisor, "--invalid", *broken)
    out = json.loads(done.stdout)
    assert out["invalid_runs"] == [{"file": Path(broken[0]).name, "problems": ["errors 1"]}]
    # [왜] 무효는 meta.problems로만 정한다. 문제가 없는 실행을 무효라고 빼려 하면 거절한다
    done = verdict("--agent", *agent, "--supervisor", *supervisor, "--invalid", supervisor[0])
    assert done.returncode != 0 and "무효가 아닌 실행은 뺄 수 없다" in done.stderr
