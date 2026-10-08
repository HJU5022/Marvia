"""카카오톡 연결 API 테스트 (routers/kakao.py, 탈퇴 때 지우기는 services/account/account.py).

진짜 카카오·DB는 부르지 않는다. test_kakao_service.FakeConn, clients/kakao.py 가짜, 테스트용 열쇠를 쓴다.
"""
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend.app.clients import kakao as client
from backend.app.clients.kakao import KakaoError, Tokens
from backend.app.main import app
from backend.app.services.account import account as account_service
from backend.app.services.watch import kakao as svc
from backend.app.services.account import operators as ops
from backend.tests.integration.test_admin import _login
from backend.tests.integration.test_kakao_service import ACCESS, REFRESH, FakeConn, tokens

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


def _callback(headers, code=CODE, state=None):
    body = {"code": code, "state": state if state is not None else svc.make_state("user-123")}
    with TestClient(app) as c:
        return c.post("/api/kakao/callback", json=body, headers=headers)


def _assert_result(resp, result):
    assert resp.status_code == 200
    assert resp.json() == {"result": result}
    for secret in (CODE, ACCESS, REFRESH, "state", "token"):
        assert secret not in resp.text  # 응답에는 결과 이름만


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
    monkeypatch.setattr(client, "send_memo", lambda *a, **k: None)
    with TestClient(app) as c:
        assert c.get("/api/kakao/status", headers=me).json() == {"configured": True, "linked": False,
                                                                 "linked_at": None, "last_sent_at": None}
        svc.save_link(db, "user-123", tokens())
        body = c.get("/api/kakao/status", headers=me).json()
        assert body["linked"] is True and body["linked_at"] is not None and body["last_sent_at"] is None
        svc.send_to_user(db, "user-123", "안녕", "http://web/settings")  # 가짜 카카오 (아래 monkeypatch)
        assert c.get("/api/kakao/status", headers=me).json()["last_sent_at"] is not None

        def not_configured():
            raise KakaoError("not_configured")

        monkeypatch.setattr(client, "config", not_configured)
        body = c.get("/api/kakao/status", headers=me).json()
        assert body["configured"] is False and body["linked"] is True


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


# ── callback: 로그인한 화면이 부르는 POST, 결과마다 이름 하나 ──

