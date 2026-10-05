"""POST /api/chat 자연어 입력 창구 (docs/specs/chat-search.md).

창구만 한다: 로그인 확인 → services.chat.handle → 응답. 화물 조회·후속 질문은 /api/agent와 같은 run_agent를 부르므로
판정 규칙·조회 이력·트레이스가 그대로다. 기존 /api/agent는 평가셋·데모·정해진 칸 입력용으로 남긴다.
POST /api/chat/stream은 같은 일을 하면서 실제 처리 단계를 SSE로 흘려 준다 (docs/specs/chat-progress.md).
채팅 에이전트(10-05)가 읽기 전용 MCP 도구를 부를 때는 후속 질문과 같은 실행 함수(routers/agent._follow_up_tool)를 쓴다:
읽기 전용 목록 확인, /mcp 경유, 실패 로그, AIS 목적지 원문 빼기가 그대로 걸린다.
대화로 지켜보기(10-06): 로그인 사용자에게는 지켜보기를 읽고 쓰는 함수(_watch_hooks)를 만들어 넘긴다. 서비스는 DB를 모르고, 여기서 연결을 연다.
지금 상태 카카오톡 보내기(10-06): 같은 방식으로 _kakao_hooks를 넘긴다. 보낼 글은 서비스가 쓰고, 여기서는 저장된 화물 줄을 읽고 services/kakao.send_to_user를 부른다.
대화 목록(10-06): 두 창구 모두 답을 만든 뒤 _save_conversation으로 로그인 사용자의 대화를 뒤에서 저장한다. 실패는 로그만 남기고 답에는 영향이 없다.
두 창구 모두 로그인 사용자를 services.chat.handle에 넘긴다. 화물 비서 기억(docs/specs/memory.md)의 지난 조회 한 줄과
기억 쓰기가 두 창구에서 똑같이 돈다. 기억 쓰기는 run_agent가 뒤 작업으로 돌려 응답·스트림을 늦추지 않는다.
"""
from __future__ import annotations

import contextvars
import json
import os
import queue
import threading
import time
from collections.abc import Iterator
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.app.auth import current_user_id
from backend.app.observability.langfuse import session_scope
from backend.app.clients.kakao import KakaoError
from backend.app.observability.logging import log_failure
from backend.app.routers.agent import _follow_up_tool, run_agent
from backend.app.routers.kakao import _web
from backend.app.schemas.agent import AgentRequest, AgentResponse
from backend.app.services import cargo as cargo_service
from backend.app.services import conversations as conversations_service
from backend.app.services import chat as svc
from backend.app.services import kakao as kakao_service
from backend.app.services import memory as memory_service
from backend.app.services import operators as ops
from backend.app.services import progress
from backend.app.services import vessel_detail
from backend.app.services import watch as watch_service

router = APIRouter(prefix="/api", tags=["chat"])


class ChatContext(BaseModel):
    """화면이 지금 보고 있는 화물. 후속 질문과 "다시 조회"에 쓴다. B/L은 서버 안에서만 쓰고 LLM에는 가는 일이 없다."""

    bl_no: str
    bl_type: Literal["MASTER", "HOUSE"]
    sale_due_date: str | None = None
    mrn: str | None = None  # 세관에 아직 없는 화물의 대체 조회용 (docs/specs/mrn-fallback.md)


class ChatTurn(BaseModel):
    """화면에 보이는 대화 한 줄. 채팅 에이전트가 "이건", "그 배"를 알아듣는 데만 쓴다 (10-05).
    화면이 보낸 값이라 믿지 않는다: 서버가 B/L을 가리고 주입 모양 줄을 뺀 뒤 자료로만 LLM에 넘긴다 (services/chat._masked_history)."""

    role: Literal["user", "assistant"]
    text: str = Field(max_length=2000)  # 화면은 500자로 잘라 보낸다. 서버도 가린 뒤 다시 자른다


class ChatRequest(BaseModel):
    message: str = Field(max_length=svc.MESSAGE_MAX)
    session_id: str
    context: ChatContext | None = None
    # 최근 대화. 서버는 마지막 몇 줄만 쓴다 (services/chat.HISTORY_TURNS). 보내지 않아도 된다 (전 화면·평가 스크립트)
    history: list[ChatTurn] = Field(default_factory=list, max_length=50)


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


