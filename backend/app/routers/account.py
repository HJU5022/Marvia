"""DELETE /api/account 회원 탈퇴 (삭제 3단계, 개인정보보호법 제37조 동의 철회 → 지체 없이 파기).

순서가 중요하다: 우리 조회 기록을 먼저 지우고, 그다음 Supabase 계정을 지운다.
  - 계정을 먼저 지웠는데 기록 삭제가 실패하면, 그 사람은 로그인을 못 해 다시 탈퇴할 수도 없고 기록만 주인 없이 남는다
  - 기록을 먼저 지우면, 계정 삭제가 실패해도 아직 로그인된 상태라 탈퇴를 다시 누를 수 있다
기록 삭제는 "내 기록 삭제"(routers/history.py, db.delete_user_queries)와 같은 함수를 쓴다.

한계: 탈퇴 직후에도 이미 받은 출입증은 남은 기한(보통 1시간) 동안 우리 확인기(auth.py)를 통과한다.
출입증에 기한이 적혀 있을 뿐 계정이 지워졌는지는 Supabase에 따로 묻지 않기 때문이다. 화면이 탈퇴 직후 로그아웃시킨다.
"""
import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app.auth import current_user_id
from backend.app.clients.supabase_admin import AdminError, delete_account
from backend.app.db import connect, delete_user_queries
from backend.app.observability.logging import log_failure

router = APIRouter(prefix="/api", tags=["account"])

RETRY_LATER = "탈퇴를 끝내지 못했습니다. 잠시 뒤 다시 시도하세요"


class AccountDeleteResponse(BaseModel):
    deleted_records: int  # 지운 조회 기록 수 (결과를 사용자에게 알린다, 제36조 ②와 같은 취지)
    account_deleted: bool  # 여기까지 오면 항상 true. 실패는 503으로 돌려준다


@router.delete("/account", response_model=AccountDeleteResponse)
def delete_my_account(user_id: Annotated[str | None, Depends(current_user_id)] = None) -> AccountDeleteResponse:
    """로그인한 사용자의 기록과 계정을 지운다. 어느 단계든 실패하면 503이고, 다시 누르면 이어서 끝난다."""
    if not user_id:
        raise HTTPException(status_code=401, detail="로그인한 사용자만 탈퇴할 수 있습니다",
                            headers={"WWW-Authenticate": "Bearer"})

    # 1) 우리 기록 먼저. 못 지우면 계정은 건드리지 않는다
    if not os.environ.get("DATABASE_URL"):
        log_failure("account_records", "not_configured")
        raise HTTPException(status_code=503, detail=RETRY_LATER)
    try:
        with connect() as conn:
            deleted = delete_user_queries(conn, user_id)
    except Exception as e:
        log_failure("account_records", type(e).__name__)
        raise HTTPException(status_code=503, detail=RETRY_LATER)

    # 2) 계정. 실패해도 기록은 이미 지워졌다. 다시 누르면 기록 0건 + 계정 삭제로 이어진다
    try:
        delete_account(user_id)
    except AdminError as e:
        log_failure("account_delete", f"{e.kind} {e.code}" if e.code else e.kind)
        raise HTTPException(status_code=503, detail=RETRY_LATER)

    return AccountDeleteResponse(deleted_records=deleted, account_deleted=True)
