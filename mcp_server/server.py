"""MCP 서버 — 필수 조건 5.

서비스 기능을 MCP tool로 노출합니다. 2주차 17강에서 만든 그대로입니다.

확인 방법은 자유입니다:
  - Claude Desktop / Cursor에 연결해 자연어로 호출
  - 18강처럼 langchain-mcp-adapters로 붙여 확인

도구를 무엇으로 가를지가 설계입니다. tool_description만 읽고도
언제 쓰는 도구인지 알 수 있어야 합니다 (2주차 6·7강).
"""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("project-mcp")


@mcp.tool()
def example_tool(query: str) -> str:
    """이 도구가 언제 쓰이는지 한 문장으로 적습니다. 모델이 이 설명만 보고 고릅니다.

    Args:
        query: 무엇을 넣어야 하는지
    """
    raise NotImplementedError


if __name__ == "__main__":
    mcp.run()
