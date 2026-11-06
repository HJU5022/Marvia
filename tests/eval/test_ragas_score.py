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
