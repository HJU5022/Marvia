"""DELETE /api/account 회원 탈퇴 (삭제 3단계).

접수 창구만 한다: 로그인 확인 → services.account.account.withdraw 부르기 → 결과를 HTTP 응답으로 바꾸기.
무엇을 어떤 순서로 지우는지(기록 먼저, 계정 나중)와 그 이유는 services/account/account.py에 있다.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app.auth import current_user_id
from backend.app.observability.logging import log_failure
from backend.app.services.account.account import WithdrawError, withdraw

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
    try:
        deleted = withdraw(user_id)
    except WithdrawError as e:
        log_failure(e.stage, e.reason)
        raise HTTPException(status_code=503, detail=RETRY_LATER)
    return AccountDeleteResponse(deleted_records=deleted, account_deleted=True)
