"""POST /api/chat 자연어 입력 창구 (docs/specs/chat-search.md).

창구만 한다: 로그인 확인 → services.chat.chat.handle → 응답. 화물 조회·후속 질문은 /api/agent와 같은 run_agent를 부르므로
판정 규칙·조회 이력·트레이스가 그대로다. 기존 /api/agent는 평가셋·데모·정해진 칸 입력용으로 남긴다.
POST /api/chat/stream은 같은 일을 하면서 실제 처리 단계를 SSE로 흘려 준다 (docs/specs/chat-progress.md).
채팅 에이전트가 읽기 전용 MCP 도구를 부를 때는 후속 질문과 같은 실행 함수(routers/agent._follow_up_tool)를 쓴다:
읽기 전용 목록 확인, /mcp 경유, 실패 로그, AIS 목적지 원문 빼기가 그대로 걸린다.
대화로 지켜보기: 로그인 사용자에게는 지켜보기를 읽고 쓰는 함수(_watch_hooks)를 만들어 넘긴다. 서비스는 DB를 모르고, 여기서 연결을 연다.
지금 상태 카카오톡 보내기: 같은 방식으로 _kakao_hooks를 넘긴다. 보낼 글은 서비스가 쓰고, 여기서는 저장된 화물 줄을 읽고 services/watch/kakao.send_to_user를 부른다.
대화 목록: 두 창구 모두 답을 만든 뒤 _save_conversation으로 로그인 사용자의 대화를 뒤에서 저장한다. 실패는 로그만 남기고 답에는 영향이 없다.
두 창구 모두 로그인 사용자를 services.chat.chat.handle에 넘긴다. 화물 비서 기억(docs/specs/memory.md)의 지난 조회 한 줄과
기억 쓰기가 두 창구에서 똑같이 돈다. 기억 쓰기는 run_agent가 뒤 작업으로 돌려 응답·스트림을 늦추지 않는다.
"""
from __future__ import annotations

import contextvars
import json
import os
import queue
import re
import threading
import time
from collections.abc import Iterator
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.app.auth import current_user_id
from backend.app.observability.langfuse import request_span, session_scope
from backend.app.clients.kakao import KakaoError
from backend.app.observability.logging import log_failure
from backend.app.routers.agent import _follow_up_tool, quota_guard, run_agent
from backend.app.routers.kakao import _web
from backend.app.schemas.agent import SESSION_ID_MAX, AgentRequest, AgentResponse
from backend.app.services.watch import cargo as cargo_service
from backend.app.services.chat import conversations as conversations_service
from backend.app.services.chat import chat as svc
from backend.app.services.watch import kakao as kakao_service
from backend.app.services.account import memory as memory_service
from backend.app.services.account import operators as ops
from backend.app.services.chat import progress
from backend.app.services.watch import vessel_detail
from backend.app.services.watch import vessel_watch as vessel_watch_service
from backend.app.services.watch import watch as watch_service
from backend.app.services.chat import limits as chat_limits
from backend.app.services.chat import models as chat_models

router = APIRouter(prefix="/api", tags=["chat"])


SCREEN_TEXT_MAX, SCREEN_TIME_MAX = 80, 40  # 배 이름·항구 이름 / 시각 글자 상한. 실제 선박 이름·항구 이름은 이 안이다 (AIS 이름 20자, 해수부 항구명)


class ChatContext(BaseModel):
    """화면이 지금 보고 있는 화물. 후속 질문과 "다시 조회"에 쓴다. B/L은 서버 안에서만 쓰고 LLM에는 가는 일이 없다."""

    bl_no: str
    bl_type: Literal["MASTER", "HOUSE"]
    sale_due_date: str | None = None
    mrn: str | None = None  # 세관에 아직 없는 화물의 대체 조회용 (docs/specs/mrn-fallback.md)


class ChatDocument(BaseModel):
    """서류 사진에서 사용자가 확인한 출항일. 이 B/L의 조회 요청에만 departed_on으로 실어, 내 화물 현황 표 출항 칸에 적게 한다.
    B/L은 서버 안에서 요청의 B/L과 맞춰 보는 데만 쓰고 LLM에는 가는 일이 없다. 판정에도 쓰지 않는다."""

    bl_no: str
    departed_on: date


