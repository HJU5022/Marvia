"""도구 이름·설명·인자 스키마만 알려 주는 MCP 서버 (stdio). cli_model.py가 `claude -p`에 붙인다 (설계 13절).

[왜] 도구를 글로만 알려 주면 모델이 없는 도구를 직접 부르다 실패하고 검색 없이 답한다 (11-12 실측).
     MCP 서버로 보여 주면 모델이 평소처럼 도구 호출을 낸다.
실행: python cli_tools_stub.py <도구 목록 JSON 파일>
하지 않는 일: 도구 실행. 호출은 cli_model.py가 모델 메시지에서 읽고 에이전트 루프가 돌린다.
"""

import json
import sys

import anyio
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server


def list_result(specs: list[dict]) -> types.ListToolsResult:
    """도구 목록(이름, 설명, parameters)을 MCP 도구 목록 답으로 바꾼다."""
    return types.ListToolsResult(
        tools=[
            types.Tool(name=s["name"], description=s.get("description", ""), input_schema=s["parameters"])
            for s in specs
        ]
    )


async def serve(path: str) -> None:
    """파일의 도구 목록을 알려 주는 서버를 stdin·stdout으로 돌린다."""
    with open(path, encoding="utf-8") as file:
        specs = json.load(file)

    async def list_tools(ctx, params) -> types.ListToolsResult:
        return list_result(specs)

    async def call_tool(ctx, params) -> types.CallToolResult:
        # [주의] 여기까지 오면 cli_model.py가 프로세스를 제때 멈추지 못한 것이다. 실행하지 않고 오류로 답한다
        return types.CallToolResult(
            content=[types.TextContent(type="text", text="not executed")], is_error=True
        )

    # [왜] mcp 2.3.0의 낮은 층 Server는 처리 함수를 생성자 인자로 받는다 (설치된 소스 확인 11-12)
    server = Server("marvia", on_list_tools=list_tools, on_call_tool=call_tool)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    anyio.run(serve, sys.argv[1])
