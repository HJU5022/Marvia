"""릴레이 테스트. 실제 네트워크 없이 MockTransport로 돈다."""
import httpx
import pytest
from fastapi.testclient import TestClient

from relay import main

OK_PATH = "/1192000/VsslEtrynd5/Info5"


@pytest.fixture
def seen(monkeypatch):
    """업스트림으로 나간 요청을 모으고, 가짜 XML을 돌려준다."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, text="<response/>", headers={"content-type": "application/xml"})

    monkeypatch.setattr(main, "_client", httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setenv("RELAY_TOKEN", "secret")
    return calls


client = TestClient(main.app)
GOOD = {"X-Relay-Token": "secret"}


def test_healthz_needs_no_token(monkeypatch):
    monkeypatch.delenv("RELAY_TOKEN", raising=False)
    r = client.get("/health")
    assert (r.status_code, r.text) == (200, "ok")


def test_missing_env_refuses_everything(monkeypatch, seen):
    monkeypatch.delenv("RELAY_TOKEN", raising=False)
    assert client.get(OK_PATH, headers=GOOD).status_code == 503
    assert seen == []


@pytest.mark.parametrize("headers", [{}, {"X-Relay-Token": "wrong"}])
def test_bad_token_is_401(seen, headers):
    assert client.get(OK_PATH, headers=headers).status_code == 401
    assert seen == []


@pytest.mark.parametrize("path", ["/1192000/Other/Info", "/1192000/VsslEtrynd5", "/1192000/VsslEtrynd5/../X/y"])
def test_path_outside_allowlist_is_404(seen, path):
    assert client.get(path, headers=GOOD).status_code == 404
    assert seen == []


def test_forwards_query_unchanged_and_returns_upstream(seen):
    r = client.get(OK_PATH + "?serviceKey=a%2Bb%3D&sde=20261001", headers=GOOD)
    assert r.status_code == 200 and r.text == "<response/>"
    assert r.headers["content-type"].startswith("application/xml")
    assert str(seen[0].url) == "https://apis.data.go.kr" + OK_PATH + "?serviceKey=a%2Bb%3D&sde=20261001"
    assert "x-relay-token" not in seen[0].headers  # 토큰은 업스트림으로 새지 않는다


def test_upstream_timeout_is_504(monkeypatch):
    def boom(request):
        raise httpx.ConnectTimeout("x")

    monkeypatch.setattr(main, "_client", httpx.Client(transport=httpx.MockTransport(boom)))
    monkeypatch.setenv("RELAY_TOKEN", "secret")
    assert client.get(OK_PATH, headers=GOOD).status_code == 504


def test_query_not_logged(seen, caplog):
    with caplog.at_level("INFO", logger="relay"):
        client.get(OK_PATH + "?serviceKey=TOPSECRET", headers=GOOD)
    assert "path=" + OK_PATH in caplog.text
    assert "TOPSECRET" not in caplog.text
