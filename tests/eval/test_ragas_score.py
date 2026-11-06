"""scripts/ragas_score.py의 순수 함수 시험. ragas 없이 돈다 (ragas는 main 안에서만 import한다)."""

import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "ragas_score", Path(__file__).resolve().parents[2] / "scripts" / "ragas_score.py"
)
assert SPEC and SPEC.loader
ragas_score = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ragas_score)

PRICE = {"input": 2.0, "output": 10.0}


def test_spent_usd_prices_the_tokens_counted_so_far():
    assert ragas_score.spent_usd({"in": 500_000, "out": 100_000}, PRICE) == 2.0


def test_over_cap_stops_when_the_running_cost_reaches_the_cap():
    assert not ragas_score.over_cap({"in": 400_000, "out": 100_000}, PRICE, 2.0)
    assert ragas_score.over_cap({"in": 500_000, "out": 100_000}, PRICE, 2.0)


def test_dry_run_fails_when_the_estimate_is_over_the_cap(tmp_path):
    import json
    import subprocess
    import sys

    import yaml

    root = Path(__file__).resolve().parents[2]
    ids = [
        i["id"]
        for i in yaml.safe_load((root / "eval/set_v1.yaml").read_text("utf-8"))["items"]
        if i.get("reference")
    ]
    raw = [
        {"id": i, "behaviour": "answer", "cited_texts": ["c"], "calc_lines": [], "ranked_texts": ["c"] * 8}
        for i in ids
    ] * 3
    raw_path = tmp_path / "r.raw.json"
    raw_path.write_text(json.dumps(raw), encoding="utf-8")
    done = subprocess.run(
        [
            sys.executable,
            "scripts/ragas_score.py",
            str(raw_path),
            "--out",
            str(tmp_path / "o.json"),
            "--dry-run",
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert done.returncode != 0 and "상한" in done.stderr


def test_provenance_carries_the_unchecked_label_and_the_run_commit_but_no_answer_text():
    judge = {"unchecked_label": "LLM 채점, 사람 일치 미확인"}
    assert ragas_score.provenance(judge, "ae1891c") == {
        "label": "LLM 채점, 사람 일치 미확인",
        "commit": "ae1891c",
    }
    assert ragas_score.provenance(judge, None)["commit"] == "미상"


NEW = {"id": "R1", "question": "q", "draft": "d", "behaviour": "answer", "reference": "r"}


def test_each_metric_gets_its_own_contexts():
    sample = NEW | {"cited_texts": ["조문"], "calc_lines": ["[BL1]: 반입신고"], "ranked_texts": ["a", "b"]}
    got = ragas_score.contexts_for(sample)
    assert got["faithfulness"] == ["조문", "[BL1]: 반입신고"]
    assert got["context_precision"] == got["context_recall"] == ["a", "b"]


def test_a_raw_file_without_the_new_fields_is_refused_with_a_message():
    import pytest

    old = [{"id": "R1", "question": "q", "behaviour": "answer", "contexts": ["c"]}]
    with pytest.raises(SystemExit, match="cited_texts"):
        ragas_score.samples(old, {"R1": "r"})


def test_a_cargo_item_with_no_cited_text_is_still_scored():
    # [왜] 화물 문항(R15 같은)은 인용 없이 화물 줄만 있어도 빼지 않는다
    raw = [NEW | {"cited_texts": [], "calc_lines": ["[BL1]: 반입신고"], "ranked_texts": []}]
    assert [s["id"] for s in ragas_score.samples(raw, {"R1": "r"})] == ["R1"]


def test_empty_contexts_score_zero_for_faithfulness_and_recall_and_none_for_precision():
    import asyncio

    class Boom:
        async def ascore(self, **kwargs):  # 판정 호출이 일어나면 안 된다
            raise AssertionError("judge called")

    sample = NEW | {"cited_texts": [], "calc_lines": [], "ranked_texts": []}
    metrics = {"faithfulness": Boom(), "context_precision": Boom(), "context_recall": Boom()}
    out = asyncio.run(ragas_score.score(sample, metrics))
    assert out["faithfulness"] == 0.0 and out["context_recall"] == 0.0 and out["context_precision"] is None
    assert out["errors"] == [
        "faithfulness: no_contexts=0",
        "context_precision: no_contexts",
        "context_recall: no_contexts=0",
    ]


def test_reference_items_that_were_not_scored_are_listed_with_the_reason():
    raw = [
        NEW | {"id": "R1", "cited_texts": [], "calc_lines": [], "ranked_texts": []},
        NEW | {"id": "R2", "behaviour": "decline", "cited_texts": [], "calc_lines": [], "ranked_texts": []},
        {"id": "R3", "error": "X"},  # 오류 줄은 행동이 없다
    ]
    refs = {"R1": "r", "R2": "r", "R3": "r", "R4": "r", "S1": ""}  # S1은 정답 글이 없다
    todo = ragas_score.samples(raw, refs)
    assert ragas_score.not_scored(raw, refs, todo) == [
        ("R2", "decline"),
        ("R3", "error"),
        ("R4", "raw에 없음"),
    ]
