"""GET·PUT /api/profile 본인 회원 정보 (docs/specs/user-profile.md).

창구만 한다: 로그인 확인 → services.account.profile 부르기 → HTTP 응답. 검사·암호화·마스킹 규칙은 services/account/profile.py에 있다.
본인 정보라 원문을 돌려준다. 다른 사람 정보는 이 경로로 볼 수 없다 (user_id는 출입증에서만 꺼낸다).
"""
from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app.auth import CurrentUser, current_user
from backend.app.observability.logging import log_failure
from backend.app.services.account import operators as ops
from backend.app.services.account import profile as svc

router = APIRouter(prefix="/api", tags=["profile"])

DB_DOWN = "회원 정보 저장소에 연결하지 못했습니다. 잠시 뒤 다시 시도하세요"
_ERRORS = {
    "consent": "개인정보 수집·이용에 동의해야 저장할 수 있습니다",
    "name": "이름을 1~30자로 입력해 주세요",
    "phone": "휴대전화 번호를 확인해 주세요 (예: 010-1234-5678)",
    "address": "주소를 5~200자로 입력해 주세요",
}


class ProfileBody(BaseModel):
    name: str
    phone: str
    address: str
    consent: bool


class ProfileResponse(BaseModel):
    name: str
    phone: str  # 010-1234-5678 모양
    address: str


def _login_required(user: CurrentUser | None) -> CurrentUser:
    """로그인 기능이 꺼진 환경에는 사람이 없으니 회원 정보도 없다 (EC-05)."""
    if not user:
        raise HTTPException(status_code=401, detail="로그인한 사용자만 회원 정보를 쓸 수 있습니다",
                            headers={"WWW-Authenticate": "Bearer"})
    if not os.environ.get("DATABASE_URL"):
        raise HTTPException(status_code=503, detail=DB_DOWN)
    return user


@router.get("/profile", response_model=ProfileResponse)
def get_profile(user: Annotated[CurrentUser | None, Depends(current_user)] = None) -> ProfileResponse:
    """본인 정보 원문. 아직 없거나 열쇠가 바뀌어 못 열면 404 (화면은 입력 화면을 보여 준다, EC-07)."""
    user = _login_required(user)
    try:
        with ops.open_conn() as conn:
            p = svc.load(conn, user.id)
    except Exception as e:
        log_failure("profile_read", type(e).__name__)
        raise HTTPException(status_code=503, detail=DB_DOWN)
    if p is None:
        raise HTTPException(status_code=404, detail="회원 정보가 없습니다")
    return ProfileResponse(name=p.name, phone=svc.format_phone(p.phone), address=p.address)


@router.put("/profile", response_model=ProfileResponse)
def put_profile(body: ProfileBody, user: Annotated[CurrentUser | None, Depends(current_user)] = None) -> ProfileResponse:
    """저장(처음 입력과 수정 같음). 형식이 틀리면 400, 열쇠가 없으면 503 (EC-01~04)."""
    user = _login_required(user)
    try:
        p = svc.clean(body.name, body.phone, body.address, body.consent)
    except svc.ProfileError as e:
        raise HTTPException(status_code=400, detail=_ERRORS[e.kind])
    try:
        with ops.open_conn() as conn:
            svc.save(conn, user.id, p)
    except svc.ProfileError:  # no_key. 원문을 그대로 저장하지 않는다
        log_failure("profile_write", "no_key")
        raise HTTPException(status_code=503, detail="회원 정보를 안전하게 저장할 수 없습니다. 관리자에게 알려 주세요")
    except Exception as e:
        log_failure("profile_write", type(e).__name__)
        raise HTTPException(status_code=503, detail=DB_DOWN)
    return ProfileResponse(name=p.name, phone=svc.format_phone(p.phone), address=p.address)
