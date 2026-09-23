"""MCP 서버 연결 확인 스크립트 (B1 완료 기준, B10 캡처용).

서버에 붙어 initialize → tool 목록을 출력합니다.
    python -m mcp_server.check http://localhost:8001/mcp
"""
import asyncio
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def list_tools(url: str) -> list[str]:
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            info = await session.initialize()
            print(f"connected: {info.serverInfo.name} (protocol {info.protocolVersion})")
            tools = (await session.list_tools()).tools
            for t in tools:
                print(f"- {t.name}: {(t.description or '').splitlines()[0] if t.description else ''}")
            print(f"tools: {len(tools)}")
            return [t.name for t in tools]


if __name__ == "__main__":
    asyncio.run(list_tools(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8001/mcp"))
