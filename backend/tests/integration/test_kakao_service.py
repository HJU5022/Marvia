"""카카오톡 연결 서비스 테스트 (services/watch/kakao.py).

진짜 카카오·DB는 부르지 않는다. kakao_links 표를 흉내 내는 가짜 연결과, clients/kakao.py 함수를 바꿔 끼운 가짜,
테스트용 Fernet 열쇠·가짜 시크릿을 쓴다.
"""
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet

from backend.app import crypto
from backend.app.clients import kakao as client
from backend.app.clients.kakao import KakaoError, Tokens
from backend.app.services.watch import kakao as svc

SECRET = "fake-kakao-client-secret"
ACCESS, REFRESH = "raw-access-token-AAA", "raw-refresh-token-BBB"


class _Result:
    def __init__(self, rows=None, rowcount=0):
        self._rows, self.rowcount = rows or [], rowcount

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeConn:
    """kakao_links 한 표만 메모리에 둔다. 문장 앞부분으로 어떤 SQL인지 가른다 (test_admin.FakeConn과 같은 방식)."""

    def __init__(self):
        self.links: dict[str, dict] = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        q = " ".join(sql.split())
        if q.startswith("INSERT INTO kakao_links"):
            self.links[params[0]] = {"access": params[1], "refresh": params[2], "access_at": params[3],
                                     "refresh_at": params[4], "linked_at": datetime.now(timezone.utc), "last_sent_at": None}
            return _Result(rowcount=1)
        if q.startswith("SELECT 1 FROM kakao_links"):
            return _Result([(1,)] if params[0] in self.links else [])
        if q.startswith("SELECT access_token_enc, refresh_token_enc, access_expires_at FROM kakao_links"):
            row = self.links.get(params[0])
            return _Result([(row["access"], row["refresh"], row["access_at"])] if row else [])
        if q.startswith("SELECT linked_at, last_sent_at FROM kakao_links"):
            row = self.links.get(params[0])
            return _Result([(row["linked_at"], row["last_sent_at"])] if row else [])
        if q.startswith("UPDATE kakao_links SET last_sent_at"):
            self.links[params[0]]["last_sent_at"] = datetime.now(timezone.utc)
            return _Result(rowcount=1)
        if q.startswith("SELECT access_token_enc FROM kakao_links"):
            row = self.links.get(params[0])
            return _Result([(row["access"],)] if row else [])
        if q.startswith("UPDATE kakao_links SET access_token_enc = %s, access_expires_at = %s, updated_at"):
            self.links[params[2]].update(access=params[0], access_at=params[1])
            return _Result(rowcount=1)
        if q.startswith("UPDATE kakao_links SET access_token_enc = %s, access_expires_at = %s, refresh_token_enc"):
            self.links[params[4]].update(access=params[0], access_at=params[1], refresh=params[2], refresh_at=params[3])
            return _Result(rowcount=1)
        if q.startswith("DELETE FROM kakao_links"):
            return _Result(rowcount=1 if self.links.pop(params[0], None) else 0)
        raise AssertionError(f"예상하지 못한 SQL: {q}")