class ChatTurn(BaseModel):
    """화면에 보이는 대화 한 줄. 채팅 에이전트가 "이건", "그 배"를 알아듣는 데만 쓴다.
    화면이 보낸 값이라 믿지 않는다: 서버가 B/L을 가리고 주입 모양 줄을 뺀 뒤 자료로만 LLM에 넘긴다 (services/chat/chat._masked_history)."""

    role: Literal["user", "assistant"]
    text: str = Field(max_length=2000)  # 화면은 500자로 잘라 보낸다. 서버도 가린 뒤 다시 자른다


class ChatScreenVessel(BaseModel):
    """화면에 보이는 화물의 배. 위치·시각은 마지막으로 받은 값이다. B/L·컨테이너 번호 칸은 없다.
    길이 상한은 화면이 보낸 값을 믿지 않는 신뢰 경계다 (SDD 7절). 문자열은 서버가 다시 가리고 주입 모양이면 뺀다 (services/chat/chat._masked_screen)."""

    ship_name: str = Field(max_length=SCREEN_TEXT_MAX)
    flag: str | None = Field(default=None, max_length=SCREEN_TEXT_MAX)
    mmsi: int | None = Field(default=None, ge=0, le=999_999_999)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    position_time: str | None = Field(default=None, max_length=SCREEN_TIME_MAX)  # 마지막 위치 수신 시각 (ISO 글자)
    destination: str | None = Field(default=None, max_length=SCREEN_TEXT_MAX)  # 도착항 (화면의 UNI-PASS 양륙항 이름)


class ChatScreenArrival(BaseModel):
    """화면의 부산 입항 예정 선박 목록 한 줄. 목록에 MMSI가 없어 이름·국적·입항 예정·직전 항구만 받는다."""

    ship_name: str = Field(max_length=SCREEN_TEXT_MAX)
    flag: str | None = Field(default=None, max_length=SCREEN_TEXT_MAX)
    eta: str | None = Field(default=None, max_length=SCREEN_TIME_MAX)
    previous_port: str | None = Field(default=None, max_length=SCREEN_TEXT_MAX)
    # 배를 지켜볼 때 MMSI를 찾는 열쇠와, 사용자가 목록에서 고른 줄(지도에 보이는 배) 표시. 옛 화면은 보내지 않는다
    call_sign: str | None = Field(default=None, max_length=20)
    selected: bool = False


class ChatScreen(BaseModel):
    """지금 화면에 떠 있는 배들 (요청 계약에 추가된 칸). "옆에 떠있네 라이베리아에서 오는 거"를 알아듣는 데만 쓴다.
    선택 칸이라 옛 화면·평가 스크립트는 보내지 않아도 된다. 판정에는 쓰지 않는다. LLM에는 자료로만 간다."""

    vessel: ChatScreenVessel | None = None
    arrivals: list[ChatScreenArrival] = Field(default_factory=list, max_length=chat_limits.SCREEN_ARRIVALS_MAX)


class ChatRequest(BaseModel):
    message: str = Field(max_length=svc.MESSAGE_MAX)
    session_id: str = Field(max_length=SESSION_ID_MAX)  # /api/agent와 같은 상한 (schemas/agent.py)
    context: ChatContext | None = None
    # 서류 사진에서 확인한 출항일. 없어도 된다(전 화면·평가 스크립트)
    document: ChatDocument | None = None
    # 최근 대화. 서버는 마지막 몇 줄만 쓴다 (services/chat/chat.HISTORY_TURNS). 보내지 않아도 된다 (전 화면·평가 스크립트)
    history: list[ChatTurn] = Field(default_factory=list, max_length=50)
    # 화면에 지금 떠 있는 배. 없어도 된다(전 화면·평가 스크립트)
    on_screen: ChatScreen | None = None


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
    """답 말풍선 밑 미니 지도 자료. 에이전트가 이번 문장에서 선박 실시간 위치를 실제로 조회했을 때만 붙는다.
    좌표는 도구 결과에서만 읽는다 (services/chat/chat._map_payload). received_at은 AIS 수신 시각(없으면 조회 시각)의 ISO 8601 글자."""

    lat: float
    lng: float
    ship_name: str | None = None
    distance_nm: float | None = None
    received_at: str | None = None
    source: str  # "shipfinder"


