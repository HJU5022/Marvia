"""비용 상한. (PRD 8절, 41번)

순수 함수라 키·DB 없이 테스트된다. 강제 지점은 두 곳이다.
  - 요청당: pipeline.run 이 judge(대형)를 부르기 전에 누적액과 비교한다. 넘으면 대형을 생략한다.
  - 일일: routers/agent.py 가 pipeline.run 전에 오늘 합계와 비교한다. 넘으면 429 다.
둘 다 env 가 비어 있으면 동작하지 않는다.
"""
from __future__ import annotations

import json
import os

# (입력, 출력) $/1M 토큰. 대략값 (2026-09 기준). 실단가와 다를 수 있어
# 정확한 단가는 MODEL_COST_JSON 으로 덮어쓴다. 예: {"my/model": [1.0, 3.0]}
_RATES: dict[str, tuple[float, float]] = {
    "anthropic/claude-sonnet-5": (3.0, 15.0),
    "google/gemini-3.8-flash": (0.5, 1.5),
    "openai/gpt-5.6-luna": (5.0, 20.0),
    "openai/gpt-4o-mini": (0.15, 0.6),
}


def _rates() -> dict[str, tuple[float, float]]:
    merged = dict(_RATES)
    raw = os.environ.get("MODEL_COST_JSON")
    if raw:
        try:
            for model, pair in json.loads(raw).items():
                merged[model] = (float(pair[0]), float(pair[1]))
        except (ValueError, TypeError, IndexError):
            pass
    return merged


def estimate_cost_usd(model: str, tokens_in: int, tokens_out: int) -> float | None:
    """토큰 수로 대략 비용을 잰다. 단가표에 없는 모델은 None (강제하지 않는다)."""
    rate = _rates().get(model)
    if rate is None:
        return None
    return (tokens_in * rate[0] + tokens_out * rate[1]) / 1_000_000


def _parse_limit(name: str) -> float | None:
    raw = os.environ.get(name)
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def per_request_limit() -> float | None:
    """COST_LIMIT_USD_PER_REQUEST. 비어 있으면 제한 없음."""
    return _parse_limit("COST_LIMIT_USD_PER_REQUEST")


def daily_limit() -> float | None:
    """DAILY_COST_LIMIT_USD. 비어 있으면 제한 없음."""
    return _parse_limit("DAILY_COST_LIMIT_USD")


def over_limit(spent_usd: float, limit: float | None) -> bool:
    """누적액이 상한에 닿았나. 상한이 없으면 False."""
    return limit is not None and spent_usd >= limit
