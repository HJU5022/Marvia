"""카카오톡 "나에게 보내기" 알림 연결 /api/kakao (카카오 로그인 REST API 문서).

창구만 한다: 로그인 확인 → services.watch.kakao 부르기 → HTTP 응답. 토큰 보관·갱신·state 서명 규칙은 services/watch/kakao.py에 있다.

POST /callback도 로그인이 필요하다. 카카오 동의 화면이 끝나면 브라우저는 백엔드가 아니라 우리 화면
(/settings/kakao)으로 돌아오고, 그 화면이 인가 코드와 state를 들고 로그인 출입증(Bearer 헤더)과 함께 이 주소를 부른다.
예전에는 카카오가 백엔드 GET /callback으로 바로 돌아왔다. 그 요청에는 출입증이 없어서 state 속 user_id를 믿을 수밖에 없었고,
공격자가 자기 동의 링크를 피해자에게 보내면 피해자의 카카오 토큰이 공격자 계정에 저장될 수 있었다.
이제는 state를 만든 사람(user_id)과 지금 로그인한 사용자가 같을 때만 저장한다. 다르면 mismatch로 끝내고 인가 코드도 쓰지 않는다.
결과는 늘 HTTP 200 {"result": 이름}으로 알린다. 화면이 이름을 보고 안내 문구를 고른다:
connected / expired / mismatch / no_consent / failed. 사용자가 동의 화면에서 '취소'를 누른 경우(denied)는
카카오가 화면 주소에 error를 붙여 보내므로 화면이 알아서 처리하고, 백엔드는 부르지 않는다.
응답에는 결과 이름 하나만 담는다. 오류 내용·토큰·인가 코드는 넣지 않는다.

보내기(/test)는 재시도하지 않는다. 실패하면 사용자가 다시 누른다 (같은 메시지가 두 번 가지 않게, services/watch/kakao.py).
"""
from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app.auth import CurrentUser, current_user
from backend.app.clients import kakao
from backend.app.clients.kakao import KakaoError
from backend.app.observability.logging import log_failure
from backend.app.services.watch import kakao as svc
from backend.app.services.account import operators as ops

router = APIRouter(prefix="/api/kakao", tags=["kakao"])

DB_DOWN = "연결 정보 저장소에 연결하지 못했습니다. 잠시 뒤 다시 시도하세요"
NOT_CONFIGURED = "카카오톡 알림이 아직 준비되지 않았습니다. 관리자에게 알려 주세요"
TEST_TEXT = "[Marvia] 카카오톡 알림이 연결되었습니다. 화물 판정이 바뀌면 이 채팅방으로 알려 드립니다."
# 시험 발송 실패를 (상태 코드, 사용자가 할 수 있는 안내)로 바꾼다. 키는 서비스 kind와 카카오 kind를 같이 쓴다
_TEST_ERRORS = {
    "not_linked": (404, "카카오톡이 연결되어 있지 않습니다. 먼저 연결해 주세요"),
    "relink": (409, "카카오톡 연결이 끊어졌습니다. 다시 연결해 주세요"),
    "no_consent": (403, "카카오톡 메시지 전송에 동의하지 않았습니다. 연결을 다시 하고 '카카오톡 메시지 전송'에 동의해 주세요"),
    "not_configured": (503, NOT_CONFIGURED),
    "no_key": (503, "연결 정보를 안전하게 열 수 없습니다. 관리자에게 알려 주세요"),
}
_TEST_FAILED = (502, "카카오톡으로 보내지 못했습니다. 잠시 뒤 다시 시도하세요")


def _login_required(user: CurrentUser | None) -> CurrentUser:
    """로그인 기능이 꺼진 환경에는 사람이 없으니 연결할 계정도 없다 (routers/profile.py와 같은 규칙)."""
    if not user:
        raise HTTPException(status_code=401, detail="로그인한 사용자만 카카오톡 알림을 쓸 수 있습니다",
                            headers={"WWW-Authenticate": "Bearer"})
    if not os.environ.get("DATABASE_URL"):
        raise HTTPException(status_code=503, detail=DB_DOWN)
    return user


def _web() -> str:
    """화면 주소. ALLOWED_ORIGINS(쉼표로 여럿)의 첫 항목, 끝 슬래시 없이. main.py의 CORS 기본값과 같다."""
    first = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000").split(",")[0].strip()
    return (first or "http://localhost:3000").rstrip("/")


def _configured() -> bool:
    try:
        kakao.config()
    except KakaoError:
        return False
    return True


