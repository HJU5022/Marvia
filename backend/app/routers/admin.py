"""GET /api/me, /api/admin/* 운영자 관리 창구 (docs/specs/operator-admin.md).

창구만 한다: 로그인 확인 → 운영자 확인 → services.account.operators 부르기 → HTTP 응답으로 바꾸기.
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
from backend.app.services.account import operators as ops
from backend.app.services.account import customers as customers_svc
from backend.app.services.account import profile as profile_svc
from backend.app.services.account.account import WithdrawError

router = APIRouter(prefix="/api", tags=["admin"])

DB_DOWN = "운영자 정보를 읽지 못했습니다. 잠시 뒤 다시 시도하세요"


class MeResponse(BaseModel):
    user_id: str | None
    email: str | None
    is_operator: bool
    # 회원 정보(이름·전화·주소)를 입력했나. false면 화면이 입력 화면을 띄운다 (docs/specs/user-profile.md)
    profile_complete: bool = True


@router.get("/me", response_model=MeResponse)
def me(user: Annotated[CurrentUser | None, Depends(current_user)] = None) -> MeResponse:
    """화면이 탭을 나눌 때 묻는다. DB를 못 읽으면 운영자가 아닌 것으로 답한다 (EC-08). 관리 API는 따로 다시 확인한다."""
    if not user:  # 로그인 기능이 꺼진 환경 (EC-02). 회원 정보도 묻지 않는다 (user-profile EC-05)
        return MeResponse(user_id=None, email=None, is_operator=False)
    flag, complete = False, True
    if os.environ.get("DATABASE_URL"):
        try:
            with ops.open_conn() as conn:
                flag = ops.is_operator(conn, user.email)
                complete = profile_svc.exists(conn, user.id)
        except Exception as e:  # DB를 못 읽으면 입력 화면으로 막지 않는다 (user-profile EC-06)
            log_failure("operator_check", type(e).__name__)
            complete = True
    return MeResponse(user_id=user.id, email=user.email, is_operator=flag, profile_complete=complete)


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
    phone_masked: str | None = None
    address_masked: str | None = None
    profile_complete: bool = False  # 회원 정보를 입력했나
    is_suspended: bool = False  # 운영자가 일시 정지했나 (012)
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
            operator_hashes = ops.active_operator_hashes(conn)
            profiles = profile_svc.masked_by_user(conn)  # 이미 가린 값만 온다
            suspended = customers_svc.suspended_ids(conn)
    except Exception as e:
        log_failure("admin_customers", type(e).__name__)
        raise HTTPException(status_code=503, detail=DB_DOWN)
    items = []
    for c in ops.mask_customers(users, operator_hashes):
        p = profiles.get(c.user_id)
        # 이름은 직접 입력한 값을 먼저, 없으면 구글 이름 (user-profile Goal)
        items.append(CustomerItem(**{**c.__dict__, "name_masked": (p or {}).get("name") or c.name_masked,
                                     "phone_masked": (p or {}).get("phone"), "address_masked": (p or {}).get("address"),
                                     "profile_complete": p is not None, "is_suspended": c.user_id in suspended}))
    return CustomersResponse(items=items, total=len(items))


class OperatorItem(BaseModel):
    email: str
    granted_by: str
    granted_at: datetime
    granted_by_email: str | None = None  # 등록한 사람 이메일. 이력에서 못 찾으면 null (A5)


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
    "no_key": (503, "암호화 열쇠가 설정되지 않아 운영자 정보를 저장할 수 없습니다"),
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


# ── 고객 수정·강제 탈퇴·마스킹 해제 (docs/specs/operator-admin.md 추가 절) ──

class UnmaskBody(BaseModel):
    reason: str


class UnmaskResponse(BaseModel):
    email: str | None
    name: str | None
    phone: str | None
    address: str | None


class CustomerProfileBody(BaseModel):
    name: str
    phone: str
    address: str


class CustomerDeleteResponse(BaseModel):
    deleted_records: int


class ActionItem(BaseModel):
    action: Literal["customer_update", "customer_delete", "unmask", "customer_suspend", "customer_resume"]
    target_user_id: str
    target_email_masked: str | None
    actor_user_id: str
    actor_email: str | None
    reason: str | None
    created_at: datetime


_CUSTOMER_ERRORS = {
    "reason": (400, "사유를 10~500자로 적어 주세요"),
    "not_found": (404, "없는 고객입니다"),
    "is_operator": (409, "운영자 계정입니다. 운영자 해지를 먼저 하세요"),
    "self": (400, "자기 자신에게는 할 수 없습니다"),
    "already_suspended": (409, "이미 정지된 고객입니다"),
    "not_suspended": (409, "정지된 고객이 아닙니다"),
}


def _customer_call(stage: str, fn):
    """고객 동작 공통 오류 처리. 규칙 위반은 4xx, Supabase·DB 실패는 503."""
    try:
        with ops.open_conn() as conn:
            return fn(conn)
    except customers_svc.CustomerError as e:
        status, detail = _CUSTOMER_ERRORS[e.kind]
        raise HTTPException(status_code=status, detail=detail)
    except profile_svc.ProfileError as e:
        if e.kind == "no_key":
            raise HTTPException(status_code=503, detail="회원 정보를 안전하게 저장할 수 없습니다")
        raise HTTPException(status_code=400, detail={"name": "이름을 1~30자로 입력해 주세요",
                                                     "phone": "휴대전화 번호를 확인해 주세요",
                                                     "address": "주소를 5~200자로 입력해 주세요"}.get(e.kind, "입력값을 확인해 주세요"))
    except (AdminError, WithdrawError) as e:
        log_failure(stage, type(e).__name__)
        raise HTTPException(status_code=503, detail="처리하지 못했습니다. 잠시 뒤 다시 시도하세요")
    except Exception as e:
        log_failure(stage, type(e).__name__)
        raise HTTPException(status_code=503, detail=DB_DOWN)


@router.post("/admin/customers/{user_id}/unmask", response_model=UnmaskResponse)
def unmask_customer(user_id: str, body: UnmaskBody, user: Annotated[CurrentUser, Depends(require_operator)]) -> UnmaskResponse:
    """사유를 남기고 한 명의 원문. 기록이 먼저 되고, 기록 실패면 원문을 주지 않는다."""
    return UnmaskResponse(**_customer_call("admin_unmask",
                                           lambda c: customers_svc.unmask(c, user_id, user.id, user.email, body.reason)))


@router.put("/admin/customers/{user_id}/profile")
def update_customer(user_id: str, body: CustomerProfileBody, user: Annotated[CurrentUser, Depends(require_operator)]) -> dict:
    """이름·휴대전화·주소 수정. 응답은 가린 값 (화면은 목록을 다시 부른다)."""
    _customer_call("admin_update", lambda c: customers_svc.update(c, user_id, user.id, user.email, body.name, body.phone, body.address))
    return {"ok": True}


@router.delete("/admin/customers/{user_id}", response_model=CustomerDeleteResponse)
def delete_customer(user_id: str, user: Annotated[CurrentUser, Depends(require_operator)]) -> CustomerDeleteResponse:
    """강제 탈퇴. 기록 → 회원 정보 → 계정 순서 (services/account/account.withdraw)."""
    return CustomerDeleteResponse(deleted_records=_customer_call("admin_delete",
                                                                 lambda c: customers_svc.delete(c, user_id, user.id, user.email)))


@router.get("/admin/actions", response_model=list[ActionItem])
def admin_actions(_: Annotated[CurrentUser, Depends(require_operator)]) -> list[ActionItem]:
    """운영자 작업 이력 (수정·강제 탈퇴·마스킹 해제와 사유)."""
    return _customer_call("admin_actions", customers_svc.list_actions)


class ReasonBody(BaseModel):
    reason: str


@router.post("/admin/customers/{user_id}/suspend")
def suspend_customer(user_id: str, body: ReasonBody, user: Annotated[CurrentUser, Depends(require_operator)]) -> dict:
    """일시 정지. 사유 필수. Supabase 차단 + suspended_users (operator-admin 일시 정지 절)."""
    _customer_call("admin_suspend", lambda c: customers_svc.suspend(c, user_id, user.id, user.email, body.reason))
    return {"ok": True}


@router.post("/admin/customers/{user_id}/resume")
def resume_customer(user_id: str, user: Annotated[CurrentUser, Depends(require_operator)]) -> dict:
    """정지 해제."""
    _customer_call("admin_resume", lambda c: customers_svc.resume(c, user_id, user.id, user.email))
    return {"ok": True}


@router.get("/metrics")
def metrics(_: Annotated[CurrentUser, Depends(require_operator)]) -> dict:
    """평가지표 화면용. evals/results의 구성별 최신 결과를 읽기만 한다 (services/account/metrics.py). 운영자 전용."""
    from backend.app.services.account import metrics as metrics_svc  # 이 화면에서만 쓴다
    return metrics_svc.build()
