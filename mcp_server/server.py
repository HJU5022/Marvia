"""MCP 서버 — 필수 조건 5. 도메인 데이터·행동을 MCP 도구로 노출한다. (SDD 6절, MCP_GUIDE)

MCP(Model Context Protocol)는 LLM이 부를 수 있는 함수 목록을 표준 형식으로 공개하는 규약이다.
우리 파이프라인(services/geo.py·routes.py)이 이 도구들을 부르고, 채점 때는 Claude Desktop 같은
외부 클라이언트를 붙여 도구 목록·호출 결과 스크린샷을 남긴다 (docs/evidence/mcp/).

구조 (SDD 1절):
  backend/app/main.py 가 이 파일의 `mcp`를 /mcp 에 마운트한다. 별도 프로세스가 아니다.
  도구는 mcp_server/tools/ 에 파일 하나당 하나. 각 파일이 `mcp`를 import해 @mcp.tool()로 등록한다.
  실제 API 호출 코드는 여기 다시 쓰지 않는다. backend/app/services/·domain/ 함수를 부른다 (MCP_GUIDE).

SDK: mcp 2.x (MCPServer). 스캐폴딩의 v1 `FastMCP`는 2.x에서 import가 안 된다.
  - 마운트: mcp.streamable_http_app(streamable_http_path="/") 를 FastAPI에 mount
  - 수명: main.py lifespan 에서 `async with mcp.session_manager.run()` 을 열어야 한다. 빠지면
    첫 요청에서 "Task group is not initialized" 에러 (SDK 문서 run/asgi)

접근 제어 (MCP_GUIDE "Bearer 없으면 거부"):
  헤더 Authorization: Bearer {MCP_TOKEN} 이 .env 값과 같을 때만 통과. 브라우저가 직접 부르지 않고
  우리 백엔드와 채점자 클라이언트만 쓰므로 고정 토큰 하나로 충분하다. README에 이 방식을 적는다(가이드 요구).
"""
from __future__ import annotations

import os

from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings


class StaticTokenVerifier(TokenVerifier):
    """헤더의 토큰이 MCP_TOKEN과 같은지만 본다.

    SDK는 verify_token이 AccessToken을 돌려주면 통과, None이면 401로 응답한다.
    비교는 hmac.compare_digest로 — 길이·문자 차이에 따른 응답 시간 차이로 토큰을 추측하는 것을 막는다.
    """

    async def verify_token(self, token: str) -> AccessToken | None:
        import hmac

        expected = os.environ.get("MCP_TOKEN", "")
        if not expected or not hmac.compare_digest(token, expected):
            return None
        return AccessToken(token=token, client_id="converge-backend", scopes=["tools"], resource=_public_url())


def _public_url() -> str:
    """이 MCP 엔드포인트의 공개 주소. AuthSettings.resource_server_url 에 들어간다.
    로컬은 http://localhost:8000/mcp, 배포는 Cloud Run 주소 + /mcp (.env MCP_PUBLIC_URL)."""
    return os.environ.get("MCP_PUBLIC_URL", "http://localhost:8000/mcp")


mcp = MCPServer(
    "converge",
    token_verifier=StaticTokenVerifier(),
    # issuer_url은 OAuth 발급 서버 자리인데 우리는 고정 토큰이라 형식만 채운다. token_verifier와 auth는 항상 같이 넘긴다(SDK 문서).
    auth=AuthSettings(
        issuer_url=_public_url(),
        resource_server_url=_public_url(),
        required_scopes=["tools"],
    ),
)

# 도구 등록: tools/ 아래 파일들이 import 시점에 @mcp.tool()로 붙는다. 여기서 import해야 등록된다.
# noqa: 도구 파일이 이 파일의 `mcp`를 import하므로 순환을 피하려고 맨 아래에 둔다.
from mcp_server.tools import departure_calc, geocode, route_transit, search_places  # noqa: E402, F401
