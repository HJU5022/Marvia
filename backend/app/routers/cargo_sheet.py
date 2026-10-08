"""내 화물 현황 표 /api (019, 아버지가 손으로 쓰는 관리표 기준).

창구만 한다: 로그인 확인 → services.watch.cargo_sheet 부르기 → HTTP 응답. 묶는 규칙·신용장 처리·엑셀 만들기는 서비스에 있다.

  GET /api/cargo/sheet                          → {"groups": [{"lc": {...}|null, "rows": [...]}], "truncated": bool}  신용장별로 묶은 표 (truncated: 500줄 넘어 잘림)
  PUT /api/cargo/sheet/{cargo_key}/lc           {"lc_no", "opened_on"}      → 바뀐 표   신용장 잇기·풀기 (lc_no null이면 풀기, opened_on null이면 개설일 비움, 키 생략이면 유지)
  PUT /api/cargo/sheet/{cargo_key}/departed     {"departed_on", "source"}   → 바뀐 표   출항일 쓰기
  GET /api/cargo/sheet.xlsx                     → 엑셀 파일 (Content-Disposition: attachment)

주소에 들어가는 cargo_key는 B/L을 되돌릴 수 없게 바꾼 지문(HMAC)이다. B/L 번호 자체는 주소에도 응답 JSON에도 없다 (SDD 3.5).
그 사용자의 화물이 아니면 404다. 남의 지문과 없는 지문을 구별해 주지 않는다. 모두 로그인한 사용자 것만 다룬다 (user_id는 출입증에서만).
"""
from __future__ import annotations

import os
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, field_validator

from backend.app.auth import CurrentUser, current_user
from backend.app.observability.logging import log_failure
from backend.app.services.watch import cargo_sheet as svc
from backend.app.services.account import operators as ops

router = APIRouter(prefix="/api/cargo", tags=["cargo-sheet"])

DB_DOWN = "화물 현황 표 저장소에 연결하지 못했습니다. 잠시 뒤 다시 시도하세요"
NOT_FOUND = "이 화물을 찾을 수 없습니다"


class LcBody(BaseModel):
    """신용장 번호와 개설일. lc_no가 null이면 신용장에서 푼다."""

    lc_no: str | None = None
    opened_on: date | None = None

    @field_validator("lc_no")
    @classmethod
    def _check_lc_no(cls, value: str | None) -> str | None:
        """길이·제어 문자 규칙은 서비스 한 곳(clean_lc_no)에 있다. 어기면 422로 나간다."""
        return None if value is None else svc.clean_lc_no(value)


class DepartedBody(BaseModel):
    """출항일과 출처. source 기본값 manual은 사용자가 직접 넣는 길이다. document는 도착 통지서 사진에서 읽은 값이다."""

    departed_on: date | None = None
    source: Literal["manual", "document"] = "manual"


def _login_required(user: CurrentUser | None) -> CurrentUser:
    """로그인 기능이 꺼진 환경에는 사람이 없으니 표도 없다 (routers/watch.py와 같은 규칙)."""
    if not user:
        raise HTTPException(status_code=401, detail="로그인한 사용자만 화물 현황 표를 쓸 수 있습니다",
                            headers={"WWW-Authenticate": "Bearer"})
    if not os.environ.get("DATABASE_URL"):
        raise HTTPException(status_code=503, detail=DB_DOWN)
    return user


@router.get("/sheet")
def get_sheet(user: Annotated[CurrentUser | None, Depends(current_user)] = None) -> dict:
    """신용장별로 묶은 내 화물 현황 표."""
    user = _login_required(user)
    try:
        with ops.open_conn() as conn:
            return svc.load_sheet(conn, user.id)
    except Exception as e:
        log_failure("cargo_sheet_read", type(e).__name__)
        raise HTTPException(status_code=503, detail=DB_DOWN)


@router.get("/sheet.xlsx")
def get_sheet_xlsx(user: Annotated[CurrentUser | None, Depends(current_user)] = None) -> Response:
    """엑셀로 내려받기. 파일은 서버에 남기지 않고 바로 돌려준다. 캐시도 막는다(개인 화물 목록이라 중간에 남기지 않는다)."""
    user = _login_required(user)
    try:
        with ops.open_conn() as conn:
            data = svc.build_xlsx(conn, user.id)
    except Exception as e:
        log_failure("cargo_sheet_xlsx", type(e).__name__)
        raise HTTPException(status_code=503, detail=DB_DOWN)
    return Response(content=data, media_type=svc.XLSX_MIME, headers={
        "Content-Disposition": f'attachment; filename="{svc.xlsx_filename()}"', "Cache-Control": "no-store"})


def _write(user: CurrentUser | None, action: str, write) -> dict:
    """PUT 둘이 같이 쓰는 틀. 쓰고 나서 바뀐 표를 돌려준다. 없는 화물은 404, DB 실패는 503(내용은 알리지 않는다)."""
    user = _login_required(user)
    try:
        with ops.open_conn() as conn:
            write(conn, user.id)
            return svc.load_sheet(conn, user.id)
    except svc.CargoNotFound:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    except Exception as e:
        log_failure(action, type(e).__name__)
        raise HTTPException(status_code=503, detail=DB_DOWN)


@router.put("/sheet/{cargo_key}/lc")
def put_lc(cargo_key: str, body: LcBody, user: Annotated[CurrentUser | None, Depends(current_user)] = None) -> dict:
    """화물 한 건을 신용장에 잇거나(lc_no 있음) 푼다(lc_no null).
    개설일: 요청에 opened_on 키가 없으면 기존 값을 두고, 명시적으로 null을 보내면 비운다 (model_fields_set으로 가른다, S3)."""
    return _write(user, "cargo_sheet_lc", lambda conn, uid: svc.set_lc(conn, uid, cargo_key, body.lc_no, body.opened_on,
                                                    clear_opened="opened_on" in body.model_fields_set))


@router.put("/sheet/{cargo_key}/departed")
def put_departed(cargo_key: str, body: DepartedBody,
                 user: Annotated[CurrentUser | None, Depends(current_user)] = None) -> dict:
    """출항일을 쓴다. departed_on이 null이면 지운다."""
    return _write(user, "cargo_sheet_departed",
                  lambda conn, uid: svc.set_departed(conn, uid, cargo_key, body.departed_on, body.source))