class ChatCargo(BaseModel):
    """한 문장에 B/L이 2~3개일 때 표의 한 줄. agent·request는 이 줄을 눌렀을 때 아래 결과 칸을 바꾸는 데 쓴다:
    단일 화물 답의 agent·request와 같은 모양이다. bl_no는 사용자가 입력한 값 그대로다(요청에도 있는 값, LLM에는 가지 않는다).
    ship_name·eta·days_margin은 판정 흐름 응답에서 옮긴 값이다. days_margin은 판매 예정일이 있을 때만 값이 있다.
    note 칸은 판정을 못 낸 줄(insufficient)이 필요로 하는 것의 짧은 이유 ("같은 이름 배 2척", "조회 결과 없음"). 판정이 났으면 None."""

    bl_no: str
    status: str
    verdict: str | None = None
    ship_name: str | None = None
    eta: datetime | None = None
    days_margin: int | None = None
    sale_due_date: date | None = None
    note: str | None = None
    agent: AgentResponse
    request: AgentRequest


class WatchOffer(BaseModel):
    """"이 화물을 지켜볼까요?" 제안. 화면이 답 말풍선 밑에 [지켜보기] 버튼으로 보여 준다.
    bl_no는 화면이 PUT /api/cargo/watch에 쓰는 값(request.bl_no)과 같다. reason은 코드가 쓴 제안 문장이고 reply에도 들어 있다.
    logged_in이 false면 버튼 대신 로그인 안내를 보여 준다."""

    bl_no: str
    reason: str
    logged_in: bool


class WatchSet(BaseModel):
    """이번 문장으로 지켜보기를 켜거나 껐다. 화면이 그 화물의 토글을 새로 읽는다."""

    bl_no: str
    on: bool


class WatchVesselSet(BaseModel):
    """이번 문장으로 배 한 척을 감시 목록에 넣거나 뺐다. 화면이 그 배의 버튼을 새로 읽는다."""

    mmsi: int
    name: str
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
    watch_offer: WatchOffer | None = None  # 지켜보기를 먼저 제안한 답에만 채워진다
    watch_set: WatchSet | None = None  # 대화로 지켜보기를 켜거나 껐을 때만 채워진다
    watch_vessel_set: WatchVesselSet | None = None  # 대화로 배 한 척을 감시 목록에 넣거나 뺐을 때만 채워진다
    # 답 문장 속 근거 표시. 둘 다 더하기만 한 칸이라 옛 화면은 무시해도 된다.
    # evidence_items: 이번 문장에서 모은 근거 [{id, source, fetched_at, values:[{field,value}], url?, title?}]. 코드 문장·고정 문구에도 실린다(화면이 글 끝 칩으로 보인다)
    # citations: 검증을 통과한 [E#] 표시 [{id, start, end, evidence_ref}]. start/end는 reply 글 안 "[E1]"의 자리, evidence_ref는 evidence_items[].id
    evidence_items: list[dict] = []
    citations: list[dict] = []


BAD_MESSAGE = "문장을 1~500자로 입력해 주세요"
STREAM_FAILED = "답을 만드는 중 문제가 생겼어요. 잠시 뒤 다시 시도해 주세요."
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


def _agent_runner(body: ChatRequest, user_id: str | None):
    """services.chat.chat.handle이 부르는 조회 함수. 서류에서 확인한 출항일이 있고 요청의 B/L이 그 서류의 B/L일 때만
    요청에 departed_on을 실어 run_agent로 넘긴다. 문장에 다른 B/L이 섞여 있어도 그 화물에는 이 날짜가 가지 않는다.
    서비스(services/chat/chat.py)는 이 값을 모른다. 채팅 에이전트·판정 LLM 입력에도 가지 않고, 화물 표 쓰기(upsert_assessment)만 읽는다."""
    doc = body.document
    want = re.sub(r"\s+", "", doc.bl_no).upper() if doc else None

    def run(req: AgentRequest) -> AgentResponse:
        if doc and req.bl_no == want and not req.follow_up_question:
            req = req.model_copy(update={"departed_on": doc.departed_on})
        return run_agent(req, user_id)

    return run


def _on_screen(body: ChatRequest) -> dict:
    """화면이 보낸 지금 보이는 배들을 서비스에 넘길 인자로. 없으면 빈 묶음이라 호출이 예전과 같다. /api/chat과 스트림이 같이 쓴다."""
    return {"on_screen": body.on_screen.model_dump()} if body.on_screen else {}


