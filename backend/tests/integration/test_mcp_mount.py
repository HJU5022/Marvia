"""API 서버 안의 /mcp 경로 테스트 (서버 하나로 합침, SDD 5.9).

- 토큰이 있으면 토큰 없이 401, 토큰이 맞으면 MCP initialize가 된다
- Cloud Run처럼 localhost가 아닌 Host로 와도 막히지 않는다 (토큰이 있을 때 Host 검사를 끈다)
- 서버 수명을 여러 번 열어도 된다 (FastMCP 세션 관리자는 한 번만 시작할 수 있어 수명마다 새로 만든다)
"""
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app

INITIALIZE = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}},
}
HEADERS = {"accept": "application/json, text/event-stream"}


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setenv("MCP_TOKEN", "secret-token")
    return "secret-token"


def test_mcp_needs_token(token):
    with TestClient(app) as client:
        assert client.post("/mcp", json=INITIALIZE, headers=HEADERS).status_code == 401


def test_mcp_initialize_with_token_on_public_host(token):
    # base_url의 Host가 Cloud Run 주소 모양이다. Host 검사가 켜져 있으면 421이 난다
    with TestClient(app, base_url="https://marvia-test.a.run.app") as client:
        resp = client.post("/mcp", json=INITIALIZE, headers={**HEADERS, "authorization": f"Bearer {token}"})
    assert resp.status_code == 200 and "marvia-mcp" in resp.text


def test_lifespan_can_open_twice(token):
    for _ in range(2):
        with TestClient(app) as client:
            resp = client.post("/mcp", json=INITIALIZE, headers={**HEADERS, "authorization": f"Bearer {token}"})
            assert resp.status_code == 200


def test_other_routes_unchanged(token):
    # /mcp를 붙여도 /health는 토큰 없이 열려 있다
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200 and resp.json()["status"] == "ok"
