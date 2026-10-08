"""MCP 서버 토큰 인증 (작업 A10).

/mcp는 Authorization: Bearer <MCP_TOKEN> 없이 부를 수 없다 (SDD 5.9, 7절).
공개된 배포 주소로 아무나 우리 ShipFinder·해수부 키를 태우지 못하게 막는 것이 목적이다.

FastMCP에는 OAuth 기반 인증이 있지만 발급 서버와 메타데이터 경로가 필요하다.
우리는 서버 사이(FastAPI에서 MCP)만 부르므로 고정 토큰 하나로 충분하다.

MCP_TOKEN이 비었을 때 (전에는 경고만 남기고 /mcp를 누구에게나 열었다)
  - REPLAY_MODE면 연다. 외부 API 대신 가공 응답만 읽어 키가 새거나 호출 한도가 닳을 일이 없다 (SDD 6.1, 채점자 재현용)
  - 아니면 같은 컨테이너 안(루프백 주소)에서 온 요청만 받고 나머지는 401이다. api가 자기 /mcp를 부르는 길
    (Dockerfile app 스테이지 MCP_URL=http://127.0.0.1:8000/mcp, services/mcp_client.py)은 토큰 없이도 돌아야 해서다.
    .env.example의 MCP_TOKEN 기본값이 비어 있어 이 길까지 막으면 키만 채운 로컬 실행에서 조회가 모두 실패한다.
    포트 매핑·Cloud Run으로 들어온 요청은 루프백이 아니라서 막힌다.
    uvicorn은 X-Forwarded-For를 직접 붙은 상대가 127.0.0.1일 때만 믿는다(FORWARDED_ALLOW_IPS 기본값). 이 값을 *로
    바꾸면 밖에서 루프백인 척할 수 있으니 토큰 없이 띄울 때는 바꾸지 않는다
"""
import hmac
import ipaddress
import logging
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from backend.app.clients.replay import replay_enabled

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


def _is_loopback(request: Request) -> bool:
    """요청이 같은 컨테이너 안(127.0.0.1, ::1)에서 왔나. 주소를 모르면 아니라고 본다."""
    host = request.client.host if request.client else ""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class LoopbackOnlyMiddleware(BaseHTTPMiddleware):
    """MCP_TOKEN 없이 띄웠을 때 루프백에서 온 요청만 통과시킨다 (모듈 설명 참고)."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path in PUBLIC_PATHS or _is_loopback(request):
            return await call_next(request)
        logger.warning("MCP_TOKEN 없음, 외부 요청 거절: %s %s", request.method, request.url.path)
        return JSONResponse({"error": "unauthorized", "message": "MCP_TOKEN이 설정되지 않아 외부 요청을 받지 않습니다"},
                            status_code=401)


def protect(app: ASGIApp, token: str | None = None) -> ASGIApp:
    """토큰이 있으면 Bearer 인증을 건다. 없으면 REPLAY_MODE일 때만 그대로 열고, 아니면 루프백만 받는다.

    전에는 토큰이 없으면 경고만 남기고 열어 두었다. 키를 채우고 토큰을 빠뜨린 배포가 우리 ShipFinder·해수부 키를
    누구에게나 태우게 되어 막았다.
    """
    token = token if token is not None else os.environ.get("MCP_TOKEN", "")
    if token:
        return BearerTokenMiddleware(app, token)
    if replay_enabled():
        logger.warning("MCP_TOKEN이 없어 /mcp가 인증 없이 열려 있습니다 (REPLAY_MODE, 가공 응답만 씀)")
        return app
    logger.warning("MCP_TOKEN이 없어 /mcp는 같은 컨테이너 안의 요청만 받습니다. 외부에서 부르려면 MCP_TOKEN을 설정하세요")
    return LoopbackOnlyMiddleware(app)