def _history(body: ChatRequest) -> list[dict]:
    """화면이 보낸 최근 대화를 서비스가 받는 모양으로. /api/chat과 스트림이 같이 쓴다."""
    return [turn.model_dump() for turn in body.history]


# 켜기 직전에 화물 줄이 아직 없을 수 있다: 조회가 끝난 뒤 뒤 작업이 쓴다 (services/watch/watch.set_watch not_saved). 같은 문장에서 조회하고
# 바로 지켜보라고 한 경우를 위해 아주 잠깐만 기다린다. 길게 기다리지 않는다 (응답이 늦어진다)
SAVE_WAIT_TRIES, SAVE_WAIT_SEC = 3, 1.0


def _vessel_hooks(user_id: str) -> chat_models.VesselHooks:
    """로그인 사용자의 배 한 척 지켜보기 함수 셋. 오류는 종류만 서비스에 돌려주고 문장은 서비스가 정한다."""

    def resolve(call_sign: str, name: str | None) -> dict:
        try:
            return {"mmsi": vessel_watch_service.resolve_mmsi(call_sign, name)}
        except vessel_watch_service.VesselWatchError as e:
            return {"error": e.kind}

    def add(mmsi: int, name: str, flag: str | None, dest: str | None, eta: str | None, call_sign: str | None) -> dict:
        try:
            with ops.open_conn() as conn:
                return {"mmsi": vessel_watch_service.add_vessel(conn, user_id, mmsi, name, flag, dest, eta, call_sign)["mmsi"]}
        except vessel_watch_service.VesselWatchError as e:
            return {"error": e.kind}

    def remove(mmsi: int) -> dict:
        with ops.open_conn() as conn:
            return {"mmsi": vessel_watch_service.remove_vessel(conn, user_id, mmsi).get("mmsi", mmsi)}

    return chat_models.VesselHooks(resolve=resolve, add=add, remove=remove)


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
        """그 화물에 적어 둔 걱정 메모 중 가장 나중 것의 글. 사용자가 쓴 말을 기억 뽑기가 정리해 둔 값이다 (services/account/memory.py worry)."""
        key = cargo_service.cargo_key(bl_no)
        if key is None:  # 열쇠가 없으면 화물을 가리킬 수 없다 (cargo_key가 없는 항목과 짝지어지지 않게)
            return None
        with ops.open_conn() as conn:
            items = memory_service.load(conn, user_id)[0]
        texts = [(i.get("fields") or {}).get("text") for i in items if i.get("kind") == "worry" and i.get("cargo_key") == key]
        return next((t for t in reversed(texts) if t), None)

    return svc.WatchHooks(tool=tool, state=state, worry=worry, vessel=_vessel_hooks(user_id))


def _kakao_hooks(user_id: str | None) -> svc.KakaoHooks | None:
    """로그인 사용자의 카카오톡으로 지금 상태를 보내는 함수 둘. 로그인하지 않았거나 DB가 없으면 None.
    send는 재시도하지 않는다 (services/watch/kakao.send_to_user의 규칙). 실패는 종류만 서비스에 돌려주고 토큰·본문은 로그에 남기지 않는다.
    누르면 열리는 주소는 지켜보기 알림(services/watch/watch._notify)과 같은 화면 첫 페이지다."""
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

    def linked() -> bool:
        with ops.open_conn() as conn:
            return kakao_service.is_linked(conn, user_id)

    return svc.KakaoHooks(row=row, send=send, linked=linked)


def _save_conversation(body: ChatRequest, user_id: str | None, response: ChatResponse) -> None:
    """답을 만든 뒤 대화 목록에 저장하도록 뒤 일꾼에 맡긴다. 대화 번호는 session_id.
    로그인하지 않았거나 DB·PII 열쇠가 없으면 서비스가 조용히 건너뛴다. 저장은 부가 기능이라 어떤 실패도 채팅 답을 막지 않는다."""
    try:
        # customs_detail(UNI-PASS 처리 이력 원문, 중량·관세법인명 포함)은 화면 전용이라 DB에 저장하지 않는다 (SDD 3.5, docs/specs/customs-detail.md).
        # 대화에 든 판정 덩어리는 두 곳이다: 단일 화물 답의 agent와 여러 B/L 표 줄(cargos)마다의 agent. 둘 다 뺀다.
        # 다시 연 대화에서는 이 표가 비고, 화물을 다시 조회하면 채워진다
        saved = response.model_dump(mode="json", exclude={"agent": {"customs_detail"},
                                                          "cargos": {"__all__": {"agent": {"customs_detail"}}}})
        conversations_service.save_later(user_id, body.session_id, body.message, saved)
    except Exception as e:  # noqa: BLE001
        log_failure("conversation_save", type(e).__name__)


