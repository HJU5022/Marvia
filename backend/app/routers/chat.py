"""POST /api/chat 자연어 입력 창구 (docs/specs/chat-search.md).

창구만 한다: 로그인 확인 → services.chat.handle → 응답. 화물 조회·후속 질문은 /api/agent와 같은 run_agent를 부르므로
판정 규칙·조회 이력·트레이스가 그대로다. 기존 /api/agent는 평가셋·데모·정해진 칸 입력용으로 남긴다.
POST /api/chat/stream은 같은 일을 하면서 실제 처리 단계를 SSE로 흘려 준다 (docs/specs/chat-progress.md).
두 창구 모두 로그인 사용자를 services.chat.handle에 넘긴다. 화물 비서 기억(docs/specs/memory.md)의 지난 조회 한 줄과
기억 쓰기가 두 창구에서 똑같이 돈다. 기억 쓰기는 run_agent가 뒤 작업으로 돌려 응답·스트림을 늦추지 않는다.
"""
from __future__ import annotations

import contextvars
import json
import queue
import threading
from collections.abc import Iterator
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.app.auth import current_user_id
from backend.app.observability.langfuse import session_scope
from backend.app.observability.logging import log_failure
from backend.app.routers.agent import quota_guard, run_agent
from backend.app.schemas.agent import AgentRequest, AgentResponse
from backend.app.services import chat as svc
from backend.app.services import progress
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


BAD_MESSAGE = "문장을 1~500자로 입력해 주세요"
STREAM_FAILED = "답을 만드는 중 문제가 생겼습니다. 잠시 뒤 다시 시도해 주세요."
# 오래 걸리는 단계(LLM 판정 등)에서 중간 장비가 조용한 연결을 끊지 않게 보내는 빈 줄 간격 (chat-progress.md How)
PING_SEC = 15


def _context(body: ChatRequest) -> AgentRequest | None:
    """화면이 보낸 지금 화물을 판정 요청 모양으로. 틀렸으면 없는 것으로 본다. /api/chat과 스트림이 같이 쓴다."""
    if not body.context:
        return None
    try:
        return AgentRequest(bl_no=body.context.bl_no, bl_type=body.context.bl_type,
                            sale_due_date=body.context.sale_due_date, session_id=body.session_id,
                            mrn=body.context.mrn)
    except ValueError:
        return None


@router.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest, user_id: Annotated[str | None, Depends(current_user_id)] = None) -> ChatResponse:
    """문장 하나를 받아 화물 조회·후속 질문·입항 선박 검색·안내 중 하나로 답한다."""
    quota_guard(body.session_id, user_id)  # 하루 토큰 한도 (docs/specs/token-quota.md)
    context = _context(body)
    with session_scope(body.session_id, user_id):
        try:
            result = svc.handle(body.message, body.session_id, context, lambda req: run_agent(req, user_id), user_id)
        except svc.ChatError as e:
            raise HTTPException(status_code=400, detail=BAD_MESSAGE) from e
    return ChatResponse(**result.__dict__)


def _sse(event: str, data: dict) -> str:
    """SSE 한 덩어리. 이벤트 이름 한 줄 + JSON 한 줄 + 빈 줄 (HTML Living Standard, Server-sent events)."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat/stream")
def chat_stream(body: ChatRequest, user_id: Annotated[str | None, Depends(current_user_id)] = None) -> StreamingResponse:
    """/api/chat과 같은 처리를 하면서 실제 단계 소식을 SSE로 보낸다 (docs/specs/chat-progress.md).

    이벤트: progress {stage} 여러 번 → result (ChatResponse, /api/chat 응답과 같은 모양) 또는 error {status, detail}.
    판정 문장은 흘려보내지 않는다. 검증을 통과한 최종 응답만 result로 나간다.

    처리는 별도 스레드에서 돌리고 단계 소식은 큐로 받는다. handle·run_agent가 동기 함수라 그대로 쓰기 위해서다.
    스레드에 지금 요청의 문맥(요청 ID, LLM 사용량 기록)을 복사해 넘겨야 로그와 트레이스가 이 요청에 묶인다.
    로그인 확인은 응답을 열기 전에 끝난다(Depends). 그래서 401·403은 스트림이 아니라 보통 오류 응답으로 간다.
    """
    quota_guard(body.session_id, user_id)  # 스트림을 열기 전에 확인한다. 열린 뒤에는 429를 보낼 수 없다
    context = _context(body)
    events: queue.Queue[tuple[str, dict] | None] = queue.Queue()

    def work() -> None:
        try:
            with progress.listening(lambda stage: events.put(("progress", {"stage": stage}))):
                with session_scope(body.session_id, user_id):
                    result = svc.handle(body.message, body.session_id, context, lambda req: run_agent(req, user_id),
                                        user_id)
            events.put(("result", ChatResponse(**result.__dict__).model_dump(mode="json")))
        except svc.ChatError:
            events.put(("error", {"status": 400, "detail": BAD_MESSAGE}))
        except Exception as e:  # noqa: BLE001 - 응답이 이미 열려 있어 HTTP 500을 줄 수 없다. 오류 이벤트로 알린다
            log_failure("chat_stream", type(e).__name__)  # 예외 메시지는 남기지 않는다 (B/L·주소가 섞일 수 있다, SDD 3.5)
            events.put(("error", {"status": 500, "detail": STREAM_FAILED}))
        finally:
            events.put(None)

    threading.Thread(target=contextvars.copy_context().run, args=(work,), daemon=True).start()

    def stream() -> Iterator[str]:
        while True:
            try:
                item = events.get(timeout=PING_SEC)
            except queue.Empty:
                yield ": ping\n\n"  # 콜론으로 시작하는 줄은 SSE 주석이라 화면은 무시한다
                continue
            if item is None:
                return
            yield _sse(*item)

    # no-cache·X-Accel-Buffering: 중간 프록시가 모아 두었다 한꺼번에 보내지 않게 한다
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/vessels/detail")
def vessel_detail_view(call_sign: str | None = Query(default=None, max_length=20),
                       ship_name: str | None = Query(default=None, max_length=100),
                       user_id: Annotated[str | None, Depends(current_user_id)] = None) -> dict:
    """선박 표에서 선명을 눌렀을 때. 해수부 일정 + AIS 위치 + 부산까지 거리. 판정은 하지 않는다 (services/vessel_detail.py)."""
    if not (call_sign or ship_name):
        raise HTTPException(status_code=400, detail="호출부호나 선명이 필요합니다")
    return vessel_detail.detail(call_sign, ship_name)
