"""POST /api/agent. 파이프라인 입구. (SDD 1절·2절)

이 파일은 "요청 받기 → 로그인 확인 → pipeline.run 부르기 → 상태 코드 정하기"만 한다.
단계 순서와 갈림길은 services/pipeline.py 에 있다 (SDD 5절).

로그인 필수. 토큰이 없거나 틀리면 401 이고, 그 전에 LLM을 부르지 않는다 (비용 방어, SDD 2절).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.app.schemas.request import AgentRequest
from backend.app.schemas.result import AgentResponse
from backend.app.services import pipeline
from backend.app.services.auth import current_user

router = APIRouter(prefix="/api", tags=["agent"])


@router.post("/agent", response_model=AgentResponse)
async def agent(req: AgentRequest, user_id: str = Depends(current_user)) -> AgentResponse:
    """문장 또는 캡처를 받아 집결 계획을 돌려준다.

    실패도 200 으로 돌려준다. stage 가 failed·need_info 로 오는 것이지 HTTP 오류가 아니다.
    화면이 stage 하나로 갈리기 때문이다 (frontend/FRONTEND_GUIDE.md 표).
    HTTP 오류는 권한 문제일 때만 낸다.
    """
    try:
        return await pipeline.run(req, user_id)
    except pipeline.NotYourPin as e:
        # 남의 핀을 고치려 한 경우 (SDD 7절 핀 소유권)
        raise HTTPException(status_code=403, detail=f"본인 핀만 수정할 수 있습니다: {e}") from e
