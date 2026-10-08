"""MCP 서버 연결 확인 스크립트 (B1 완료 기준, B10 제출 캡처용).

서버에 붙어 initialize와 tool 목록 조회를 한다.

    python -m scripts.demo.mcp_check http://localhost:8000/mcp --token <MCP_TOKEN>

토큰을 생략하면 환경변수 MCP_TOKEN을 쓴다. 서버에 토큰이 걸려 있는데 안 주면 401이 난다 (A10).
"""
import argparse
import asyncio
import os

from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

load_dotenv()  # MCP_TOKEN을 .env에서 읽는다


async def list_tools(url: str, token: str | None = None) -> list[str]:
    headers = {"Authorization": f"Bearer {token}"} if token else None
    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            info = await session.initialize()
            print(f"connected: {info.serverInfo.name} (protocol {info.protocolVersion})")
            tools = (await session.list_tools()).tools
            for tool in tools:
                first_line = (tool.description or "").strip().splitlines()[0] if tool.description else ""
                print(f"- {tool.name}: {first_line}")
            print(f"tools: {len(tools)}")
            return [tool.name for tool in tools]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MCP 서버 연결 확인")
    parser.add_argument("url", nargs="?", default="http://localhost:8000/mcp")
    parser.add_argument("--token", default=os.environ.get("MCP_TOKEN"))
    args = parser.parse_args()
    asyncio.run(list_tools(args.url, args.token))