@router.get("/status")
def get_status(user: Annotated[CurrentUser | None, Depends(current_user)] = None) -> dict:
    """화면이 연결 버튼을 보여 줄지 정한다. configured: 서버에 카카오 키가 있나, linked: 이 사용자가 연결했나."""
    user = _login_required(user)
    try:
        with ops.open_conn() as conn:
            times = svc.link_times(conn, user.id)
    except Exception as e:
        log_failure("kakao_status", type(e).__name__)
        raise HTTPException(status_code=503, detail=DB_DOWN)
    return {"configured": _configured(), "linked": times is not None,
            "linked_at": times[0] if times else None, "last_sent_at": times[1] if times else None}


@router.post("/connect")
def connect(user: Annotated[CurrentUser | None, Depends(current_user)] = None) -> dict:
    """카카오 동의 화면 주소를 돌려준다. 화면이 그 주소로 브라우저를 보낸다."""
    user = _login_required(user)
    try:
        return {"url": kakao.authorize_url(svc.make_state(user.id))}
    except KakaoError as e:
        log_failure("kakao_connect", e.kind)
        raise HTTPException(status_code=503, detail=NOT_CONFIGURED)


class CallbackBody(BaseModel):
    """화면이 카카오에서 돌아온 주소(?code=...&state=...)에서 읽어 보내는 값."""

    code: str
    state: str


def _link_result(user_id: str, code: str, state: str) -> str:
    """callback을 처리하고 결과 이름만 돌려준다: connected / expired / mismatch / no_consent / failed.
    순서가 중요하다: state 확인 → 로그인한 사람과 같은지 → 코드 교환 → 동의 항목 → 저장.
    state가 만료됐거나 다른 사람 것이면 일회용 인가 코드를 쓰지 않는다."""
    state_user = svc.read_state(state)
    if state_user is None:
        return "expired"
    if state_user != user_id:  # 남이 만든 동의 링크로 내 토큰이 그 사람 계정에 붙는 것을 막는다
        log_failure("kakao_callback", "mismatch")
        return "mismatch"
    if not code:
        return "failed"
    try:
        tokens = kakao.exchange_code(code)
        # 메시지 전송 동의(talk_message)를 체크하지 않고 넘어온 경우. 보낼 수 없는 토큰은 저장하지 않는다
        if kakao.SCOPE not in (tokens.scope or "").split():
            return "no_consent"
        with ops.open_conn() as conn:
            svc.save_link(conn, user_id, tokens)
    except KakaoError as e:
        log_failure("kakao_callback", e.kind)
        return "failed"
    except svc.KakaoLinkError as e:
        log_failure("kakao_callback", e.kind)
        return "failed"
    except Exception as e:  # DB 연결·SQL 실패. 종류만 남긴다
        log_failure("kakao_callback", type(e).__name__)
        return "failed"
    return "connected"


@router.post("/callback")
def callback(body: CallbackBody, user: Annotated[CurrentUser | None, Depends(current_user)] = None) -> dict:
    """우리 화면이 카카오에서 받은 인가 코드와 state를 보내는 곳. 로그인한 사용자 계정에 연결한다. 결과는 늘 200."""
    user = _login_required(user)
    return {"result": _link_result(user.id, body.code, body.state)}


@router.post("/test")
def send_test(user: Annotated[CurrentUser | None, Depends(current_user)] = None) -> dict:
    """연결이 되었는지 시험 메시지를 한 통 보낸다."""
    user = _login_required(user)
    try:
        with ops.open_conn() as conn:
            svc.send_to_user(conn, user.id, TEST_TEXT, f"{_web()}/settings")
    except (svc.KakaoLinkError, KakaoError) as e:
        log_failure("kakao_test", e.kind)
        status, detail = _TEST_ERRORS.get(e.kind, _TEST_FAILED)
        raise HTTPException(status_code=status, detail=detail)
    except Exception as e:
        log_failure("kakao_test", type(e).__name__)
        raise HTTPException(status_code=503, detail=DB_DOWN)
    return {"sent": True}


@router.delete("/link")
def unlink(user: Annotated[CurrentUser | None, Depends(current_user)] = None) -> dict:
    """연결 해제. 카카오 쪽 연결도 끊고 우리 토큰을 지운다."""
    user = _login_required(user)
    try:
        with ops.open_conn() as conn:
            svc.unlink_user(conn, user.id)
    except Exception as e:
        log_failure("kakao_unlink", type(e).__name__)
        raise HTTPException(status_code=503, detail=DB_DOWN)
    return {"linked": False}
