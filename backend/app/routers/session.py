"""세션 API 3개. (SDD 1절·2절)

  GET    /api/session/{id}                    공유 링크. 세션 + 마지막 결과
  DELETE /api/session/{id}                    주선자 본인만. 즉시 삭제
  PATCH  /api/session/{id}/participants/{idx} 참석자 본인 출발지 수정 — 자리만 (설계는 별도 세션)

셋 다 로그인 필수 (결정 4: /health 빼고 전부). `Depends(current_user)` 한 줄이 그 역할이다.
DB는 직접 만지지 않고 services/store.py 함수만 부른다. 이 파일은 "요청 받기 → store 부르기 → 상태 코드 정하기"만.

POST /api/agent(파이프라인)는 routers/agent.py 에 따로 둔다 (SDD 1절).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from backend.app.schemas.session import SessionRead
from backend.app.services import store
from backend.app.services.auth import current_user

router = APIRouter(prefix="/api/session", tags=["session"])


@router.get("/{session_id}", response_model=SessionRead)
async def read_session(session_id: str, user_id: str = Depends(current_user)) -> SessionRead:
    """공유 링크로 들어온 사람에게 세션과 가장 최근 결과를 돌려준다.

    로그인한 사람이 이 세션의 참석자인지는 확인하지 않는다 — 링크를 아는 사람은 누구나 (SDD 2절, 미결 "참석자 ↔ 계정 연결").
    없거나 만료면 404. get_session이 만료 행을 None으로 주므로 여기선 None만 보면 된다.
    """
    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="세션이 없거나 만료되었습니다")

    result = await store.get_latest_result(session_id)
    return SessionRead(
        **session,
        locked=store.is_locked(session["meet_at"]),
        result=result,
    )


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str, user_id: str = Depends(current_user)) -> Response:
    """주선자가 세션을 지운다 (결정 7). 즉시 삭제, results는 DB가 같이 지운다(CASCADE).

    "본인만"은 store.delete_session이 SQL WHERE로 보장한다. False면 남의 세션이거나 없는 것 → 403.
    둘을 구분하지 않는 이유: "그런 세션 없음"과 "네 것 아님"을 나눠 주면 세션 id 존재 여부가 새어 나간다.
    204는 본문 없이 "됐다"만 뜻한다.
    """
    deleted = await store.delete_session(session_id, user_id)
    if not deleted:
        raise HTTPException(status_code=403, detail="본인 세션만 삭제할 수 있습니다")
    return Response(status_code=204)


@router.patch("/{session_id}/participants/{idx}", status_code=501)
async def update_participant(session_id: str, idx: int, user_id: str = Depends(current_user)) -> dict:
    """참석자 본인 출발지 수정 — 자리만 잡아 둔다 (SDD 2절 PATCH, 결정 11·15).

    본문 모양·재계산 범위(경로만 다시, LLM 없음)·본인 확인 방법은 별도 설계 세션에서 정한다.
    그때까지 501 Not Implemented. 라우트를 미리 두는 이유는 /docs 에 자리가 보이고 프론트가 주소를 확정할 수 있어서.
    """
    raise HTTPException(status_code=501, detail="참석자 출발지 수정은 아직 구현 전입니다")
