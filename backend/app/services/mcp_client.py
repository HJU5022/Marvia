"""서비스가 MCP 도구를 MCP 프로토콜로 부르는 곳 (D9 "서비스에서 MCP 도구가 실제로 호출되는지 확인").

전에는 routers/agent.py 등이 mcp_server.tools의 함수를 파이썬으로 바로 불러서, /mcp는 외부 클라이언트만 썼다.
가이드 v4 배포 구조(/api/agent → /mcp)대로 서비스도 /mcp를 거치게 바꿨다.

통로는 MCP_URL로 정한다.
  - MCP_URL이 있으면(Dockerfile app 스테이지가 http://127.0.0.1:8000/mcp로 넣는다): 그 주소에 Streamable HTTP로 붙는다.
    외부 클라이언트와 같은 길이라 MCP_TOKEN 인증까지 거친다.
  - 없으면(테스트·평가 실행기·스크립트처럼 서버를 띄우지 않고 부를 때): 같은 프로세스 안의 MCP 서버에 메모리로 붙는다.
    HTTP와 인증만 빠지고, 도구 목록·입력 검사·호출은 같은 MCP 프로토콜로 오간다.

아래 함수 4개는 도구와 이름·인자가 같다. 부르는 쪽은 import 경로만 바꾸면 되고, 테스트가 바꿔치기하던 이름도 그대로다.
돌려주는 값도 도구가 돌려준 dict 그대로다. 도구는 결과를 JSON 모드로 만들어서(model_dump(mode="json"))
MCP 텍스트를 json.loads로 되돌리면 직접 부른 값과 같다.

호출마다 Langfuse에 tool 관측 하나를 남긴다 (SDD 5.11, call_tool). 키가 없으면 아무것도 안 한다.
"""
import asyncio
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.memory import create_connected_server_and_client_session

from backend.app.observability.langfuse import end_tool, start_tool

logger = logging.getLogger(__name__)

_memory_server = None  # 메모리 통로용 MCP 서버. 처음 쓸 때 한 번 만든다


def _failed(message: str, code: str = "mcp_failed", retryable: bool = True) -> dict:
    """MCP 통로 자체가 실패했을 때. 도구 실패와 같은 {error: ToolError} 모양이라 부르는 쪽이 따로 처리할 필요가 없다."""
    return {"error": {"code": code, "message": message, "retryable": retryable}}


def _leaves(exc: BaseException):
    """예외 그룹을 펼쳐 안쪽 예외를 하나씩 돌려준다. MCP 클라이언트는 HTTP 오류를 ExceptionGroup에 싸서 던진다."""
    if isinstance(exc, BaseExceptionGroup):
        for inner in exc.exceptions:
            yield from _leaves(inner)
    else:
        yield exc


def _transport_failed(exc: BaseException) -> dict:
    """통로 예외를 오류 dict로 바꾼다.

    인증 실패(401·403)는 다시 불러도 같은 결과라 retryable=False, 코드 unauthorized로 따로 낸다.
    전에는 ExceptionGroup 하나로 뭉쳐 mcp_failed·retryable=True가 되어, 토큰 설정 문제가 일시 장애처럼 보였다.
    그 밖의 연결 실패·응답 깨짐은 일시 장애일 수 있어 그대로 retryable=True다.
    """
    for leaf in _leaves(exc):
        if isinstance(leaf, httpx.HTTPStatusError) and leaf.response.status_code in (401, 403):
            return _failed(f"MCP 인증 실패 ({leaf.response.status_code})", code="unauthorized", retryable=False)
    return _failed(type(exc).__name__)


@asynccontextmanager
async def _session():
    """MCP 세션 하나를 연다. 도구 호출(_call)과 도구 목록(_list_tools)이 같은 통로를 쓴다."""
    url = os.environ.get("MCP_URL", "")
    if url:
        token = os.environ.get("MCP_TOKEN", "")
        headers = {"Authorization": f"Bearer {token}"} if token else None
        # mcp 1.30부터 streamablehttp_client(headers=...)는 폐기 예정이다. 새 streamable_http_client는 헤더를 받지 않고
        # httpx 클라이언트를 받는다. 옛 함수가 안에서 만들던 것과 같은 값(타임아웃 30초, 읽기 300초)으로 만들어 넘긴다
        timeout = httpx.Timeout(30, read=300)
        async with httpx.AsyncClient(headers=headers, timeout=timeout) as http:
            async with streamable_http_client(url, http_client=http) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session
    else:
        global _memory_server
        if _memory_server is None:
            from mcp_server.server import create_mcp  # 메모리 통로를 쓸 때만 불러온다
            _memory_server = create_mcp(token="")
        async with create_connected_server_and_client_session(_memory_server) as session:
            yield session


async def _call(name: str, arguments: dict) -> dict:
    async with _session() as session:
        result = await session.call_tool(name, arguments)

    text = result.content[0].text if result.content else ""
    if result.isError:  # 도구가 예외를 던졌을 때. 도구는 실패를 {error}로 돌려주게 돼 있어 보통은 없다
        # 입력 스키마 검사 실패(위도 999 등)도 여기로 온다. FastMCP(mcp 1.30)는 이를 별도 코드 없이
        # "... validation error(s) for <도구>Arguments" 문장으로만 알려 준다. 같은 입력으로 다시 불러도
        # 실패하므로 도구의 입력 오류와 같은 bad_input·retryable=False로 낸다 (port_schedule.py와 같은 코드)
        if "validation error" in text:
            return _failed(text[:200], code="bad_input", retryable=False)
        return _failed(text[:200])
    return json.loads(text)


