"""evals/push_dataset.py 변환 테스트. Langfuse 없이 돈다 (올리는 부분은 부르지 않는다)."""
import json
from pathlib import Path

from evals.push_dataset import DATASET, DATASET_NAME, item_id, to_item


def _records() -> list[dict]:
    return [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_every_case_becomes_one_item_with_unique_id():
    """30건 모두 항목이 되고, 항목 id가 겹치지 않는다. 다시 올려도 같은 id라 중복이 안 생긴다."""
    items = [to_item(r) for r in _records()]
    ids = [i["id"] for i in items]
    assert len(items) == 30 and len(set(ids)) == 30
    assert ids[0] == item_id("N01") == f"{DATASET_NAME}:N01"


def test_item_splits_input_answer_and_notes():
    """input은 재현용(요청 + 가공 fixtures), expected_output은 채점 칸, metadata는 사람이 읽는 설명."""
    record = next(r for r in _records() if r["id"] == "B08")
    item = to_item(record)
    assert set(item["input"]) == {"request", "fixtures"}
    assert item["expected_output"]["verdict"] == "act" and item["expected_output"]["status"] == "ok"
    assert item["metadata"]["case_id"] == "B08" and item["metadata"]["labeler"]
