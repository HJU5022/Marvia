"""화면 서버: 에이전트 한 차례를 AG-UI 이벤트(SSE)로 흘려보낸다 (설계 3절·10절·12절, 계획 4b Task 5).

ag-ui-langgraph 어댑터를 쓰지 않고 ag-ui-protocol의 이벤트 타입·인코더로 엔드포인트를 직접 쓴다.
[왜] 어댑터는 화면이 보낸 메시지·state를 그래프 입력에 합치고, 공책 전체(가림 표 포함)를
     STATE_SNAPSHOT으로 보내고, 비동기 저장기를 요구한다(계획 4b 사전 부검 1번). 여기서는 받는 값을
     마지막 사용자 글과 재개 값으로 줄이고, 보내는 값은 view.py의 허용 목록만 쓴다.
흐름: POST /agui → 로그인 확인(auth) → thread 잠금 → 작업 스레드 하나에서 graph.stream → 큐 → SSE
     RUN_STARTED → STATE_SNAPSHOT(할 일·읽은 번호·화물·근거가 바뀔 때마다) → (답이면 TEXT_MESSAGE_*)
     → RUN_FINISHED(outcome success 또는 interrupt + 카드) | RUN_ERROR
잠금(running)은 이 프로세스 안에서만 지킨다. 배포는 인스턴스 하나로 돌린다(여럿이면 thread 키에
pg_try_advisory_lock을 거는 것으로 올린다).
하지 않는 일: 화면 그리기(web/), 가림 판단(identify), 모델 호출, 표 만들기(python -m marvia.migrate).
"""

from __future__ import annotations

import logging
import os
import queue
import re
import threading
import traceback
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

import anyio
import psycopg
import uvicorn
from ag_ui.core import (
    BaseEvent,
    RunAgentInput,
    RunErrorEvent,
    RunFinishedEvent,
    RunFinishedInterruptOutcome,
    RunFinishedSuccessOutcome,
    RunStartedEvent,
    StateSnapshotEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
)
from ag_ui.core import Interrupt as CardInterrupt
from ag_ui.encoder import EventEncoder
from langgraph.types import Command
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.body_limit import RequestBodyLimitMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from marvia.auth import AuthError, Verify, user_from_header, verifier
from marvia.config import Settings
from marvia.db import read_pool
from marvia.graph.live import agent_deps, live_memory
from marvia.graph.main import build_main_graph
from marvia.graph.resume import approval_reply, remask_reply
from marvia.graph.state import merge_cargos, merge_evidence
from marvia.graph.tools import SERVER_SURFACE
from marvia.tools.rules import load_rules
from marvia.view import interrupt_card, screen_view

LOG = logging.getLogger(__name__)

# [왜] 화면이 정하는 thread id는 이름 공간 안의 이름일 뿐이다.
#      서버가 "사용자/이름"으로 묶어 남의 대화에 닿지 못한다
THREAD_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
# [왜] 프록시·압축이 이벤트를 모았다가 한꺼번에 보내면 "진행 중인 할 일"이 답과 함께 뜬다
SSE_HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}
LIVE_KEYS = ("todos", "plan", "cargos", "evidence", "mask_map")  # 화면 보기를 바꾸는 공책 칸
CHOICE_KEYS = ("selected", "custom", "timeout")  # 선택지 재개 값에서 받는 칸 (설계 6.3)