def _summary(result: dict) -> tuple[dict, str | None]:
    """트레이스 output에 넣을 결과 요약과 오류 코드. 응답 원본은 넣지 않는다 (ShipFinder 약관, CLAUDE.md "할 것").

    성공이면 들어 있는 키 이름만, 실패면 오류 코드만 남긴다. 어느 도구가 무엇을 돌려줬는지 구분하는 데는 이걸로 충분하다.
    """
    error = result.get("error")
    if isinstance(error, dict):
        code = str(error.get("code", "unknown"))
        return {"ok": False, "error": code}, code
    return {"ok": True, "keys": sorted(result.keys())}, None


def _run(coro):
    """MCP 클라이언트 코루틴을 동기 코드에서 끝까지 돌리고 결과를 돌려준다.

    서비스 코드는 동기 함수이고 FastAPI 스레드풀에서 돈다. 그 스레드에는 이벤트 루프가 없어 asyncio.run으로 돌린다.
    이미 루프가 도는 곳에서는 asyncio.run이 RuntimeError를 낸다. 평가 실행기의 Langfuse run_experiment가 그렇게
    문항을 돌려 도구가 전부 mcp_failed였다. 그때는 새 스레드에서 따로 루프를 만들어 돌리고 끝날 때까지 기다린다.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:  # 루프 없음: 서비스(FastAPI 스레드풀)와 테스트의 보통 경로
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def call_tool(name: str, **arguments) -> dict:
    """MCP 도구 하나를 부른다. None인 인자는 빼서 도구 기본값을 쓰게 한다.

    코루틴은 _run()이 돌린다 (루프가 없으면 asyncio.run, 이미 있으면 별도 스레드).

    호출마다 Langfuse tool 관측 하나를 남긴다 (SDD 5.11 "MCP 도구 호출에 적용").
      - 이름: mcp:<도구 이름>
      - input: 인자 dict. 선박명·호출부호·MMSI·좌표뿐이고 B/L 번호는 도구 인자에 없다
      - output: 결과 요약(_summary). 실패면 오류 코드가 level=ERROR로 남는다
      - metadata: 통로(http·memory)와 지연(ms)
    start_tool·end_tool은 키가 없거나 Langfuse가 실패하면 아무것도 안 한다. 트레이스 때문에 호출이 막히지 않는다.
    """
    arguments = {k: v for k, v in arguments.items() if v is not None}
    transport = "http" if os.environ.get("MCP_URL", "") else "memory"  # _call()과 같은 기준
    tool = start_tool(f"mcp:{name}", arguments)
    started = time.monotonic()
    try:
        result = _run(_call(name, arguments))
    except Exception as e:  # 연결 실패·인증 실패(401)·응답 깨짐. 서비스는 도구 실패와 같은 경로(partial 등)로 간다
        logger.warning("MCP 도구 호출 실패: %s (%s)", name, type(e).__name__)
        result = _transport_failed(e)
    output, error = _summary(result)
    latency_ms = round((time.monotonic() - started) * 1000)
    end_tool(tool, output, {"transport": transport, "latency_ms": latency_ms}, error=error)
    return result


_read_only_tools: list[dict] | None = None  # 한 번 받은 도구 목록. 도구는 서버가 뜰 때 정해지고 실행 중에 안 바뀐다


async def _list_tools():
    async with _session() as session:
        return (await session.list_tools()).tools


def read_only_tools() -> list[dict]:
    """LLM에게 줄 도구 목록 (D9 B안: 후속 질문에서 LLM이 도구를 직접 고른다).

    MCP tools/list로 받아 OpenAI tool 형식으로 바꾼다. 이름·설명·입력 스키마는 MCP 서버가 준 그대로다.
    읽기 전용 표시(readOnlyHint=True)가 있는 도구만 넘긴다. 부작용 있는 도구는 LLM이 아예 볼 수 없다
    (D9 도구 권한 정책, 가이드 v4 신뢰 경계 "부작용이 있는 도구는 명시적 요청과 권한 없이 호출되지 않게").
    목록을 못 받으면 빈 목록. 그러면 후속 답은 도구 없이 지난 결과만으로 나간다.
    """
    global _read_only_tools
    if _read_only_tools is not None:
        return _read_only_tools
    try:
        tools = _run(_list_tools())
    except Exception as e:  # 목록 실패는 후속 답을 막지 않는다. 다음 요청에서 다시 받는다
        logger.warning("MCP 도구 목록 조회 실패 (%s)", type(e).__name__)
        return []
    _read_only_tools = [
        {"type": "function",
         "function": {"name": t.name, "description": t.description or "", "parameters": t.inputSchema}}
        for t in tools if t.annotations and t.annotations.readOnlyHint
    ]
    return _read_only_tools


def get_vessel_candidates(ship_name: str, nationality: str | None = None, eta_window_days: int | None = None,
                          call_sign: str | None = None) -> dict:
    return call_tool("get_vessel_candidates", ship_name=ship_name, nationality=nationality,
                     eta_window_days=eta_window_days, call_sign=call_sign)


def get_live_position(mmsi: int) -> dict:
    return call_tool("get_live_position", mmsi=mmsi)


def get_port_schedule(call_sign: str | None = None, ship_name: str | None = None, lookback_days: int | None = None,
                      lookahead_days: int | None = None) -> dict:
    return call_tool("get_port_schedule", call_sign=call_sign, ship_name=ship_name,
                     lookback_days=lookback_days, lookahead_days=lookahead_days)


def estimate_distance(lat: float, lng: float, sog: float | None = None) -> dict:
    return call_tool("estimate_distance", lat=lat, lng=lng, sog=sog)
