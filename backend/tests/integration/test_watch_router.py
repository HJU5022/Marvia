"""화물 지켜보기 창구 테스트 (routers/watch.py, G5).

DB는 부르지 않는다. test_watch.FakeConn을 ops.open_conn 자리에 끼운다. B/L은 모의값이다.
"""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.account import operators as ops
from backend.tests.integration.test_admin import _login
from backend.tests.integration.test_watch import BL, USER, FakeConn, env  # noqa: F401  (env는 autouse 열쇠 설정)

ENDPOINTS = [("post", "/api/cargo/watch/state", {"bl_no": BL}), ("put", "/api/cargo/watch", {"bl_no": BL, "on": True}),
             ("get", "/api/watch/changes", None), ("post", "/api/watch/changes/seen", None),
             ("get", "/api/watch", None)]  # 감시 목록


@pytest.fixture
def db(monkeypatch):
    conn = FakeConn()
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    monkeypatch.setattr(ops, "open_conn", lambda: _Ctx(conn))
    return conn


class _Ctx:
    """with ops.open_conn() as conn 모양을 맞춘다."""

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *exc):
        return False


@pytest.fixture
def me(monkeypatch):
    return _login(monkeypatch, "kim@example.com")  # 사용자 ID는 'user-123'


def _call(method, path, body, headers=None):
    with TestClient(app) as c:
        return getattr(c, method)(path, headers=headers, **({"json": body} if body is not None else {}))


# ── 로그인·DB 조건 ──

@pytest.mark.parametrize("method,path,body", ENDPOINTS)
def test_login_disabled_is_401(monkeypatch, method, path, body):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    assert _call(method, path, body).status_code == 401


@pytest.mark.parametrize("method,path,body", ENDPOINTS)
def test_no_bearer_is_401_when_login_on(db, monkeypatch, method, path, body):
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")  # 로그인 켜짐, 헤더 없음
    assert _call(method, path, body).status_code == 401


@pytest.mark.parametrize("method,path,body", ENDPOINTS)
def test_no_database_is_503(monkeypatch, me, method, path, body):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert _call(method, path, body, me).status_code == 503


@pytest.mark.parametrize("method,path,body", ENDPOINTS)
def test_db_failure_is_503_without_leaking(monkeypatch, me, method, path, body):
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")

    def down():
        raise RuntimeError(f"connection to {BL} failed")

    monkeypatch.setattr(ops, "open_conn", down)
    r = _call(method, path, body, me)
    assert r.status_code == 503 and BL not in r.text and "connection" not in r.text


def test_bl_in_url_is_not_supported(db, me):
    """B/L은 본문으로만 받는다. 주소에 넣는 길은 없다."""
    assert _call("get", f"/api/cargo/watch/{BL}", None, me).status_code in (404, 405)


# ── state / put ──

def test_state_and_toggle_round_trip(db, me):
    r = _call("post", "/api/cargo/watch/state", {"bl_no": BL}, me)
    assert r.status_code == 200 and r.json() == {"saved": False, "watch": False}
    db.add()
    assert _call("post", "/api/cargo/watch/state", {"bl_no": BL}, me).json() == {"saved": True, "watch": False}
    r = _call("put", "/api/cargo/watch", {"bl_no": BL, "on": True}, me)
    assert r.status_code == 200 and r.json() == {"watch": True} and BL not in r.text
    assert _call("post", "/api/cargo/watch/state", {"bl_no": BL}, me).json() == {"saved": True, "watch": True}
    assert _call("put", "/api/cargo/watch", {"bl_no": BL, "on": False}, me).json() == {"watch": False}


def test_put_not_saved_is_404(db, me):
    r = _call("put", "/api/cargo/watch", {"bl_no": BL, "on": True}, me)
    assert r.status_code == 404 and r.json()["detail"] == "이 화물은 아직 저장되지 않았습니다. 잠시 뒤 다시 눌러 주세요"
    assert BL not in r.text


def test_put_done_is_409(db, me):
    db.add(status="done")
    r = _call("put", "/api/cargo/watch", {"bl_no": BL, "on": True}, me)
    assert r.status_code == 409 and r.json()["detail"] == "반출이 끝난 화물은 지켜볼 수 없습니다"


def test_put_limit_is_409(db, me):
    for i in range(5):
        db.add(bl=f"MOCKBL2026100{i}", watch=True)
    db.add()
    r = _call("put", "/api/cargo/watch", {"bl_no": BL, "on": True}, me)
    assert r.status_code == 409 and r.json()["detail"] == "지켜보기는 최대 5건까지입니다. 다른 화물을 먼저 끄세요"


def test_put_no_key_is_503(db, me, monkeypatch):
    monkeypatch.delenv("BL_ENCRYPTION_KEY")
    r = _call("put", "/api/cargo/watch", {"bl_no": BL, "on": True}, me)
    assert r.status_code == 503 and BL not in r.text


def test_put_off_without_row_is_ok(db, me):
    assert _call("put", "/api/cargo/watch", {"bl_no": BL, "on": False}, me).json() == {"watch": False}


def test_body_is_validated(db, me):
    assert _call("put", "/api/cargo/watch", {"bl_no": BL}, me).status_code == 422  # on 없음
    assert _call("post", "/api/cargo/watch/state", {}, me).status_code == 422


# ── changes / seen ──

def test_changes_then_seen(db, me):
    db.add(label="고추", last_verdict="act", changed_from="watch", change_seen=False,
           changed_at=datetime(2026, 10, 5, tzinfo=timezone.utc))
    db.add(bl="MOCKBL20261001", user="other", change_seen=False, changed_at=datetime(2026, 10, 5, tzinfo=timezone.utc))
    r = _call("get", "/api/watch/changes", None, me)
    assert r.status_code == 200
    assert r.json() == {"changes": [{"bl_masked": "MOC*******1005", "label": "고추", "from_verdict": "watch",
                                     "to_verdict": "act", "changed_at": "2026-10-05T00:00:00+00:00",
                                     "reason": None}]}
    assert BL not in r.text  # 가린 번호만 나간다
    assert _call("post", "/api/watch/changes/seen", None, me).json() == {"cleared": 1}
    assert _call("get", "/api/watch/changes", None, me).json() == {"changes": []}
    assert _call("post", "/api/watch/changes/seen", None, me).json() == {"cleared": 0}
    assert db.row("MOCKBL20261001", "other")["change_seen"] is False


def test_user_id_comes_from_token_only(db, me):
    """다른 사용자의 줄은 보이지도 바뀌지도 않는다."""
    db.add(user="other")
    r = _call("post", "/api/cargo/watch/state", {"bl_no": BL}, me)
    assert r.json() == {"saved": False, "watch": False}
    assert _call("put", "/api/cargo/watch", {"bl_no": BL, "on": True}, me).status_code == 404
    assert USER != "other" and db.row(user="other")["watch"] is False
