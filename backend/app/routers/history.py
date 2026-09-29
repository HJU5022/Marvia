"""GET /api/history (작업 A12, SDD 4.4).

세션의 지난 조회를 목록으로 돌려준다. 새로 계산하거나 저장하지 않고 query_log를 읽기만 한다.
B/L은 bl_masked로만 나간다 (SDD 3.5, 7절).

DB가 없거나 꺼져 있으면 빈 목록을 돌려준다. 이력은 부가 기능이라 이것 때문에 화면이 죽으면 안 된다.
"""
import os
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from backend.app.db import connect, recent_queries
from backend.app.observability.logging import log_failure

router = APIRouter(prefix="/api", tags=["history"])


class HistoryItem(BaseModel):
    """이력 한 줄. 판정 결과 요약만 담는다. 근거와 본문은 다시 조회해야 한다."""

    request_id: str | None
    bl_masked: str | None
    status: str | None
    verdict: str | None
    vessel_match: str | None
    decided_by: Literal["rule", "llm"] | None
    model: str | None
    trace_id: str | None
    created_at: datetime


class HistoryResponse(BaseModel):
    items: list[HistoryItem]
    available: bool = True  # DB를 못 읽었으면 false. 빈 이력과 구분한다


@router.get("/history", response_model=HistoryResponse)
def get_history(
    session_id: str = Query(description="조회할 세션 ID"),
    limit: int = Query(default=20, ge=1, le=100, description="가져올 개수. 최대 100"),
) -> HistoryResponse:
    """이 세션이 지금까지 무엇을 조회했는지 최신순으로 돌려준다."""
    # DB 미설정·연결 실패. 이력이 없다는 것과 못 읽었다는 것을 available로 구분한다.
    # 왜 못 읽었는지는 로그에 남긴다 (DB를 일부러 끈 것인지, 고장인지)
    if not os.environ.get("DATABASE_URL"):
        log_failure("history_read", "not_configured")
        return HistoryResponse(items=[], available=False)
    try:
        with connect() as conn:
            rows = recent_queries(conn, session_id, limit)
    except Exception as e:
        log_failure("history_read", type(e).__name__)
        return HistoryResponse(items=[], available=False)

    return HistoryResponse(items=[HistoryItem(**row) for row in rows])
