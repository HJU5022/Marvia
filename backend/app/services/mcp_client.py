"""서비스가 MCP 도구를 MCP 프로토콜로 부르는 곳 (10-02, D9 "서비스에서 MCP 도구가 실제로 호출되는지 확인").

전에는 routers/agent.py 등이 mcp_server.tools의 함수를 파이썬으로 바로 불러서, /mcp는 외부 클라이언트만 썼다.
가이드 v4 배포 구조(/api/agent → /mcp)대로 서비스도 /mcp를 거치게 바꿨다.

통로는 MCP_URL로 정한다.
  - MCP_URL이 있으면(Dockerfile app 스테이지가 http://127.0.0.1:8000/mcp로 넣는다): 그 주소에 Streamable HTTP로 붙는다.
    외부 클라이언트와 같은 길이라 MCP_TOKEN 인증까지 거친다.
  - 없으면(테스트·평가 실행기·스크립트처럼 서버를 띄우지 않고 부를 때): 같은 프로세스 안의 MCP 서버에 메모리로 붙는다.
    HTTP와 인증만 빠지고, 도구 목록·입력 검사·호출은 같은 MCP 프로토콜로 오간다.

아래 함수 4개는 도구와 이름·인자가 같다. 부르는 쪽은 import 경로만 바꾸면 되고, 테스트가 바꿔치기하던 이름도 그대로다.
돌려주는 값도 도구가 돌려준 dict 그대로다. 도구는 결과를 JSON 모드로 만들어서(model_dump(mode="json"))
MCP 텍스트를 json.loads로 되돌리면 직접 부른 값과 같다 (10-02 확인).
"""
import asyncio
import json
import logging
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.memory import create_connected_server_and_client_session

logger = logging.getLogger(__name__)

_memory_server = None  # 메모리 통로용 MCP 서버. 처음 쓸 때 한 번 만든다


def _failed(message: str) -> dict:
    """MCP 통로 자체가 실패했을 때. 도구 실패와 같은 {error: ToolError} 모양이라 부르는 쪽이 따로 처리할 필요가 없다."""
    return {"error": {"code": "mcp_failed", "message": message, "retryable": True}}


async def _call(name: str, arguments: dict) -> dict:
    url = os.environ.get("MCP_URL", "")
    if url:
        token = os.environ.get("MCP_TOKEN", "")
        headers = {"Authorization": f"Bearer {token}"} if token else None
        async with streamablehttp_client(url, headers=headers) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments)
    else:
        global _memory_server
        if _memory_server is None:
            from mcp_server.server import create_mcp  # 메모리 통로를 쓸 때만 불러온다
            _memory_server = create_mcp(token="")
        async with create_connected_server_and_client_session(_memory_server) as session:
            result = await session.call_tool(name, arguments)

    text = result.content[0].text if result.content else ""
    if result.isError:  # 도구가 예외를 던졌을 때. 도구는 실패를 {error}로 돌려주게 돼 있어 보통은 없다
        return _failed(text[:200])
    return json.loads(text)


def call_tool(name: str, **arguments) -> dict:
    """MCP 도구 하나를 부른다. None인 인자는 빼서 도구 기본값을 쓰게 한다.

    서비스 코드는 동기 함수이고 FastAPI 스레드풀에서 돈다. 그 스레드에는 이벤트 루프가 없어 asyncio.run으로 돌린다.
    """
    arguments = {k: v for k, v in arguments.items() if v is not None}
    try:
        return asyncio.run(_call(name, arguments))
    except Exception as e:  # 연결 실패·인증 실패(401)·응답 깨짐. 서비스는 도구 실패와 같은 경로(partial 등)로 간다
        logger.warning("MCP 도구 호출 실패: %s (%s)", name, type(e).__name__)
        return _failed(type(e).__name__)


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
