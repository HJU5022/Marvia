"""GET /api/history (작업 A12, SDD 4.4).

세션의 지난 조회를 목록으로 돌려준다. 로그인했으면 세션 대신 사용자 기준으로 돌려준다 (G3). 새로 계산하거나 저장하지 않고 query_log를 읽기만 한다.
B/L은 bl_masked로만 나간다 (SDD 3.5, 7절).

DB가 없거나 꺼져 있으면 빈 목록을 돌려준다. 이력은 부가 기능이라 이것 때문에 화면이 죽으면 안 된다.
"""
import os
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.app.auth import current_user_id
from backend.app.db import connect, delete_user_queries, recent_queries
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
    user_id: Annotated[str | None, Depends(current_user_id)] = None,
) -> HistoryResponse:
    """이 세션이 지금까지 무엇을 조회했는지 최신순으로 돌려준다.
    로그인했으면(user_id) 브라우저와 상관없이 그 사용자의 조회 전부를 돌려준다."""
    # DB 미설정·연결 실패. 이력이 없다는 것과 못 읽었다는 것을 available로 구분한다.
    # 왜 못 읽었는지는 로그에 남긴다 (DB를 일부러 끈 것인지, 고장인지)
    if not os.environ.get("DATABASE_URL"):
        log_failure("history_read", "not_configured")
        return HistoryResponse(items=[], available=False)
    try:
        with connect() as conn:
            rows = recent_queries(conn, session_id, limit, user_id)
    except Exception as e:
        log_failure("history_read", type(e).__name__)
        return HistoryResponse(items=[], available=False)

    return HistoryResponse(items=[HistoryItem(**row) for row in rows])


class DeleteResponse(BaseModel):
    deleted: int  # 지운 줄 수. 사용자에게 결과를 알리는 값이다 (제36조 ②)


@router.delete("/history", response_model=DeleteResponse)
def delete_history(user_id: Annotated[str | None, Depends(current_user_id)] = None) -> DeleteResponse:
    """로그인한 사용자가 자기 조회 기록을 전부 지운다 (삭제 2단계, 개인정보보호법 제36조 삭제 요구).

    로그인 필수다(09-30). 로그인 기능이 꺼진 채점 환경은 사용자가 없어 401이다. 그 환경의 기록은 90일 자동 삭제(008)로 정리된다.
    조회(GET)와 달리 실패를 빈 결과로 숨기지 않는다. 지운 줄 알았는데 남아 있으면 안 되므로 503으로 알린다.
    """
    if not user_id:
        raise HTTPException(status_code=401, detail="로그인한 사용자만 기록을 삭제할 수 있습니다",
                            headers={"WWW-Authenticate": "Bearer"})
    if not os.environ.get("DATABASE_URL"):
        log_failure("history_delete", "not_configured")
        raise HTTPException(status_code=503, detail="기록 저장소에 연결하지 못해 삭제하지 못했습니다. 잠시 뒤 다시 시도하세요")
    try:
        with connect() as conn:
            deleted = delete_user_queries(conn, user_id)
    except Exception as e:
        log_failure("history_delete", type(e).__name__)
        raise HTTPException(status_code=503, detail="기록 저장소에 연결하지 못해 삭제하지 못했습니다. 잠시 뒤 다시 시도하세요")
    return DeleteResponse(deleted=deleted)
