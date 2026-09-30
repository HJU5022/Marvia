"""평가셋 30건을 Langfuse Dataset에 올린다 (필수 조건 4 "Langfuse 평가셋 30건+ Dataset", SDD 5.12).

    python -m evals.push_dataset          # .env의 LANGFUSE 키로 올린다

레포의 evals/dataset.jsonl이 원본이다. Langfuse는 사본이라, 평가셋을 사람이 고치면 이 스크립트를 다시 돌린다.
문항 id(N01 등)로 Langfuse 항목 id를 정해서, 다시 돌려도 같은 항목을 덮어쓸 뿐 중복이 생기지 않는다.

서비스는 이 Dataset을 쓰지 않는다. 평가 실행기(evals/run_eval.py)가 돌 때마다 결과를 문항별로 연결해
"프롬프트·모델을 바꾸기 전과 후"를 Langfuse 화면에서 문항별로 비교하려는 것이다.
fixtures는 전부 가공값이다 (CLAUDE.md: 실제 선박·B/L 응답은 레포와 외부에 올리지 않는다).
"""
from __future__ import annotations

import json
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals" / "dataset.jsonl"
DATASET_NAME = "marvia-golden-30"  # Langfuse Dataset 이름. run_eval.py가 같은 이름으로 실행 기록을 붙인다


def item_id(record_id: str) -> str:
    """Langfuse 항목 id. 프로젝트 안에서 겹치지 않게 Dataset 이름을 앞에 붙인다. 예: marvia-golden-30:N01"""
    return f"{DATASET_NAME}:{record_id}"


def to_item(record: dict) -> dict:
    """평가셋 한 줄을 Langfuse 항목의 input·expected_output·metadata로 나눈다.

    input은 실행기가 문항을 재현하는 데 필요한 것(요청 + 가공 fixtures), expected_output은 채점하는 정답 칸,
    metadata는 사람이 화면에서 읽는 설명(유형·라벨링한 사람·이유)이다.
    """
    return {
        "id": item_id(record["id"]),
        "input": {"request": record["request"], "fixtures": record["fixtures"]},
        "expected_output": {
            "status": record["expected_status"],
            "verdict": record["expected_verdict"],
            "vessel_match": record["expected_vessel_match"],
            "mmsi": record["expected_mmsi"],
            "missing_inputs": record["expected_missing_inputs"],
        },
        "metadata": {
            "case_id": record["id"],
            "category": record["category"],
            "failure_kind": record["failure_kind"],
            "labeler": record["labeler"],
            "label_reason": record["label_reason"],
        },
    }


def main() -> None:
    load_dotenv(ROOT / ".env")
    from langfuse import Langfuse  # 키 없는 테스트 환경에서 이 모듈을 import해도 langfuse 없이 돌게 여기서 부른다

    records = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    client = Langfuse()
    client.create_dataset(
        name=DATASET_NAME,
        description="Marvia 평가셋 30건 (정상 8 · 경계 14 · 실패 8). 원본은 레포 evals/dataset.jsonl, 입력은 모두 가공값",
        metadata={"source": "evals/dataset.jsonl", "count": len(records)},
    )
    for record in records:
        client.create_dataset_item(dataset_name=DATASET_NAME, **to_item(record))
    client.flush()
    print(f"{DATASET_NAME}: {len(records)}건 올림")


if __name__ == "__main__":
    main()