class ChatMap(BaseModel):
    """답 말풍선 밑 미니 지도 자료 (10-05). 에이전트가 이번 문장에서 선박 실시간 위치를 실제로 조회했을 때만 붙는다.
    좌표는 도구 결과에서만 읽는다 (services/chat._map_payload). received_at은 AIS 수신 시각(없으면 조회 시각)의 ISO 8601 글자."""

    lat: float
    lng: float
    ship_name: str | None = None
    distance_nm: float | None = None
    received_at: str | None = None
    source: str  # "shipfinder"


class ChatCargo(BaseModel):
    """한 문장에 B/L이 2~3개일 때 표의 한 줄 (10-05 정운 결정). agent·request는 이 줄을 눌렀을 때 오른쪽 칸을 바꾸는 데 쓴다:
    단일 화물 답의 agent·request와 같은 모양이다. bl_no는 사용자가 입력한 값 그대로다(요청에도 있는 값, LLM에는 가지 않는다).
    ship_name·eta·days_margin은 판정 흐름 응답에서 옮긴 값이다. days_margin은 판매 예정일이 있을 때만 값이 있다."""

    bl_no: str
    status: str
    verdict: str | None = None
    ship_name: str | None = None
    eta: datetime | None = None
    days_margin: int | None = None
    sale_due_date: date | None = None
    agent: AgentResponse
    request: AgentRequest


class WatchOffer(BaseModel):
    """"이 화물을 지켜볼까요?" 제안 (10-06). 화면이 답 말풍선 밑에 [지켜보기] 버튼으로 보여 준다.
    bl_no는 화면이 PUT /api/cargo/watch에 쓰는 값(request.bl_no)과 같다. reason은 코드가 쓴 제안 문장이고 reply에도 들어 있다.
    logged_in이 false면 버튼 대신 로그인 안내를 보여 준다."""

    bl_no: str
    reason: str
    logged_in: bool


class WatchSet(BaseModel):
    """이번 문장으로 지켜보기를 켜거나 껐다 (10-06). 화면이 그 화물의 토글을 새로 읽는다."""

    bl_no: str
    on: bool


class ChatResponse(BaseModel):
    kind: Literal["cargo", "vessels", "message"]
    reply: str
    agent: AgentResponse | None = None
    request: AgentRequest | None = None
    vessels: list[VesselItem] = []
    place: str | None = None
    ports: list[str] = []
    days: int | None = None
    map: ChatMap | None = None
    cargos: list[ChatCargo] = []  # B/L이 2~3개인 문장에서만 채워진다. 한 개짜리 답은 빈 목록이라 옛 화면도 그대로 쓴다
    watch_offer: WatchOffer | None = None  # 지켜보기를 먼저 제안한 답에만 채워진다 (10-06)
    watch_set: WatchSet | None = None  # 대화로 지켜보기를 켜거나 껐을 때만 채워진다 (10-06)


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


def _history(body: ChatRequest) -> list[dict]:
    """화면이 보낸 최근 대화를 서비스가 받는 모양으로. /api/chat과 스트림이 같이 쓴다."""
    return [turn.model_dump() for turn in body.history]


# 켜기 직전에 화물 줄이 아직 없을 수 있다: 조회가 끝난 뒤 뒤 작업이 쓴다 (services/watch.set_watch not_saved). 같은 문장에서 조회하고
# 바로 지켜보라고 한 경우를 위해 아주 잠깐만 기다린다. 길게 기다리지 않는다 (응답이 늦어진다)
SAVE_WAIT_TRIES, SAVE_WAIT_SEC = 3, 1.0


def _watch_hooks(user_id: str | None) -> svc.WatchHooks | None:
    """로그인 사용자의 지켜보기를 읽고 쓰는 함수 셋. 로그인하지 않았거나 DB가 없으면 None (서비스는 "바꾸지 않고 안내만"으로 안다).
    함수마다 연결을 따로 연다: 켜기·상태·걱정 읽기가 한 요청에서 각각 한두 번뿐이라 단순함이 낫다 (routers/watch.py와 같은 방식)."""
    if not user_id or not os.environ.get("DATABASE_URL"):
        return None

    def tool(bl_no: str, on: bool) -> dict:
        for attempt in range(SAVE_WAIT_TRIES):
            try:
                with ops.open_conn() as conn:
                    return {"on": watch_service.set_watch(conn, user_id, bl_no, on)}
            except watch_service.WatchError as e:
                if e.kind == "not_saved" and attempt + 1 < SAVE_WAIT_TRIES:
                    time.sleep(SAVE_WAIT_SEC)
                    continue
                log_failure("chat_watch", e.kind)
                return {"error": e.kind}
        return {"error": "not_saved"}

    def state(bl_no: str) -> dict:
        with ops.open_conn() as conn:
            return watch_service.watch_state(conn, user_id, bl_no)

    def worry(bl_no: str) -> str | None:
        """그 화물에 적어 둔 걱정 메모 중 가장 나중 것의 글. 사용자가 쓴 말을 기억 뽑기가 정리해 둔 값이다 (services/memory.py worry)."""
        key = cargo_service.cargo_key(bl_no)
        if key is None:  # 열쇠가 없으면 화물을 가리킬 수 없다 (cargo_key가 없는 항목과 짝지어지지 않게)
            return None
        with ops.open_conn() as conn:
            items = memory_service.load(conn, user_id)[0]
        texts = [(i.get("fields") or {}).get("text") for i in items if i.get("kind") == "worry" and i.get("cargo_key") == key]
        return next((t for t in reversed(texts) if t), None)

    return svc.WatchHooks(tool=tool, state=state, worry=worry)


