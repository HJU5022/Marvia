"""/health 테스트 (DB 연결까지 본다, 끊기면 503).

진짜 DB 없이 돈다. DB 연결은 main.connect를 가짜로 바꿔 성공·실패를 흉내 낸다.
"""
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.main import app


class _FakeConn:
    """with 문과 execute만 흉내 내는 가짜 DB 연결."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql):
        assert sql == "SELECT 1"


def test_health_without_database_url_is_ok(monkeypatch):
    # DB를 일부러 끈 환경(평가 실행기 등)은 고장이 아니다
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "db": "not_configured"}


def test_health_with_database_ok(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake/fake")
    monkeypatch.setattr(main, "_migrate", lambda: None)
    monkeypatch.setattr(main, "connect", lambda **kw: _FakeConn())
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "db": "ok"}


def test_health_with_database_down_is_503(monkeypatch):
    def fail(**kw):
        raise ConnectionError("connection refused host=secret-host")

    monkeypatch.setenv("DATABASE_URL", "postgresql://fake/fake")
    monkeypatch.setattr(main, "_migrate", lambda: None)
    monkeypatch.setattr(main, "connect", fail)
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.json() == {"status": "error", "db": "down"}
    # 응답에 예외 메시지(DB 주소 등)가 새지 않는다
    assert "secret-host" not in resp.text
