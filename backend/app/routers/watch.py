"""화물 지켜보기 /api (G5 등록·감시·알림, 10-05 결정, docs/Marvia_개발_작업_리스트.md).

창구만 한다: 로그인 확인 → services.watch 부르기 → HTTP 응답. 최대 5건·반출 끝난 화물 제외 같은 규칙과
다시 판정·알림은 services/watch.py에 있다.

  POST /api/cargo/watch/state   {"bl_no"}           → {"saved", "watch"}   결과 화면의 버튼 상태
  PUT  /api/cargo/watch         {"bl_no", "on"}     → {"watch"}            지켜보기 켜기·끄기
  GET  /api/watch/changes                           → {"changes": [...]}   안 본 판정 변화 (다음 접속 때 띠)
  POST /api/watch/changes/seen                      → {"cleared": 건수}    띠를 보여 줬으니 "봤음"으로

B/L 번호는 주소에 넣지 않고 요청 본문(JSON)으로만 받는다. 주소는 접속 로그·브라우저 기록에 남기 때문이다 (SDD 3.5).
그래서 상태 조회도 GET이 아니라 POST다. 응답에는 B/L을 되돌려 주지 않는다. 변화 목록은 가린 번호(bl_masked)만 담는다.
모두 로그인한 사용자 것만 다룬다 (user_id는 출입증에서만 꺼낸다).
"""
from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app.auth import CurrentUser, current_user
from backend.app.observability.logging import log_failure
from backend.app.services import operators as ops
from backend.app.services import watch as svc

router = APIRouter(prefix="/api", tags=["watch"])

DB_DOWN = "지켜보기 저장소에 연결하지 못했습니다. 잠시 뒤 다시 시도하세요"
# 켜기 실패를 (상태 코드, 사용자가 할 수 있는 안내)로 바꾼다. 키는 서비스의 WatchError.kind
_ERRORS = {
    "not_saved": (404, "이 화물은 아직 저장되지 않았습니다. 잠시 뒤 다시 눌러 주세요"),
    "done": (409, "반출이 끝난 화물은 지켜볼 수 없습니다"),
    "limit": (409, "지켜보기는 최대 5건까지입니다. 다른 화물을 먼저 끄세요"),
    "no_key": (503, "화물 정보를 안전하게 열 수 없습니다. 관리자에게 알려 주세요"),
}


class StateBody(BaseModel):
    bl_no: str


class WatchBody(BaseModel):
    bl_no: str
    on: bool


def _login_required(user: CurrentUser | None) -> CurrentUser:
    """로그인 기능이 꺼진 환경에는 사람이 없으니 지켜볼 화물도 없다 (routers/profile.py와 같은 규칙)."""
    if not user:
        raise HTTPException(status_code=401, detail="로그인한 사용자만 화물을 지켜볼 수 있습니다",
                            headers={"WWW-Authenticate": "Bearer"})
    if not os.environ.get("DATABASE_URL"):
        raise HTTPException(status_code=503, detail=DB_DOWN)
    return user


@router.post("/cargo/watch/state")
def get_state(body: StateBody, user: Annotated[CurrentUser | None, Depends(current_user)] = None) -> dict:
    """화면이 "지켜보기" 버튼을 켤 수 있는지(saved)와 이미 켜져 있는지(watch) 정한다."""
    user = _login_required(user)
    try:
        with ops.open_conn() as conn:
            return svc.watch_state(conn, user.id, body.bl_no)
    except Exception as e:
        log_failure("watch_state", type(e).__name__)
        raise HTTPException(status_code=503, detail=DB_DOWN)


@router.put("/cargo/watch")
def put_watch(body: WatchBody, user: Annotated[CurrentUser | None, Depends(current_user)] = None) -> dict:
    """지켜보기를 켜거나 끈다. 돌려주는 watch는 바뀐 뒤 상태다."""
    user = _login_required(user)
    try:
        with ops.open_conn() as conn:
            return {"watch": svc.set_watch(conn, user.id, body.bl_no, body.on)}
    except svc.WatchError as e:
        log_failure("watch_set", e.kind)
        status, detail = _ERRORS[e.kind]
        raise HTTPException(status_code=status, detail=detail)
    except Exception as e:
        log_failure("watch_set", type(e).__name__)
        raise HTTPException(status_code=503, detail=DB_DOWN)


@router.get("/watch/changes")
def get_changes(user: Annotated[CurrentUser | None, Depends(current_user)] = None) -> dict:
    """아직 못 본 판정 변화. 화면이 접속할 때 불러 띠로 보여 준다."""
    user = _login_required(user)
    try:
        with ops.open_conn() as conn:
            return {"changes": svc.pending_changes(conn, user.id)}
    except Exception as e:
        log_failure("watch_changes", type(e).__name__)
        raise HTTPException(status_code=503, detail=DB_DOWN)


@router.post("/watch/changes/seen")
def post_seen(user: Annotated[CurrentUser | None, Depends(current_user)] = None) -> dict:
    """띠를 보여 줬으니 안 본 변화를 모두 "봤음"으로 바꾼다."""
    user = _login_required(user)
    try:
        with ops.open_conn() as conn:
            return {"cleared": svc.mark_seen(conn, user.id)}
    except Exception as e:
        log_failure("watch_seen", type(e).__name__)
        raise HTTPException(status_code=503, detail=DB_DOWN)
