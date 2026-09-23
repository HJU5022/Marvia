"""MCP 서버 토큰 인증 (작업 A10).

/mcp는 Authorization: Bearer <MCP_TOKEN> 없이 부를 수 없다 (SDD 5.9, 7절).
공개된 Cloud Run 주소로 아무나 우리 ShipFinder·해수부 키를 태우지 못하게 막는 것이 목적이다.

FastMCP에는 OAuth 기반 인증이 있지만 발급 서버와 메타데이터 경로가 필요하다.
우리는 서버 사이(FastAPI에서 MCP)만 부르므로 고정 토큰 하나로 충분하다.
"""
import hmac
import logging
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

PUBLIC_PATHS = ("/health",)  # 배포 환경이 상태를 확인하는 경로는 연다


class BearerTokenMiddleware(BaseHTTPMiddleware):
    """Authorization 헤더의 Bearer 토큰이 MCP_TOKEN과 같아야 통과시킨다."""

    def __init__(self, app: ASGIApp, token: str):
        super().__init__(app)
        self._token = token

    async def dispatch(self, request: Request, call_next):
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        header = request.headers.get("authorization", "")
        scheme, _, value = header.partition(" ")
        # 토큰 비교는 hmac.compare_digest로 한다. 앞부분만 맞아도 시간 차이로 새는 것을 막는다
        if scheme.lower() != "bearer" or not hmac.compare_digest(value.strip(), self._token):
            logger.warning("인증 실패: %s %s", request.method, request.url.path)
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


def protect(app: ASGIApp, token: str | None = None) -> ASGIApp:
    """토큰이 있으면 인증을 건다. 없으면 경고만 남기고 그대로 둔다.

    로컬에서 토큰 없이 띄워보는 경우를 막지 않되, 조용히 열려 있지는 않게 한다.
    """
    token = token if token is not None else os.environ.get("MCP_TOKEN", "")
    if not token:
        logger.warning("MCP_TOKEN이 없어 /mcp가 인증 없이 열려 있습니다. 배포에서는 반드시 설정하세요")
        return app
    return BearerTokenMiddleware(app, token)
