"""MCP 도구 확인 스크립트 — 도구 목록을 찍고, 이름을 주면 그 도구를 한 번 부른다. (MCP_GUIDE "제출 증거")

왜 있나: 09-18 departure_calc 검증 때 쓴 클라이언트를 안 남겨서 다음 도구마다 다시 짜야 했다.
  이 파일을 두면 도구 6개 모두 같은 방법으로 확인하고, docs/evidence/mcp/ 증거도 여기 출력으로 남긴다.

어떻게 쓰나 (컨테이너 안에서 돌린다. scripts/ 는 이미지에 안 들어가므로 stdin 으로 넘긴다):
  도구 목록만:  docker compose exec -T api python - < scripts/mcp_check.py
  도구 호출:    docker compose exec -T api python - geocode '{"query": "마산역"}' < scripts/mcp_check.py

MCP SDK 2.x 기준 (server.py 와 같은 버전). 클라이언트 함수 이름이 v1 과 다르다 (streamable_http_client).
토큰은 서버와 같은 .env 의 MCP_TOKEN 을 읽는다 (server.py StaticTokenVerifier).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

# 컨테이너 안에서 자기 자신을 부른다. 밖에서 돌리면 localhost:8000 그대로 쓰면 된다.
URL = os.environ.get("MCP_CHECK_URL", "http://localhost:8000/mcp")


async def main(tool: str | None, args: dict) -> None:
    # 서버가 Bearer 토큰을 요구하므로 (server.py) 헤더를 단 클라이언트를 넘긴다
    headers = {"Authorization": f"Bearer {os.environ['MCP_TOKEN']}"}
    async with httpx.AsyncClient(headers=headers, timeout=30) as http:
        async with streamable_http_client(URL, http_client=http) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()  # MCP 악수. 이게 먼저 와야 도구를 물어볼 수 있다

                tools = await session.list_tools()
                print("== tools ==")
                for t in tools.tools:
                    print(f"- {t.name}: {t.description.splitlines()[0] if t.description else ''}")
                    print(f"    입력: {list(t.input_schema.get('properties', {}))}")
                    out = t.output_schema.get("properties", {}) if t.output_schema else {}
                    print(f"    출력: {list(out)}")

                if tool:
                    print(f"\n== call {tool} {args} ==")
                    res = await session.call_tool(tool, args)
                    if res.is_error:
                        print("ERROR:", [c.text for c in res.content if hasattr(c, "text")])
                    else:
                        print(json.dumps(res.structured_content, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else None
    params = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    asyncio.run(main(name, params))
