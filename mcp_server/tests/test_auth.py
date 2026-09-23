"""A10 MCP 토큰 인증 테스트."""
import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from mcp_server.auth import protect
from mcp_server.server import build_app


@pytest.fixture
def app():
    return build_app(token="secret-token")


async def _post(app, headers: dict | None = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}, headers=headers or {})


@pytest.mark.anyio
async def test_rejects_request_without_token(app):
    resp = await _post(app)
    assert resp.status_code == 401 and resp.json()["error"] == "unauthorized"


@pytest.mark.anyio
async def test_rejects_wrong_token(app):
    resp = await _post(app, {"Authorization": "Bearer wrong-token"})
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_rejects_wrong_scheme(app):
    resp = await _post(app, {"Authorization": "Basic secret-token"})
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_passes_with_correct_token():
    """실제 MCP 앱은 세션 준비가 필요해서, 통과 여부만 단순 앱으로 확인한다."""
    inner = Starlette(routes=[Route("/mcp", lambda request: PlainTextResponse("ok"), methods=["POST"])])
    resp = await _post(protect(inner, token="secret-token"), {"Authorization": "Bearer secret-token"})
    assert resp.status_code == 200 and resp.text == "ok"


@pytest.mark.anyio
async def test_health_is_public():
    inner = Starlette(routes=[Route("/health", lambda request: PlainTextResponse("ok"))])
    transport = httpx.ASGITransport(app=protect(inner, token="secret-token"))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/health")).status_code == 200


def test_without_token_setting_app_is_open():
    """토큰이 없으면 인증을 걸지 않는다. 로컬에서 띄워보는 경우를 막지 않는다."""
    sentinel = object()
    assert protect(sentinel, token="") is sentinel
