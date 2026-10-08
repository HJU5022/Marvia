"""화물 지켜보기 /api (G5 등록·감시·알림, docs/Marvia_개발_작업_리스트.md).

창구만 한다: 로그인 확인 → services.watch.watch 부르기 → HTTP 응답. 최대 5건·반출 끝난 화물 제외 같은 규칙과
다시 판정·알림은 services/watch/watch.py에 있다.

  POST /api/cargo/watch/state   {"bl_no"}           → {"saved", "watch"}   결과 화면의 버튼 상태
  PUT  /api/cargo/watch         {"bl_no", "on"}     → {"watch"}            지켜보기 켜기·끄기
  GET  /api/watch                                   → {"items", "updated_at", "sample"}  지켜보는 화물 목록·위치
  GET  /api/watch/changes                           → {"changes": [...]}   안 본 판정 변화 (다음 접속 때 띠)
  POST /api/watch/changes/seen                      → {"cleared": 건수}    띠를 보여 줬으니 "봤음"으로

  GET    /api/watch/vessels             → {"items"}            B/L 없이 배만 지켜보는 목록
  POST   /api/watch/vessels  {mmsi | call_sign, name, flag?, dest?, eta?} → {"mmsi", "watch": true}   배 지켜보기 켜기
                                    (mmsi 없이 call_sign만 오면 ShipFinder 검색으로 MMSI를 정한다. 여러 척이면 name이 같은 배, 그다음 최근 신호. 한 척도 없으면 422,
                                    검색 실패 503, 하루 한도 소진은 503에 다른 안내문)
  DELETE /api/watch/vessels/{mmsi}      → {"mmsi", "watch": false}  배 지켜보기 끄기

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
from backend.app.services.account import operators as ops
from backend.app.services.watch import vessel_watch as vsvc
from backend.app.services.watch import watch as svc

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


class VesselBody(BaseModel):
    """채팅에서 본 배. name 이하는 사용자가 본 글 그대로의 표시용 값이다 (services/watch/vessel_watch.py)."""
    mmsi: int | None = None
    call_sign: str | None = None  # 입항 예정 목록처럼 MMSI가 없는 곳에서 온다. mmsi가 있으면 쓰지 않는다
    name: str
    flag: str | None = None
    dest: str | None = None
    eta: str | None = None


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


@router.get("/watch")
def get_watch_list(user: Annotated[CurrentUser | None, Depends(current_user)] = None) -> dict:
    """감시 목록 화면이 부른다. 지켜보는 화물마다 마지막 조회 값과 배 위치·지나온 길 (services/watch/watch.watch_list)."""
    user = _login_required(user)
    try:
        with ops.open_conn() as conn:
            return svc.watch_list(conn, user.id)
    except Exception as e:
        log_failure("watch_list", type(e).__name__)
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


# ── B/L 없이 배만 지켜보기. 기존 B/L 지켜보기와 표·규칙을 섞지 않는다 ──

_VESSEL_ERRORS = {
    "limit": (409, "배 지켜보기는 최대 5척까지입니다. 다른 배를 먼저 끄세요"),
    "invalid": (422, "배 번호(MMSI) 또는 호출부호와 이름이 필요합니다"),
    "unknown_vessel": (422, "이 배의 선박 번호를 확인하지 못해 지켜볼 수 없어요."),
    "lookup_failed": (503, "선박 번호를 찾는 중 문제가 생겼어요. 잠시 뒤 다시 시도해 주세요."),
    # 하루 한도 소진은 다시 눌러도 오늘은 같으므로 안내를 따로 둔다
    "quota_exhausted": (503, "오늘 선박 조회 한도를 다 썼어요. 내일 다시 시도해 주세요."),
}


@router.get("/watch/vessels")
def get_vessel_watches(user: Annotated[CurrentUser | None, Depends(current_user)] = None) -> dict:
    """배만 지켜보는 목록과 마지막 위치·지나온 길. 판정은 없다."""
    user = _login_required(user)
    try:
        with ops.open_conn() as conn:
            # refresh: 위치가 없거나 오래된 배는 지금 받아 채운다
            return vsvc.list_vessels(conn, user.id, refresh=True)
    except Exception as e:
        log_failure("vessel_watch_list", type(e).__name__)
        raise HTTPException(status_code=503, detail=DB_DOWN)


@router.post("/watch/vessels")
def add_vessel_watch(body: VesselBody, user: Annotated[CurrentUser | None, Depends(current_user)] = None) -> dict:
    """채팅에서 본 배를 지켜보기에 올린다. 같은 배를 다시 올리면 보인 값만 갱신한다."""
    user = _login_required(user)
    try:
        mmsi = body.mmsi
        if not mmsi:
            # DB 연결을 열기 전에 찾는다: 외부 검색이 느려도 연결을 붙잡고 있지 않게
            if not (body.call_sign or "").strip():
                raise vsvc.VesselWatchError("invalid")
            # name은 같은 호출부호의 여러 배 중 이름이 같은 배를 고르는 데 쓴다
            mmsi = vsvc.resolve_mmsi(body.call_sign, body.name)
        with ops.open_conn() as conn:
            return vsvc.add_vessel(conn, user.id, mmsi, body.name, body.flag, body.dest, body.eta, body.call_sign)
    except vsvc.VesselWatchError as e:
        log_failure("vessel_watch_add", e.kind)
        status, detail = _VESSEL_ERRORS[e.kind]
        raise HTTPException(status_code=status, detail=detail)
    except Exception as e:
        log_failure("vessel_watch_add", type(e).__name__)
        raise HTTPException(status_code=503, detail=DB_DOWN)


@router.delete("/watch/vessels/{mmsi}")
def remove_vessel_watch(mmsi: int, user: Annotated[CurrentUser | None, Depends(current_user)] = None) -> dict:
    """배 지켜보기를 푼다. 켜져 있지 않아도 오류가 아니다."""
    user = _login_required(user)
    try:
        with ops.open_conn() as conn:
            return vsvc.remove_vessel(conn, user.id, mmsi)
    except Exception as e:
        log_failure("vessel_watch_remove", type(e).__name__)
        raise HTTPException(status_code=503, detail=DB_DOWN)
