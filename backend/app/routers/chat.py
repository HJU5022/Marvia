"""POST /api/chat 자연어 입력 창구 (docs/specs/chat-search.md).

창구만 한다: 로그인 확인 → services.chat.handle → 응답. 화물 조회·후속 질문은 /api/agent와 같은 run_agent를 부르므로
판정 규칙·조회 이력·트레이스가 그대로다. 기존 /api/agent는 평가셋·데모·정해진 칸 입력용으로 남긴다.
"""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.app.auth import current_user_id
from backend.app.observability.langfuse import session_scope
from backend.app.routers.agent import run_agent
from backend.app.schemas.agent import AgentRequest, AgentResponse
from backend.app.services import chat as svc
from backend.app.services import vessel_detail

router = APIRouter(prefix="/api", tags=["chat"])


class ChatContext(BaseModel):
    """화면이 지금 보고 있는 화물. 후속 질문과 "다시 조회"에 쓴다. B/L은 서버 안에서만 쓰고 LLM에는 가는 일이 없다."""

    bl_no: str
    bl_type: Literal["MASTER", "HOUSE"]
    sale_due_date: str | None = None
    mrn: str | None = None  # 세관에 아직 없는 화물의 대체 조회용 (docs/specs/mrn-fallback.md)


class ChatRequest(BaseModel):
    message: str = Field(max_length=svc.MESSAGE_MAX)
    session_id: str
    context: ChatContext | None = None


class VesselItem(BaseModel):
    ship_name: str
    call_sign: str | None
    nationality: str | None
    ship_kind: str | None
    previous_port: str | None
    next_port: str | None
    purpose: str | None
    expected_arrival: str | None
    planned_departure: str | None = None  # 부산 출항 예정
    is_cargo: bool = True  # 수입 화물선(skills/port-busan/cargo-vessels.md). 화면 기본값은 이 배들만
    facility: str | None


class ChatResponse(BaseModel):
    kind: Literal["cargo", "vessels", "message"]
    reply: str
    agent: AgentResponse | None = None
    request: AgentRequest | None = None
    vessels: list[VesselItem] = []
    place: str | None = None
    ports: list[str] = []
    days: int | None = None


@router.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest, user_id: Annotated[str | None, Depends(current_user_id)] = None) -> ChatResponse:
    """문장 하나를 받아 화물 조회·후속 질문·입항 선박 검색·안내 중 하나로 답한다."""
    context = None
    if body.context:
        try:
            context = AgentRequest(bl_no=body.context.bl_no, bl_type=body.context.bl_type,
                                   sale_due_date=body.context.sale_due_date, session_id=body.session_id,
                                   mrn=body.context.mrn)
        except ValueError:
            context = None  # 화면이 보낸 화물 정보가 틀렸으면 없는 것으로 본다
    with session_scope(body.session_id, user_id):
        try:
            result = svc.handle(body.message, body.session_id, context, lambda req: run_agent(req, user_id))
        except svc.ChatError as e:
            raise HTTPException(status_code=400, detail="문장을 1~500자로 입력해 주세요") from e
    return ChatResponse(**result.__dict__)


@router.get("/vessels/detail")
def vessel_detail_view(call_sign: str | None = Query(default=None, max_length=20),
                       ship_name: str | None = Query(default=None, max_length=100),
                       user_id: Annotated[str | None, Depends(current_user_id)] = None) -> dict:
    """선박 표에서 선명을 눌렀을 때. 해수부 일정 + AIS 위치 + 부산까지 거리. 판정은 하지 않는다 (services/vessel_detail.py)."""
    if not (call_sign or ship_name):
        raise HTTPException(status_code=400, detail="호출부호나 선명이 필요합니다")
    return vessel_detail.detail(call_sign, ship_name)
