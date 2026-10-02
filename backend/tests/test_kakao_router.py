"""카카오톡 연결 API 테스트 (routers/kakao.py, 탈퇴 때 지우기는 services/account.py).

진짜 카카오·DB는 부르지 않는다. test_kakao_service.FakeConn, clients/kakao.py 가짜, 테스트용 열쇠를 쓴다.
"""
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend.app.clients import kakao as client
from backend.app.clients.kakao import KakaoError, Tokens
from backend.app.main import app
from backend.app.services import account as account_service
from backend.app.services import kakao as svc
from backend.app.services import operators as ops
from backend.tests.test_admin import _login
from backend.tests.test_kakao_service import ACCESS, REFRESH, FakeConn, tokens

WEB = "https://web.example.com"
CODE = "auth-code-XYZ"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("PII_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("KAKAO_CLIENT_SECRET", "fake-kakao-client-secret")
    monkeypatch.setenv("ALLOWED_ORIGINS", f"{WEB}/, http://localhost:3000")
    monkeypatch.setattr(client, "config", lambda: ("rest-key", "fake-kakao-client-secret", "http://cb"))


@pytest.fixture
def db(monkeypatch):
    conn = FakeConn()
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    monkeypatch.setattr(ops, "open_conn", lambda: conn)
    return conn


@pytest.fixture
def me(monkeypatch):
    return _login(monkeypatch, "kim@example.com")  # 사용자 ID는 'user-123'


def _callback(code=CODE, state=None, error=None):
    params = {k: v for k, v in {"code": code, "state": state, "error": error}.items() if v is not None}
    with TestClient(app) as c:
        return c.get("/api/kakao/callback", params=params, follow_redirects=False)


def _assert_redirect(resp, result):
    assert resp.status_code == 302
    loc = resp.headers["location"]
    assert loc == f"{WEB}/settings?kakao={result}"
    for secret in (CODE, ACCESS, REFRESH, "state", "token"):
        assert secret not in loc  # 주소창에 남을 값에는 결과 이름만


# ── 로그인·DB 조건 ──

@pytest.mark.parametrize("method,path", [("get", "/api/kakao/status"), ("post", "/api/kakao/connect"),
                                         ("post", "/api/kakao/test"), ("delete", "/api/kakao/link")])
def test_login_disabled_is_401(monkeypatch, method, path):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    with TestClient(app) as c:
        assert getattr(c, method)(path).status_code == 401


def test_no_database_is_503(monkeypatch, me):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with TestClient(app) as c:
        assert c.get("/api/kakao/status", headers=me).status_code == 503


# ── status / connect ──

def test_status(db, me, monkeypatch):
    with TestClient(app) as c:
        assert c.get("/api/kakao/status", headers=me).json() == {"configured": True, "linked": False}
        svc.save_link(db, "user-123", tokens())
        assert c.get("/api/kakao/status", headers=me).json() == {"configured": True, "linked": True}

        def not_configured():
            raise KakaoError("not_configured")

        monkeypatch.setattr(client, "config", not_configured)
        assert c.get("/api/kakao/status", headers=me).json() == {"configured": False, "linked": True}


def test_connect_returns_url_with_signed_state(db, me, monkeypatch):
    seen = []
    monkeypatch.setattr(client, "authorize_url", lambda state: seen.append(state) or f"https://kauth/authorize?state={state}")
    with TestClient(app) as c:
        r = c.post("/api/kakao/connect", headers=me)
    assert r.status_code == 200 and r.json()["url"] == f"https://kauth/authorize?state={seen[0]}"
    assert svc.read_state(seen[0]) == "user-123"


def test_connect_not_configured_is_503(db, me, monkeypatch):
    monkeypatch.delenv("KAKAO_CLIENT_SECRET")  # state를 서명할 수 없다
    with TestClient(app) as c:
        r = c.post("/api/kakao/connect", headers=me)
    assert r.status_code == 503 and "관리자" in r.json()["detail"]


# ── callback: 결과마다 이동 주소 ──

def test_callback_connected_saves_encrypted(db, monkeypatch):
    monkeypatch.setattr(client, "exchange_code", lambda code, **k: tokens())
    _assert_redirect(_callback(state=svc.make_state("user-123")), "connected")
    assert ACCESS not in str(db.links) and svc.is_linked(db, "user-123")


def test_callback_needs_no_bearer_header(db, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")  # 로그인 켜짐, 헤더 없음
    monkeypatch.setattr(client, "exchange_code", lambda code, **k: tokens())
    _assert_redirect(_callback(state=svc.make_state("user-123")), "connected")


def test_callback_denied(db, monkeypatch):
    monkeypatch.setattr(client, "exchange_code", lambda *a, **k: pytest.fail("취소했으면 토큰을 받으러 가지 않는다"))
    _assert_redirect(_callback(code=None, state=svc.make_state("user-123"), error="access_denied"), "denied")


@pytest.mark.parametrize("state", [None, "garbage", "a.b"])
def test_callback_bad_state_is_expired(db, monkeypatch, state):
    monkeypatch.setattr(client, "exchange_code", lambda *a, **k: pytest.fail("state가 틀리면 토큰을 받으러 가지 않는다"))
    _assert_redirect(_callback(state=state), "expired")
    assert db.links == {}


def test_callback_expired_state(db, monkeypatch):
    state = svc.make_state("user-123")
    real = svc.time.time
    monkeypatch.setattr(svc.time, "time", lambda: real() + svc.STATE_TTL_SEC + 1)
    _assert_redirect(_callback(state=state), "expired")


def test_callback_missing_talk_message_scope(db, monkeypatch):
    monkeypatch.setattr(client, "exchange_code", lambda code, **k: Tokens(ACCESS, 100, REFRESH, 200, "profile_nickname"))
    _assert_redirect(_callback(state=svc.make_state("user-123")), "no_consent")
    assert db.links == {}  # 보낼 수 없는 토큰은 저장하지 않는다


def test_callback_scope_none_is_no_consent(db, monkeypatch):
    monkeypatch.setattr(client, "exchange_code", lambda code, **k: Tokens(ACCESS, 100, REFRESH, 200, None))
    _assert_redirect(_callback(state=svc.make_state("user-123")), "no_consent")


def test_callback_failures(db, monkeypatch):
    state = svc.make_state("user-123")

    def kakao_down(code, **k):
        raise KakaoError("failed", 500)

    monkeypatch.setattr(client, "exchange_code", kakao_down)
    _assert_redirect(_callback(state=state), "failed")

    monkeypatch.setattr(client, "exchange_code", lambda code, **k: tokens())
    monkeypatch.delenv("PII_ENCRYPTION_KEY")  # 열쇠 없음
    _assert_redirect(_callback(state=state), "failed")
    assert db.links == {}

    monkeypatch.setattr(client, "exchange_code", lambda code, **k: tokens(refresh=None))  # refresh 토큰 없음
    monkeypatch.setenv("PII_ENCRYPTION_KEY", Fernet.generate_key().decode())
    _assert_redirect(_callback(state=state), "failed")

    _assert_redirect(_callback(code=None, state=state), "failed")  # code 없음

    monkeypatch.delenv("DATABASE_URL")  # DB 없음
    monkeypatch.setattr(client, "exchange_code", lambda code, **k: tokens())
    _assert_redirect(_callback(state=state), "failed")


def test_callback_db_error_is_failed(db, monkeypatch):
    def broken():
        raise ConnectionError("테스트")

    monkeypatch.setattr(ops, "open_conn", broken)
    monkeypatch.setattr(client, "exchange_code", lambda code, **k: tokens())
    _assert_redirect(_callback(state=svc.make_state("user-123")), "failed")


def test_callback_redirect_default_origin(db, monkeypatch):
    monkeypatch.delenv("ALLOWED_ORIGINS")
    resp = _callback(state=None)
    assert resp.headers["location"] == "http://localhost:3000/settings?kakao=expired"


# ── test / link ──

def test_test_sends_message_to_settings(db, me, monkeypatch):
    svc.save_link(db, "user-123", tokens())
    sent = []
    monkeypatch.setattr(client, "send_memo", lambda access, text, link_url, button_title="x", **k: sent.append((access, text, link_url)))
    with TestClient(app) as c:
        r = c.post("/api/kakao/test", headers=me)
    assert r.status_code == 200 and r.json() == {"sent": True}
    assert sent == [(ACCESS, "[Marvia] 카카오톡 알림이 연결되었습니다. 화물 판정이 바뀌면 이 채팅방으로 알려 드립니다.",
                     f"{WEB}/settings")]


def test_test_not_linked_is_404(db, me):
    with TestClient(app) as c:
        assert c.post("/api/kakao/test", headers=me).status_code == 404


@pytest.mark.parametrize("error,status", [
    (KakaoError("unauthorized", 401), 409), (KakaoError("no_consent", 403), 403),
    (KakaoError("not_configured"), 503), (KakaoError("failed", 500), 502), (KakaoError("weird"), 502)])
def test_test_error_mapping(db, me, monkeypatch, error, status):
    svc.save_link(db, "user-123", tokens())

    def send(*a, **k):
        raise error

    monkeypatch.setattr(client, "send_memo", send)
    with TestClient(app) as c:
        r = c.post("/api/kakao/test", headers=me)
    assert r.status_code == status
    assert ACCESS not in r.text and REFRESH not in r.text
    if status == 409:
        assert not svc.is_linked(db, "user-123")  # 죽은 토큰은 지운다


def test_delete_link(db, me, monkeypatch):
    svc.save_link(db, "user-123", tokens())
    unlinked = []
    monkeypatch.setattr(client, "unlink", lambda access, **k: unlinked.append(access))
    with TestClient(app) as c:
        r = c.delete("/api/kakao/link", headers=me)
        assert r.status_code == 200 and r.json() == {"linked": False}
        assert c.delete("/api/kakao/link", headers=me).status_code == 200  # 두 번 눌러도 같다
    assert unlinked == [ACCESS] and db.links == {}


# ── 탈퇴 ──

def test_withdraw_deletes_kakao_row_without_calling_kakao(monkeypatch):
    conn = FakeConn()
    svc.save_link(conn, "user-123", tokens())
    svc.save_link(conn, "other", tokens())
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    monkeypatch.setattr(account_service, "connect", lambda *a, **k: conn)
    monkeypatch.setattr(account_service, "delete_user_queries", lambda c, u: 0)
    monkeypatch.setattr(account_service, "delete_profile", lambda c, u: 0)
    monkeypatch.setattr(account_service, "forget_user", lambda c, u: 0)
    monkeypatch.setattr(account_service, "delete_account", lambda u: None)
    monkeypatch.setattr(client, "unlink", lambda *a, **k: pytest.fail("탈퇴는 카카오 서버를 부르지 않는다"))
    account_service.withdraw("user-123")
    assert list(conn.links) == ["other"]
