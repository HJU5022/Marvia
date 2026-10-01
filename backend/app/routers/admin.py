"""GET /api/me, /api/admin/* 운영자 관리 창구 (docs/specs/operator-admin.md).

창구만 한다: 로그인 확인 → 운영자 확인 → services.operators 부르기 → HTTP 응답으로 바꾸기.
운영자인지는 서명 확인한 출입증의 email로 서버가 정한다. 화면이 관리 탭을 숨기는 것은 편의일 뿐이다 (EC-01).
고객 목록 응답에는 가린 이메일·이름만 넣는다. 원문은 services 안에서 대조에만 쓰고 버린다.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app.auth import CurrentUser, current_user
from backend.app.clients.supabase_admin import AdminError, list_users
from backend.app.observability.logging import log_failure
from backend.app.services import operators as ops

router = APIRouter(prefix="/api", tags=["admin"])

DB_DOWN = "운영자 정보를 읽지 못했습니다. 잠시 뒤 다시 시도하세요"


class MeResponse(BaseModel):
    user_id: str | None
    email: str | None
    is_operator: bool


@router.get("/me", response_model=MeResponse)
def me(user: Annotated[CurrentUser | None, Depends(current_user)] = None) -> MeResponse:
    """화면이 탭을 나눌 때 묻는다. DB를 못 읽으면 운영자가 아닌 것으로 답한다 (EC-08). 관리 API는 따로 다시 확인한다."""
    if not user:  # 로그인 기능이 꺼진 환경 (EC-02)
        return MeResponse(user_id=None, email=None, is_operator=False)
    flag = False
    if os.environ.get("DATABASE_URL"):
        try:
            with ops.open_conn() as conn:
                flag = ops.is_operator(conn, user.email)
        except Exception as e:
            log_failure("operator_check", type(e).__name__)
    return MeResponse(user_id=user.id, email=user.email, is_operator=flag)


def require_operator(user: Annotated[CurrentUser | None, Depends(current_user)] = None) -> CurrentUser:
    """관리 API 입구. 로그인했고 활성 운영자여야 한다. 아니면 403 (EC-01, EC-02). DB가 없으면 503 (EC-08)."""
    if not user:
        raise HTTPException(status_code=403, detail="운영자만 쓸 수 있습니다")
    if not os.environ.get("DATABASE_URL"):
        raise HTTPException(status_code=503, detail=DB_DOWN)
    try:
        with ops.open_conn() as conn:
            allowed = ops.is_operator(conn, user.email)
    except Exception as e:
        log_failure("operator_check", type(e).__name__)
        raise HTTPException(status_code=503, detail=DB_DOWN)
    if not allowed:
        log_failure("operator_check", "forbidden")
        raise HTTPException(status_code=403, detail="운영자만 쓸 수 있습니다")
    return user


class CustomerItem(BaseModel):
    user_id: str
    email_masked: str | None
    name_masked: str | None
    created_at: datetime | None
    last_sign_in_at: datetime | None
    is_operator: bool


class CustomersResponse(BaseModel):
    items: list[CustomerItem]
    total: int


@router.get("/admin/customers", response_model=CustomersResponse)
def customers(_: Annotated[CurrentUser, Depends(require_operator)]) -> CustomersResponse:
    """가입자 목록. 이메일·이름은 가리고, 가입일과 마지막 로그인만 그대로 (Spec "Goal")."""
    try:
        users = list_users()
    except AdminError as e:  # 관리자 키 없음·호출 실패. 운영자 기능은 DB만 쓰므로 이 화면만 막힌다 (EC-07)
        log_failure("admin_customers", f"{e.kind} {e.code}" if e.code else e.kind)
        raise HTTPException(status_code=503, detail="고객 목록을 불러오지 못했습니다. 잠시 뒤 다시 시도하세요")
    try:
        with ops.open_conn() as conn:
            operator_emails = ops.active_operator_emails(conn)
    except Exception as e:
        log_failure("admin_customers", type(e).__name__)
        raise HTTPException(status_code=503, detail=DB_DOWN)
    items = [CustomerItem(**c.__dict__) for c in ops.mask_customers(users, operator_emails)]
    return CustomersResponse(items=items, total=len(items))


class OperatorItem(BaseModel):
    email: str
    granted_by: str
    granted_at: datetime


class AuditItem(BaseModel):
    action: Literal["grant", "revoke"]
    target_email: str
    actor_user_id: str
    actor_email: str | None
    created_at: datetime


class OperatorsResponse(BaseModel):
    operators: list[OperatorItem]
    audit: list[AuditItem]


@router.get("/admin/operators", response_model=OperatorsResponse)
def operators(_: Annotated[CurrentUser, Depends(require_operator)]) -> OperatorsResponse:
    """활성 운영자와 등록·해지 이력(최근 100건)."""
    try:
        with ops.open_conn() as conn:
            return OperatorsResponse(operators=ops.list_operators(conn), audit=ops.list_audit(conn))
    except Exception as e:
        log_failure("admin_operators", type(e).__name__)
        raise HTTPException(status_code=503, detail=DB_DOWN)


class EmailBody(BaseModel):
    email: str


# OperatorError 종류 → (HTTP 상태, 화면 문구). Spec Edge Cases 표와 같다
_ERRORS = {
    "invalid_email": (400, "이메일 형식을 확인해 주세요"),
    "already": (409, "이미 운영자입니다"),
    "not_found": (404, "활성 운영자가 아닙니다"),
    "self_revoke": (400, "자기 자신은 해지할 수 없습니다. 다른 운영자에게 요청하세요"),
}


def _change(action, body: EmailBody, user: CurrentUser) -> OperatorsResponse:
    """등록·해지 공통. 바꾼 뒤 최신 목록을 돌려줘 화면이 다시 부르지 않아도 되게 한다."""
    try:
        with ops.open_conn() as conn:
            action(conn, body.email, user.id, user.email)
            return OperatorsResponse(operators=ops.list_operators(conn), audit=ops.list_audit(conn))
    except ops.OperatorError as e:
        status, detail = _ERRORS[e.kind]
        raise HTTPException(status_code=status, detail=detail)
    except Exception as e:
        log_failure("admin_operator_change", type(e).__name__)
        raise HTTPException(status_code=503, detail=DB_DOWN)


@router.post("/admin/operators", response_model=OperatorsResponse)
def grant_operator(body: EmailBody, user: Annotated[CurrentUser, Depends(require_operator)]) -> OperatorsResponse:
    """이메일로 신규 운영자 등록. 가입 전이어도 된다. 그 이메일로 로그인하면 그때부터 운영자다."""
    return _change(ops.grant, body, user)


@router.post("/admin/operators/revoke", response_model=OperatorsResponse)
def revoke_operator(body: EmailBody, user: Annotated[CurrentUser, Depends(require_operator)]) -> OperatorsResponse:
    """운영자 해지. 자기 자신은 안 된다 (EC-04)."""
    return _change(ops.revoke, body, user)