@router.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest, user_id: Annotated[str | None, Depends(current_user_id)] = None) -> ChatResponse:
    """문장 하나를 받아 화물 조회·후속 질문·입항 선박 검색·안내 중 하나로 답한다."""
    with request_span("/api/chat"):  # 요청 전체를 루트 span 하나로. 안의 관측이 전부 자식이 된다
        quota_guard(body.session_id, user_id)  # 하루 토큰 한도 (docs/specs/token-quota.md)
        context = _context(body)
        with session_scope(body.session_id, user_id):
            try:
                result = svc.handle(body.message, body.session_id, context, _agent_runner(body, user_id), user_id,
                                    history=_history(body), run_tool=_follow_up_tool,
                                    watch=_watch_hooks(user_id), kakao=_kakao_hooks(user_id),
                                    **_on_screen(body))
            except svc.ChatError as e:
                raise HTTPException(status_code=400, detail=BAD_MESSAGE) from e
            response = ChatResponse(**result.__dict__)
            # session_scope 안에서 맡긴다. 뒤에서 도는 제목 LLM이 이 문맥(사용량 주인·Langfuse user_id)을 복사해 가야
            # 하루 토큰 한도에 잡힌다. 밖에서 부르면 주인이 이미 비어 토큰이 버려진다
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
    quota_guard(body.session_id, user_id)  # 스트림을 열기 전에 확인한다. 열린 뒤에는 429를 보낼 수 없다
    context = _context(body)
    events: queue.Queue[tuple[str, dict] | None] = queue.Queue()

    def work() -> None:
        # 루트 span은 이 처리 스레드 안에서 열고 닫는다. 스트림 제너레이터는 클라이언트가 끊으면 중간에 닫혀 span이 안 끝날 수 있고,
        # 처리는 끊겨도 끝까지 도므로 처리가 끝나는 이 자리가 span이 끝나는 자리다. 오류 이벤트로 알린 상태는 span status에 적는다
        try:
            with request_span("/api/chat/stream") as root:
                try:
                    with progress.listening(lambda stage: events.put(("progress", {"stage": stage}))):
                        with session_scope(body.session_id, user_id):
                            result = svc.handle(body.message, body.session_id, context, _agent_runner(body, user_id),
                                                user_id, history=_history(body), run_tool=_follow_up_tool,
                                                watch=_watch_hooks(user_id), kakao=_kakao_hooks(user_id),
                                                **_on_screen(body))
                            response = ChatResponse(**result.__dict__)
                            # 맡기기만 한다. 저장·제목은 뒤에서 돈다. session_scope 안이라 제목 LLM 토큰도 이 사용자 몫으로 쌓인다
                            _save_conversation(body, user_id, response)
                    events.put(("result", response.model_dump(mode="json")))
                except svc.ChatError:
                    root.status = 400
                    events.put(("error", {"status": 400, "detail": BAD_MESSAGE}))
                except Exception as e:  # noqa: BLE001 - 응답이 이미 열려 있어 HTTP 500을 줄 수 없다. 오류 이벤트로 알린다
                    log_failure("chat_stream", type(e).__name__)  # 예외 메시지는 남기지 않는다 (B/L·주소가 섞일 수 있다, SDD 3.5)
                    root.status, root.error = 500, type(e).__name__
                    events.put(("error", {"status": 500, "detail": STREAM_FAILED}))
        finally:
            events.put(None)  # 스트림 끝 표시는 루트 span이 닫힌 뒤에 보낸다. 응답이 끝난 시점에 span도 이미 끝나 있다

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
    """선박 표에서 선명을 눌렀을 때. 해수부 일정 + AIS 위치 + 부산까지 거리. 판정은 하지 않는다 (services/watch/vessel_detail.py)."""
    if not (call_sign or ship_name):
        raise HTTPException(status_code=400, detail="호출부호나 선명이 필요합니다")
    return vessel_detail.detail(call_sign, ship_name)