def tokens(refresh=REFRESH, refresh_in=5_000_000) -> Tokens:
    return Tokens(access_token=ACCESS, access_expires_in=43199, refresh_token=refresh, refresh_expires_in=refresh_in,
                  scope="talk_message")


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("PII_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("KAKAO_CLIENT_SECRET", SECRET)


# ── state ──

def test_state_round_trip():
    assert svc.read_state(svc.make_state("user-1")) == "user-1"


def test_state_with_pipe_in_user_id():
    assert svc.read_state(svc.make_state("a|b")) == "a|b"  # 마지막 | 로만 가른다


def test_tampered_state_is_rejected():
    state = svc.make_state("user-1")
    payload, sig = state.split(".")
    other = svc.make_state("user-2").split(".")[0]
    assert svc.read_state(f"{other}.{sig}") is None          # 다른 사람 이름에 내 서명
    assert svc.read_state(f"{payload}.{sig[:-2]}AA") is None  # 서명 바꿈
    for bad in ["", None, "garbage", "a.b", "a.b.c", "!!!.???"]:
        assert svc.read_state(bad) is None


def test_expired_state_is_rejected(monkeypatch):
    state = svc.make_state("user-1")
    real = svc.time.time
    monkeypatch.setattr(svc.time, "time", lambda: real() + svc.STATE_TTL_SEC + 1)
    assert svc.read_state(state) is None


def test_state_signed_with_other_secret_is_rejected(monkeypatch):
    state = svc.make_state("user-1")
    monkeypatch.setenv("KAKAO_CLIENT_SECRET", "another-secret")
    assert svc.read_state(state) is None


def test_no_secret_means_no_state(monkeypatch):
    state = svc.make_state("user-1")
    monkeypatch.delenv("KAKAO_CLIENT_SECRET")
    assert svc.read_state(state) is None
    with pytest.raises(KakaoError) as e:
        svc.make_state("user-1")
    assert e.value.kind == "not_configured"


# ── 저장 ──

def test_save_encrypts_both_tokens_and_sets_expiry():
    conn = FakeConn()
    svc.save_link(conn, "u1", tokens())
    row = conn.links["u1"]
    assert ACCESS not in str(row) and REFRESH not in str(row)  # 원문은 표에 없다
    assert crypto.decrypt_pii(row["access"]) == ACCESS and crypto.decrypt_pii(row["refresh"]) == REFRESH
    now = datetime.now(timezone.utc)
    assert timedelta(seconds=43100) < row["access_at"] - now <= timedelta(seconds=43199)
    assert timedelta(seconds=4_999_000) < row["refresh_at"] - now <= timedelta(seconds=5_000_000)
    assert svc.is_linked(conn, "u1") and not svc.is_linked(conn, "u2")


def test_relink_replaces_row():
    conn = FakeConn()
    svc.save_link(conn, "u1", tokens())
    svc.save_link(conn, "u1", Tokens("new-access", 100, "new-refresh", 200, "talk_message"))
    assert crypto.decrypt_pii(conn.links["u1"]["access"]) == "new-access" and len(conn.links) == 1


def test_no_key_saves_nothing(monkeypatch):
    monkeypatch.delenv("PII_ENCRYPTION_KEY")
    conn = FakeConn()
    with pytest.raises(svc.KakaoLinkError) as e:
        svc.save_link(conn, "u1", tokens())
    assert e.value.kind == "no_key" and conn.links == {}  # 원문을 대신 저장하지 않는다


def test_missing_refresh_token_is_failed():
    conn = FakeConn()
    with pytest.raises(svc.KakaoLinkError) as e:
        svc.save_link(conn, "u1", tokens(refresh=None))
    assert e.value.kind == "failed" and conn.links == {}


# ── 보내기 ──

@pytest.fixture
def linked():
    conn = FakeConn()
    svc.save_link(conn, "u1", tokens())
    return conn


def _spy(monkeypatch, refresh_result=None, send_error=None, refresh_error=None):
    calls = {"refresh": [], "send": [], "unlink": []}

    def refresh(token, **k):
        calls["refresh"].append(token)
        if refresh_error:
            raise refresh_error
        return refresh_result

    def send_memo(access, text, link_url, button_title="Marvia 열기", **k):
        calls["send"].append((access, text, link_url))
        if send_error:
            raise send_error

    monkeypatch.setattr(client, "refresh", refresh)
    monkeypatch.setattr(client, "send_memo", send_memo)
    monkeypatch.setattr(client, "unlink", lambda access, **k: calls["unlink"].append(access))
    return calls


def test_send_uses_stored_token_without_refresh(linked, monkeypatch):
    calls = _spy(monkeypatch)
    svc.send_to_user(linked, "u1", "안녕", "http://web/settings")
    assert calls["send"] == [(ACCESS, "안녕", "http://web/settings")] and calls["refresh"] == []


def test_send_refreshes_near_expiry_and_keeps_old_refresh_token(linked, monkeypatch):
    linked.links["u1"]["access_at"] = datetime.now(timezone.utc) + timedelta(minutes=4)
    old_refresh_enc, old_refresh_at = linked.links["u1"]["refresh"], linked.links["u1"]["refresh_at"]
    calls = _spy(monkeypatch, refresh_result=Tokens("fresh-access", 43199, None, None, None))
    svc.send_to_user(linked, "u1", "안녕", "http://web/settings")
    assert calls["refresh"] == [REFRESH] and calls["send"][0][0] == "fresh-access"
    row = linked.links["u1"]
    assert crypto.decrypt_pii(row["access"]) == "fresh-access"
    assert row["refresh"] == old_refresh_enc and row["refresh_at"] == old_refresh_at  # 안 줬으니 그대로
    assert row["access_at"] > datetime.now(timezone.utc) + timedelta(hours=11)


def test_send_stores_new_refresh_token_when_given(linked, monkeypatch):
    linked.links["u1"]["access_at"] = datetime.now(timezone.utc)
    _spy(monkeypatch, refresh_result=Tokens("fresh-access", 43199, "fresh-refresh", 5_000_000, None))
    svc.send_to_user(linked, "u1", "안녕", "http://web/settings")
    row = linked.links["u1"]
    assert crypto.decrypt_pii(row["refresh"]) == "fresh-refresh"
    assert "fresh-refresh" not in str(row) and "fresh-access" not in str(row)


def test_not_linked(monkeypatch):
    _spy(monkeypatch)
    with pytest.raises(svc.KakaoLinkError) as e:
        svc.send_to_user(FakeConn(), "u1", "x", "y")
    assert e.value.kind == "not_linked"


def test_unreadable_tokens_are_no_key(linked, monkeypatch):
    calls = _spy(monkeypatch)
    monkeypatch.setenv("PII_ENCRYPTION_KEY", Fernet.generate_key().decode())  # 열쇠가 바뀜
    with pytest.raises(svc.KakaoLinkError) as e:
        svc.send_to_user(linked, "u1", "x", "y")
    assert e.value.kind == "no_key" and calls["send"] == [] and "u1" in linked.links


def test_unauthorized_on_send_deletes_row_and_asks_relink(linked, monkeypatch):
    _spy(monkeypatch, send_error=KakaoError("unauthorized", 401))
    with pytest.raises(svc.KakaoLinkError) as e:
        svc.send_to_user(linked, "u1", "x", "y")
    assert e.value.kind == "relink" and linked.links == {}


def test_unauthorized_on_refresh_deletes_row_and_asks_relink(linked, monkeypatch):
    linked.links["u1"]["access_at"] = datetime.now(timezone.utc)
    calls = _spy(monkeypatch, refresh_error=KakaoError("unauthorized", 401))
    with pytest.raises(svc.KakaoLinkError) as e:
        svc.send_to_user(linked, "u1", "x", "y")
    assert e.value.kind == "relink" and linked.links == {} and calls["send"] == []


def test_no_consent_and_failed_pass_through_and_keep_row(linked, monkeypatch):
    for kind in ["no_consent", "failed"]:
        _spy(monkeypatch, send_error=KakaoError(kind, 403))
        with pytest.raises(KakaoError) as e:
            svc.send_to_user(linked, "u1", "x", "y")
        assert e.value.kind == kind and "u1" in linked.links


def test_send_is_not_retried(linked, monkeypatch):
    calls = _spy(monkeypatch, send_error=KakaoError("failed", 500))
    with pytest.raises(KakaoError):
        svc.send_to_user(linked, "u1", "x", "y")
    assert len(calls["send"]) == 1


# ── 연결 해제·삭제 ──

def test_unlink_calls_kakao_then_deletes(linked, monkeypatch):
    calls = _spy(monkeypatch)
    svc.unlink_user(linked, "u1")
    assert calls["unlink"] == [ACCESS] and linked.links == {}


def test_unlink_refreshes_first_when_access_expired(linked, monkeypatch):
    linked.links["u1"]["access_at"] = datetime.now(timezone.utc) - timedelta(hours=1)  # 12시간이 지나 죽은 토큰
    calls = _spy(monkeypatch, refresh_result=Tokens("fresh-access", 43199, None, None, None))
    svc.unlink_user(linked, "u1")
    assert calls["refresh"] == [REFRESH]
    assert calls["unlink"] == ["fresh-access"]  # 새 토큰으로 끊는다. 죽은 토큰(401)으로 끊지 않는다
    assert linked.links == {}


def test_unlink_refreshes_when_expiring_within_margin(linked, monkeypatch):
    linked.links["u1"]["access_at"] = datetime.now(timezone.utc) + timedelta(minutes=4)
    calls = _spy(monkeypatch, refresh_result=Tokens("fresh-access", 43199, None, None, None))
    svc.unlink_user(linked, "u1")
    assert calls["refresh"] == [REFRESH] and calls["unlink"] == ["fresh-access"]


def test_unlink_with_fresh_token_does_not_refresh(linked, monkeypatch):
    calls = _spy(monkeypatch)
    svc.unlink_user(linked, "u1")
    assert calls["refresh"] == [] and calls["unlink"] == [ACCESS]


def test_unlink_refresh_failure_still_deletes_row(linked, monkeypatch):
    linked.links["u1"]["access_at"] = datetime.now(timezone.utc) - timedelta(hours=1)
    calls = _spy(monkeypatch, refresh_error=KakaoError("unauthorized", 400))
    svc.unlink_user(linked, "u1")
    assert calls["refresh"] == [REFRESH] and calls["unlink"] == []  # 갱신이 안 되면 끊기는 부르지 않는다
    assert linked.links == {}  # 사용자의 해제 요청은 우리 쪽에서 끝난다


def test_unlink_refresh_link_error_still_deletes_row(linked, monkeypatch):
    linked.links["u1"]["access_at"] = datetime.now(timezone.utc) - timedelta(hours=1)
    monkeypatch.setattr(crypto, "encrypt_pii", lambda text: None)  # 새 토큰을 잠글 수 없다 → KakaoLinkError(no_key)
    monkeypatch.setattr(client, "refresh", lambda token, **k: Tokens("fresh-access", 43199, None, None, None))
    monkeypatch.setattr(client, "unlink", lambda *a, **k: pytest.fail("갱신 저장이 실패하면 끊기는 부르지 않는다"))
    svc.unlink_user(linked, "u1")
    assert linked.links == {}


def test_unlink_deletes_even_if_kakao_fails(linked, monkeypatch):
    def boom(access, **k):
        raise KakaoError("failed", 500)

    monkeypatch.setattr(client, "unlink", boom)
    svc.unlink_user(linked, "u1")
    assert linked.links == {}


def test_unlink_without_row_is_fine(monkeypatch):
    calls = _spy(monkeypatch)
    svc.unlink_user(FakeConn(), "nobody")
    assert calls["unlink"] == []


def test_delete_returns_row_count(linked):
    assert svc.delete(linked, "u1") == 1 and svc.delete(linked, "u1") == 0


def test_send_records_last_sent_at_only_on_success(linked, monkeypatch):
    assert linked.links["u1"]["last_sent_at"] is None
    _spy(monkeypatch, send_error=KakaoError("failed"))
    with pytest.raises(KakaoError):
        svc.send_to_user(linked, "u1", "안녕", "http://web/settings")
    assert linked.links["u1"]["last_sent_at"] is None  # 실패한 시도는 적지 않는다
    _spy(monkeypatch)
    svc.send_to_user(linked, "u1", "안녕", "http://web/settings")
    assert linked.links["u1"]["last_sent_at"] is not None
    linked_at, sent_at = svc.link_times(linked, "u1")
    assert linked_at is not None and sent_at is not None
    assert svc.link_times(linked, "nobody") is None