def test_callback_login_disabled_is_401(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setattr(client, "exchange_code", lambda *a, **k: pytest.fail("로그인 없이는 토큰을 받으러 가지 않는다"))
    with TestClient(app) as c:
        r = c.post("/api/kakao/callback", json={"code": CODE, "state": svc.make_state("user-123")})
    assert r.status_code == 401


def test_callback_without_bearer_is_rejected_when_login_on(db, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")  # 로그인 켜짐, 헤더 없음
    monkeypatch.setattr(client, "exchange_code", lambda *a, **k: pytest.fail("헤더가 없으면 토큰을 받으러 가지 않는다"))
    with TestClient(app) as c:
        r = c.post("/api/kakao/callback", json={"code": CODE, "state": svc.make_state("user-123")})
    assert r.status_code == 401 and db.links == {}


def test_callback_no_database_is_503(me, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert _callback(me).status_code == 503


def test_callback_get_is_gone(db, me):
    with TestClient(app) as c:
        assert c.get("/api/kakao/callback", params={"code": CODE, "state": "x"}, headers=me).status_code == 405


def test_callback_connected_saves_encrypted_for_logged_in_user(db, me, monkeypatch):
    seen = []
    monkeypatch.setattr(client, "exchange_code", lambda code, **k: seen.append(code) or tokens())
    _assert_result(_callback(me), "connected")
    assert seen == [CODE]
    assert ACCESS not in str(db.links) and list(db.links) == ["user-123"]


def test_callback_mismatch_when_state_is_for_another_user(db, me, monkeypatch):
    monkeypatch.setattr(client, "exchange_code", lambda *a, **k: pytest.fail("남의 state면 인가 코드를 쓰지 않는다"))
    attacker_state = svc.make_state("attacker-1")  # 공격자가 만든 동의 링크의 state
    _assert_result(_callback(me, state=attacker_state), "mismatch")  # 로그인한 사람은 user-123
    assert db.links == {}  # 공격자 계정에도 피해자 계정에도 저장되지 않는다


@pytest.mark.parametrize("state", ["garbage", "a.b", "x"])
def test_callback_bad_state_is_expired(db, me, monkeypatch, state):
    monkeypatch.setattr(client, "exchange_code", lambda *a, **k: pytest.fail("state가 틀리면 토큰을 받으러 가지 않는다"))
    _assert_result(_callback(me, state=state), "expired")
    assert db.links == {}


def test_callback_expired_state(db, me, monkeypatch):
    state = svc.make_state("user-123")
    real = svc.time.time
    monkeypatch.setattr(svc.time, "time", lambda: real() + svc.STATE_TTL_SEC + 1)
    monkeypatch.setattr(client, "exchange_code", lambda *a, **k: pytest.fail("만료된 state면 토큰을 받으러 가지 않는다"))
    _assert_result(_callback(me, state=state), "expired")


def test_callback_missing_talk_message_scope(db, me, monkeypatch):
    monkeypatch.setattr(client, "exchange_code", lambda code, **k: Tokens(ACCESS, 100, REFRESH, 200, "profile_nickname"))
    _assert_result(_callback(me), "no_consent")
    assert db.links == {}  # 보낼 수 없는 토큰은 저장하지 않는다


def test_callback_scope_none_is_no_consent(db, me, monkeypatch):
    monkeypatch.setattr(client, "exchange_code", lambda code, **k: Tokens(ACCESS, 100, REFRESH, 200, None))
    _assert_result(_callback(me), "no_consent")
    assert db.links == {}


def test_callback_failures(db, me, monkeypatch):
    def kakao_down(code, **k):
        raise KakaoError("failed", 500)

    monkeypatch.setattr(client, "exchange_code", kakao_down)
    _assert_result(_callback(me), "failed")

    monkeypatch.setattr(client, "exchange_code", lambda code, **k: tokens())
    monkeypatch.delenv("PII_ENCRYPTION_KEY")  # 열쇠 없음 (KakaoLinkError)
    _assert_result(_callback(me), "failed")
    assert db.links == {}

    monkeypatch.setattr(client, "exchange_code", lambda code, **k: tokens(refresh=None))  # refresh 토큰 없음
    monkeypatch.setenv("PII_ENCRYPTION_KEY", Fernet.generate_key().decode())
    _assert_result(_callback(me), "failed")
    assert db.links == {}


def test_callback_empty_code_is_failed(db, me, monkeypatch):
    monkeypatch.setattr(client, "exchange_code", lambda *a, **k: pytest.fail("코드가 비면 토큰을 받으러 가지 않는다"))
    _assert_result(_callback(me, code=""), "failed")


def test_callback_missing_fields_is_422(db, me):
    with TestClient(app) as c:
        assert c.post("/api/kakao/callback", json={"code": CODE}, headers=me).status_code == 422


def test_callback_db_error_is_failed(db, me, monkeypatch):
    def broken():
        raise ConnectionError("테스트")

    monkeypatch.setattr(ops, "open_conn", broken)
    monkeypatch.setattr(client, "exchange_code", lambda code, **k: tokens())
    _assert_result(_callback(me), "failed")


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
    monkeypatch.setattr(account_service, "delete_conversations", lambda c, u: 0)
    monkeypatch.setattr(account_service.quota, "forget_user", lambda c, u: None)
    monkeypatch.setattr(account_service, "delete_account", lambda u: None)
    monkeypatch.setattr(client, "unlink", lambda *a, **k: pytest.fail("탈퇴는 카카오 서버를 부르지 않는다"))
    account_service.withdraw("user-123")
    assert list(conn.links) == ["other"]