class Refused(Exception):
    """그래프를 부르기 전에 요청을 거절한다. status에 상태 코드를 둔다."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def _merge(live: dict, update: dict, inside: bool) -> bool:
    """흘러온 갱신 하나를 화면용 공책 사본에 반영한다. 화면 보기가 바뀌면 True."""
    changed = False
    for key in LIVE_KEYS:
        if key not in update:
            continue
        value = update[key]
        # [왜] 루프(서브그래프) 안의 도구 갱신은 새로 찾은 것만 담는다. 공책의 합치는 함수와 같게 합친다.
        #      바깥(메인 그래프) 노드의 갱신은 칸 전체 값이다
        if inside and key == "evidence":
            limit = load_rules("agent")["answer"]["max_evidence"]
            value = merge_evidence(live.get("evidence", []), value, limit)
        elif inside and key == "cargos":
            value = merge_cargos(live.get("cargos", []), value)
        live[key] = value
        changed = True
    return changed


def _parts(update: Any) -> list[dict]:
    """노드 갱신 하나를 dict 목록으로. 도구 노드는 갱신을 여러 개(목록) 낼 수 있다."""
    items = update if isinstance(update, list) else [update]
    return [item for item in items if isinstance(item, dict)]


def turn_events(
    graph, payload: Any, config: dict, thread: str, run: str, stop: threading.Event
) -> Iterator[BaseEvent]:
    """한 차례를 돌리며 AG-UI 이벤트를 낸다. 작업 스레드 하나에서 끝까지 돈다(동기 그래프와 저장기)."""
    yield RunStartedEvent(thread_id=thread, run_id=run)
    answer = ""
    tail: list[
        BaseEvent
    ] = []  # [왜] 끝 이벤트는 만들기가 다 된 뒤에 한꺼번에 낸다. 중간에 죽어도 짝이 깨지지 않는다
    try:
        live = dict(graph.get_state(config).values)  # [왜] 재개 차례도 지난 화물·읽은 번호를 이어 보인다
        for namespace, chunk in graph.stream(payload, config, stream_mode="updates", subgraphs=True):
            if stop.is_set():
                return  # [왜] 브라우저가 끊었다. 다음 단계로 가지 않고 멈춰 LLM 비용을 더 쓰지 않는다
            for node, update in chunk.items():
                for part in _parts(update):
                    if not namespace and "answer" in part:
                        answer = part["answer"]  # [왜] 답은 저장하지 않는 칸이라 갱신에서만 읽는다 (R-035)
                    if node != "__interrupt__" and _merge(live, part, inside=bool(namespace)):
                        yield StateSnapshotEvent(snapshot=screen_view(live))
        state = graph.get_state(config)
        if state.interrupts:
            # [왜] 질문과 승인은 한 번에 하나씩 멈춘다 (batched, ask_user 혼자 부르기)
            pending = state.interrupts[0]
            card = interrupt_card(pending.value, state.values.get("mask_map", {}))
            stopped = CardInterrupt(id=pending.id, reason=card["kind"], metadata=card)
            outcome = RunFinishedInterruptOutcome(interrupts=[stopped])
            tail = [RunFinishedEvent(thread_id=thread, run_id=run, outcome=outcome)]
        else:
            message = f"{run}-answer"
            tail = [
                TextMessageStartEvent(message_id=message, role="assistant"),
                TextMessageContentEvent(message_id=message, delta=answer),
                TextMessageEndEvent(message_id=message),
                RunFinishedEvent(thread_id=thread, run_id=run, outcome=RunFinishedSuccessOutcome()),
            ]
    except Exception as error:
        # [왜] 어떤 실패든 화면에 끝을 알린다. 오류 글은 화면에도 기록에도 남기지 않는다(번호가 섞일 수 있다).
        #      기록에는 예외 종류와 난 자리(파일:줄:함수)만 남긴다
        frames = traceback.extract_tb(error.__traceback__)
        where = (
            f"{os.path.basename(frames[-1].filename)}:{frames[-1].lineno}:{frames[-1].name}"
            if frames
            else "?"
        )
        LOG.error("차례 실패 %s at %s", type(error).__name__, where)
        yield RunErrorEvent(
            message="이번 차례를 끝내지 못했어요. 다시 물어봐 주세요.", code=type(error).__name__
        )
        return
    yield from tail


def turn_input(graph, body: RunAgentInput, config: dict) -> Any:
    """그래프에 넣을 값: 새 질문이면 {"text": 마지막 사용자 글}, 재개면 Command(resume=정리한 값).

    [주의] 화면이 보낸 state·forwardedProps·지난 메시지는 읽지 않는다.
           호출 수 상한이나 가림 표를 화면이 바꿀 수 없다.
    """
    max_text = load_rules("server")["request"]["max_text"]
    if body.resume:
        state = graph.get_state(config)
        if not state.interrupts or body.resume[0].interrupt_id != state.interrupts[0].id:
            raise Refused(409, "답할 질문이 없거나 이미 지난 카드예요")
        value, raw = state.interrupts[0].value, body.resume[0].payload
        # [왜] 취소한 카드는 payload를 읽지 않는다. 선택지는 권장안으로, 승인은 모두 거절로 간다
        raw = raw if isinstance(raw, dict) and body.resume[0].status == "resolved" else {}
        if "action_requests" in value:
            names = [request["name"] for request in value["action_requests"]]
            # [왜] 모양을 본 뒤(approval_reply) 고친 인자·거절 글의 실제 번호를 이 대화의 토큰으로 다시 가린다
            reply = approval_reply(raw, len(names), names)
            # shortcut: 부모 상태의 mask_map은 이번 차례 시작 때 값이라 같은 차례에 ask_user로 들어온
            #   번호가 아직 없다(그 번호로 고치면 거절된다). 올릴 때: get_state(config, subgraphs=True)로
            #   끼어든 서브그래프의 표를 읽는다
            return Command(resume=remask_reply(reply, state.values.get("mask_map", {})))
        # [왜] 빈 dict로 재개하면 langgraph가 다시 멈춘다. 취소는 시간 초과와 같은 {"timeout": True}로 보낸다
        choice = {key: raw[key] for key in CHOICE_KEYS if key in raw} or {"timeout": True}
        # [왜] 번호는 요청이 아니라 멈춘 카드의 선택지 수로 확인한다. -1과 True도 막는다
        picked = choice.get("selected")
        if "selected" in choice and not (
            isinstance(picked, int) and not isinstance(picked, bool) and 0 <= picked < len(value["options"])
        ):
            raise Refused(422, "고른 선택지가 카드에 없어요")
        if len(str(choice.get("custom", ""))) > max_text:
            raise Refused(422, "글이 너무 길어요")
        return Command(resume=choice)
    # [왜] 마지막 메시지 하나만 본다. user가 아니거나 글이 아니면 앞 메시지로 물러서지 않고 거절한다
    last = body.messages[-1] if body.messages else None
    if last is not None and not (last.role == "user" and isinstance(last.content, str)):
        raise Refused(422, "마지막 메시지는 사용자 글이어야 해요")
    text = last.content.strip() if last is not None and isinstance(last.content, str) else ""
    if not text or len(text) > max_text:
        raise Refused(422, f"질문은 1~{max_text}자로 보내 주세요")
    return {"text": text}


async def _sse(
    events: Iterator[BaseEvent], stop: threading.Event, done: Callable[[], None]
) -> AsyncIterator[str]:
    """이벤트를 작업 스레드에서 만들어 큐로 받아 SSE 글로 내보낸다."""
    # [왜] Starlette는 동기 iterator의 next()를 매번 다른 스레드에서 부를 수 있다.
    #      그래프는 한 스레드에서 끝까지 돌린다
    encoder = EventEncoder()
    lines: queue.Queue[str | None] = queue.Queue()

    def work() -> None:
        try:
            for event in events:
                lines.put(encoder.encode(event))
        finally:
            done()  # [왜] thread 잠금은 그래프가 실제로 멈춘 뒤에 푼다(연결이 끊긴 때가 아니다)
            lines.put(None)

    threading.Thread(target=work, daemon=True).start()
    try:
        while (line := await anyio.to_thread.run_sync(lines.get, abandon_on_cancel=True)) is not None:
            yield line
    finally:
        stop.set()


def build_app(graph, verify: Verify, *, web_origin: str) -> Starlette:
    """화면 서버 앱. graph는 컴파일한 메인 그래프, verify는 auth의 토큰 확인 함수."""
    # [왜] 이 앱이 부르는 그래프는 user_id 없이 사용자 데이터에 닿으면 멈춘다 (tools.user_of, R-048)
    graph = graph.with_config(configurable={"surface": SERVER_SURFACE})
    running: set[str] = set()
    guard = threading.Lock()
    cfg = load_rules("server")["request"]

    async def run(request: Request) -> Response:
        try:
            # [왜] 공개키를 받아 오는 동안 열린 SSE 흐름이 멈추지 않게 이벤트 루프 밖에서 부른다
            user = await anyio.to_thread.run_sync(
                user_from_header, request.headers.get("authorization"), verify
            )
            body = RunAgentInput.model_validate_json(await request.body())
        except AuthError as error:
            return JSONResponse({"error": str(error)}, status_code=error.status)
        except ValidationError:
            return JSONResponse({"error": "요청 모양이 틀렸어요"}, status_code=422)
        if not THREAD_ID.fullmatch(body.thread_id):
            return JSONResponse({"error": "대화 id 모양이 틀렸어요"}, status_code=422)
        key = f"{user}/{body.thread_id}"
        with guard:
            if key in running:
                return JSONResponse({"error": "이 대화는 아직 답하는 중이에요"}, status_code=409)
            running.add(key)
        config = {"configurable": {"thread_id": key, "user_id": user}}
        try:
            payload = await anyio.to_thread.run_sync(turn_input, graph, body, config)
        except Refused as error:
            running.discard(key)
            return JSONResponse({"error": str(error)}, status_code=error.status)
        except BaseException:
            running.discard(key)
            raise
        stop = threading.Event()
        events = turn_events(graph, payload, config, body.thread_id, body.run_id, stop)
        stream = _sse(events, stop, lambda: running.discard(key))
        return StreamingResponse(stream, media_type=EventEncoder().get_content_type(), headers=SSE_HEADERS)

    async def health(request: Request) -> Response:
        return JSONResponse({"ok": True})

    middleware = [
        # [왜] 화면 주소 하나만 연다. 쿠키를 쓰지 않아 credentials는 열지 않는다
        Middleware(
            CORSMiddleware,
            allow_origins=[web_origin],
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["authorization", "content-type"],
        ),
        Middleware(RequestBodyLimitMiddleware, max_body_size=cfg["max_body_bytes"]),
    ]
    routes = [
        Route("/agui", run, methods=["POST"]),
        Route("/health", health, methods=["GET"]),
    ]
    return Starlette(routes=routes, middleware=middleware)


def main() -> None:
    """운영 진입점: python -m marvia.server. 로그인 설정이 틀리면 뜨지 않는다. 포트는 PORT(Cloud Run)."""
    settings = Settings()
    verify = verifier(settings)  # [왜] 로그인 설정 검사를 DB에 붙기 전에 한다(fail-closed)
    for key in ("anthropic_api_key", "voyage_api_key", "data_key"):
        # [왜] 키 없이 뜨면 차례마다 실패한다. 배포 확인(dry-run)에서 바로 보이게 시작을 거절한다
        if not getattr(settings, key).get_secret_value():
            raise RuntimeError(f"MARVIA_{key.upper()}가 비어 있어 서버를 띄우지 않습니다")
    url = settings.database_url
    with (
        live_memory(url, settings.data_key.get_secret_value()) as (saver, store),
        read_pool(url) as pool,
        # [왜] 감시 목록은 따로 autocommit 연결을 쓴다 (R-041)
        psycopg.connect(url, autocommit=True) as watch_conn,
    ):
        deps = agent_deps(settings, pool, watch_conn)
        graph = build_main_graph(
            deps, saver, loop=settings.loop, store=store, permission_mode=settings.permission_mode
        )
        app = build_app(graph, verify, web_origin=settings.web_origin)
        # [주의] 기본은 127.0.0.1이다. 컨테이너 안에서만 MARVIA_HOST=0.0.0.0을 주고
        #        compose가 바깥 쪽을 127.0.0.1로 연다
        uvicorn.run(app, host=settings.host, port=int(os.environ.get("PORT", "8080")))


if __name__ == "__main__":
    main()
