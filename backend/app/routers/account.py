"""DELETE /api/account 회원 탈퇴 (삭제 3단계).

접수 창구만 한다: 로그인 확인 → 데모 계정이면 막기 → services.account.account.withdraw 부르기 → 결과를 HTTP 응답으로 바꾸기.
무엇을 어떤 순서로 지우는지(기록 먼저, 계정 나중)와 그 이유는 services/account/account.py에 있다.
"""
import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app.auth import CurrentUser, current_user
from backend.app.observability.logging import log_failure
from backend.app.services.account.account import WithdrawError, withdraw

router = APIRouter(prefix="/api", tags=["account"])

RETRY_LATER = "탈퇴를 끝내지 못했습니다. 잠시 뒤 다시 시도하세요"
# 화면은 403의 detail을 그대로 보여 준다 (web/lib/api.ts)
DEMO_BLOCKED = "데모 계정은 탈퇴할 수 없어요. 여러 사람이 같이 쓰는 계정이에요."


class AccountDeleteResponse(BaseModel):
    deleted_records: int  # 지운 조회 기록 수 (결과를 사용자에게 알린다, 제36조 ②와 같은 취지)
    account_deleted: bool  # 여기까지 오면 항상 true. 실패는 503으로 돌려준다


def _is_demo(user: CurrentUser) -> bool:
    """데모 계정인가 (docs/specs/demo-account.md). 서명 확인한 이메일만 본다. DEMO_ACCOUNT_EMAIL이 비면 아무도 아니다.

    [왜] 여러 사람이 같이 쓰는 계정이라, 누가 탈퇴하면 계정이 지워져 다음 사람이 들어오지 못한다.
    """
    demo = os.environ.get("DEMO_ACCOUNT_EMAIL", "").strip().lower()
    return bool(demo) and user.email == demo  # user.email은 auth.verified_email이 소문자로 맞춘 값


@router.delete("/account", response_model=AccountDeleteResponse)
def delete_my_account(user: Annotated[CurrentUser | None, Depends(current_user)] = None) -> AccountDeleteResponse:
    """로그인한 사용자의 기록과 계정을 지운다. 어느 단계든 실패하면 503이고, 다시 누르면 이어서 끝난다. 데모 계정은 403."""
    if not user:
        raise HTTPException(status_code=401, detail="로그인한 사용자만 탈퇴할 수 있습니다",
                            headers={"WWW-Authenticate": "Bearer"})
    if _is_demo(user):
        raise HTTPException(status_code=403, detail=DEMO_BLOCKED)
    try:
        deleted = withdraw(user.id)
    except WithdrawError as e:
        log_failure(e.stage, e.reason)
        raise HTTPException(status_code=503, detail=RETRY_LATER)
    return AccountDeleteResponse(deleted_records=deleted, account_deleted=True)