def _kakao_hooks(user_id: str | None) -> svc.KakaoHooks | None:
    """로그인 사용자의 카카오톡으로 지금 상태를 보내는 함수 둘 (10-06 결정). 로그인하지 않았거나 DB가 없으면 None.
    send는 재시도하지 않는다 (services/kakao.send_to_user의 규칙). 실패는 종류만 서비스에 돌려주고 토큰·본문은 로그에 남기지 않는다.
    누르면 열리는 주소는 지켜보기 알림(services/watch._notify)과 같은 화면 첫 페이지다."""
    if not user_id or not os.environ.get("DATABASE_URL"):
        return None

    def row(bl_no: str) -> dict | None:
        key = cargo_service.cargo_key(bl_no)
        if key is None:
            return None
        with ops.open_conn() as conn:
            return cargo_service.get_row(conn, user_id, key)

    def send(text: str) -> dict:
        try:
            with ops.open_conn() as conn:
                kakao_service.send_to_user(conn, user_id, text, f"{_web()}/")
        except (kakao_service.KakaoLinkError, KakaoError) as e:
            log_failure("chat_kakao", e.kind)
            return {"error": e.kind}
        return {"sent": True}

    return svc.KakaoHooks(row=row, send=send)


def _save_conversation(body: ChatRequest, user_id: str | None, response: ChatResponse) -> None:
    """답을 만든 뒤 대화 목록에 저장하도록 뒤 일꾼에 맡긴다 (10-06). 대화 번호는 session_id.
    로그인하지 않았거나 DB·PII 열쇠가 없으면 서비스가 조용히 건너뛴다. 저장은 부가 기능이라 어떤 실패도 채팅 답을 막지 않는다."""
    try:
        conversations_service.save_later(user_id, body.session_id, body.message, response.model_dump(mode="json"))
    except Exception as e:  # noqa: BLE001
        log_failure("conversation_save", type(e).__name__)


@router.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest, user_id: Annotated[str | None, Depends(current_user_id)] = None) -> ChatResponse:
    """문장 하나를 받아 화물 조회·후속 질문·입항 선박 검색·안내 중 하나로 답한다."""
    context = _context(body)
    with session_scope(body.session_id, user_id):
        try:
            result = svc.handle(body.message, body.session_id, context, lambda req: run_agent(req, user_id), user_id,
                                history=_history(body), run_tool=_follow_up_tool,
                                watch=_watch_hooks(user_id), kakao=_kakao_hooks(user_id))
        except svc.ChatError as e:
            raise HTTPException(status_code=400, detail=BAD_MESSAGE) from e
    response = ChatResponse(**result.__dict__)
    _save_conversation(body, user_id, response)
    return response


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
    context = _context(body)
    events: queue.Queue[tuple[str, dict] | None] = queue.Queue()

    def work() -> None:
        try:
            with progress.listening(lambda stage: events.put(("progress", {"stage": stage}))):
                with session_scope(body.session_id, user_id):
                    result = svc.handle(body.message, body.session_id, context, lambda req: run_agent(req, user_id),
                                        user_id, history=_history(body), run_tool=_follow_up_tool,
                                        watch=_watch_hooks(user_id), kakao=_kakao_hooks(user_id))
            response = ChatResponse(**result.__dict__)
            _save_conversation(body, user_id, response)  # 맡기기만 한다. 저장·제목은 뒤에서 돈다
            events.put(("result", response.model_dump(mode="json")))
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
