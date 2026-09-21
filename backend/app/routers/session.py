"""세션 API 3개. (SDD 1절·2절)

  GET    /api/session/{id}               공유 링크. POST /api/agent 와 같은 모양(AgentResponse)
  DELETE /api/session/{id}               주선자 본인만. 즉시 삭제
  PATCH  /api/session/{id}/participants  참석자 핀 claim 과 위치 수정 (SDD 7절 핀 소유권)

셋 다 로그인 필수 (결정 4: /health 빼고 전부). `Depends(current_user)` 한 줄이 그 역할이다.
DB는 직접 만지지 않고 services/store.py 함수만 부른다. 이 파일은 "요청 받기 → store 부르기 → 상태 코드 정하기"만.

POST /api/agent(파이프라인)는 routers/agent.py 에 따로 둔다 (SDD 1절).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response

from backend.app.schemas.request import ParticipantPatchRequest
from backend.app.schemas.session import SessionBrief
from backend.app.schemas.result import AgentResponse, ParticipantPatchResponse
from backend.app.services import session_store, store
from backend.app.services.auth import current_user

router = APIRouter(prefix="/api/session", tags=["session"])
# 목록은 /api/sessions 라 접두사가 다르다. main.py 가 둘 다 등록한다
list_router = APIRouter(prefix="/api", tags=["session"])


@list_router.get("/sessions", response_model=list[SessionBrief])
async def list_sessions(limit: int = 20, user_id: str = Depends(current_user)) -> list[SessionBrief]:
    """내가 만든 계획 목록 (SDD 2절).

    공유 링크 주소를 잃어버려도 자기 계획을 다시 찾을 수 있게 하는 입구다. 주선자 본인 것만 나온다.
    참석자로 초대만 받은 계획은 여기 없다. sessions.user_id 에 주선자 한 명만 담기기 때문이다.
    """
    rows = await store.list_sessions(user_id, limit=max(1, min(limit, 100)))
    return [
        SessionBrief(
            id=str(row["id"]),
            preset=row["preset"],
            status=row["status"],
            purpose=row["purpose"],
            destination=row["destination_name"],
            meet_at=row["meet_at"],
            participant_count=row["participant_count"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            locked=store.is_locked(row["meet_at"]),
        )
        for row in rows
    ]


@router.get("/{session_id}", response_model=AgentResponse)
async def read_session(session_id: str, user_id: str = Depends(current_user)) -> AgentResponse:
    """공유 링크로 들어온 사람에게 세션과 가장 최근 결과를 돌려준다.

    응답 모양이 POST /api/agent 와 같다 (SDD 2절). 화면 두 개(주선자·공유 링크)가 같은 렌더링
    코드를 쓰기 위해서다. 표 컬럼으로 흩어져 저장된 것을 services/session_store.py 가 다시 모은다.

    로그인한 사람이 이 세션의 참석자인지는 확인하지 않는다. 링크를 아는 사람은 누구나 볼 수 있다
    (SDD 2절). 없거나 만료면 404.
    """
    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="세션이 없거나 만료되었습니다")

    result_row = await store.get_latest_result(session_id)
    return session_store.to_agent_response(session_id, session, result_row)


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


@router.patch("/{session_id}/participants", response_model=ParticipantPatchResponse)
async def update_participant(
    session_id: str,
    body: ParticipantPatchRequest,
    user_id: str = Depends(current_user),
) -> ParticipantPatchResponse:
    """참석자가 공유 링크에서 자기 핀을 고르거나(claim) 위치를 고친다. (SDD 2절, 7절 핀 소유권)

    claim=True   "이 사람이 나다" 등록. 아직 주인이 없을 때만 된다. 이미 있으면 409
    claim=False  위치 수정. 로그인한 사람이면 누구 핀이든 고칠 수 있다 (09-18 결정)

    누구나 고칠 수 있게 한 이유: 현장에서 "저 사람 거기서 출발 안 해요"를 옆 사람이 바로 고쳐 주는 편이
    빠르다. 대신 누가 마지막에 고쳤는지 남겨 화면에서 보이게 한다 (last_edited_by).
    재계산은 하지 않는다. 좌표만 바꾸고 기존 결과를 그대로 돌려준다. 다시 계산할지는 주선자가 정한다
    (LLM 비용이 드는 일을 참석자 조작으로 자동으로 일으키지 않는다).
    """
    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="세션이 없거나 만료되었습니다")
    if store.is_locked(session["meet_at"]):
        raise HTTPException(status_code=409, detail="약속 날짜가 지나 잠긴 세션입니다")

    participants = list(session.get("participants") or [])
    target = next((p for p in participants if p.get("name") == body.name), None)
    if target is None:
        raise HTTPException(status_code=404, detail="그런 참석자가 없습니다")

    owner = target.get("owner_user_id")
    if body.claim:
        if owner and owner != user_id:
            raise HTTPException(status_code=409, detail="이미 다른 사람이 등록했습니다")
        target["owner_user_id"] = user_id
    else:
        target["lng"] = body.lng
        target["lat"] = body.lat
        target["confirmed"] = True
        # 본인이 고쳤는지 남이 고쳤는지 구분해 둔다 (테이블정의서 1절)
        target["origin_set_by"] = "self" if owner == user_id else "other"
        target["last_edited_by"] = user_id
        target["self_edited_at"] = datetime.now(timezone.utc).isoformat()

    await store.update_session(session_id, participants=participants)
    session["participants"] = participants
    result_row = await store.get_latest_result(session_id)
    return ParticipantPatchResponse(
        slots=session_store.slots_from_session(session),
        result=session_store.result_from_row(result_row),
        edits=session_store.edits_from_session(session),
    )
