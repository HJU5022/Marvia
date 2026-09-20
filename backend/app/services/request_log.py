"""요청 로그. 단계마다 한 줄씩 남긴다. (테이블정의서 3절, 체크리스트 40·42번)

왜 남기나:
  라우팅 전후 비용을 비교하려면 "이 요청이 어느 모델을 몇 번 불렀고 얼마였나"가 있어야 한다.
  Langfuse 트레이스에도 남지만, 집계(p95 지연, 요청당 비용)는 SQL 로 하는 편이 낫다.

실패는 삼킨다. 로그를 못 남겼다고 사용자 요청을 깨뜨릴 이유가 없다.
이름·출발지 같은 식별 정보는 넣지 않는다 (테이블정의서 3절 "로그에는 식별 정보를 넣지 않는다").
"""
from __future__ import annotations

from typing import Any


async def write(**fields: Any) -> None:
    """store.log_request 로 한 줄. DB 가 없거나 실패해도 조용히 지나간다."""
    try:
        from backend.app.services import store

        await store.log_request(**fields)
    except Exception:  # noqa: BLE001  로그는 곁다리다
        return
