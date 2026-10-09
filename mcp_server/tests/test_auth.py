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


def test_without_token_open_only_in_replay_mode(monkeypatch):
    """토큰이 없으면 REPLAY_MODE일 때만 그대로 연다. 가공 응답만 읽어 키·호출 한도가 걸린 게 없다."""
    monkeypatch.setenv("REPLAY_MODE", "true")
    sentinel = object()
    assert protect(sentinel, token="") is sentinel


async def _post_from(app, client_ip: str) -> int:
    """요청을 보낸 주소(scope client)를 정해 /mcp에 POST하고 상태 코드를 돌려준다."""
    sent = []
    scope = {"type": "http", "method": "POST", "path": "/mcp", "raw_path": b"/mcp", "query_string": b"",
             "headers": [(b"host", b"api:8000")], "client": (client_ip, 50000), "server": ("api", 8000),
             "scheme": "http", "http_version": "1.1", "root_path": ""}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


@pytest.mark.anyio
async def test_without_token_refuses_outside_requests(monkeypatch):
    """토큰도 REPLAY_MODE도 없으면 루프백이 아닌 요청은 401 (전에는 누구에게나 열렸다)."""
    monkeypatch.delenv("REPLAY_MODE", raising=False)
    inner = Starlette(routes=[Route("/mcp", lambda request: PlainTextResponse("ok"), methods=["POST"])])
    app = protect(inner, token="")
    assert await _post_from(app, "172.18.0.5") == 401   # 같은 compose 망의 다른 컨테이너, 포트 매핑으로 온 요청
    assert await _post_from(app, "203.0.113.7") == 401  # 바깥


@pytest.mark.anyio
async def test_without_token_allows_loopback(monkeypatch):
    """api가 자기 /mcp를 부르는 길(MCP_URL=http://127.0.0.1:8000/mcp)은 토큰 없이도 돈다."""
    monkeypatch.delenv("REPLAY_MODE", raising=False)
    inner = Starlette(routes=[Route("/mcp", lambda request: PlainTextResponse("ok"), methods=["POST"])])
    app = protect(inner, token="")
    assert await _post_from(app, "127.0.0.1") == 200
    assert await _post_from(app, "::1") == 200


@pytest.mark.anyio
async def test_without_token_health_stays_public(monkeypatch):
    monkeypatch.delenv("REPLAY_MODE", raising=False)
    inner = Starlette(routes=[Route("/health", lambda request: PlainTextResponse("ok"))])
    transport = httpx.ASGITransport(app=protect(inner, token=""), client=("203.0.113.7", 1))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/health")).status_code == 200


def test_no_token_server_accepts_compose_service_host():
    """토큰이 없을 때 Host 허용 목록에 compose 서비스 이름(api)이 있다. worker의 MCP_URL=http://api:8000/mcp가 421로
    막히지 않게 한다. 토큰이 있으면 Host 검사를 끄고 토큰이 막는다."""
    from mcp_server.server import create_mcp

    no_token = create_mcp(token="").settings.transport_security
    assert no_token.enable_dns_rebinding_protection and "api:*" in no_token.allowed_hosts
    assert "localhost:*" in no_token.allowed_hosts
    with_token = create_mcp(token="secret-token").settings.transport_security
    assert not with_token.enable_dns_rebinding_protection
