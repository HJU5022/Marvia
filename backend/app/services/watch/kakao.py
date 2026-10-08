"""카카오톡 "나에게 보내기" 연결의 업무 규칙 (카카오 로그인 REST API 문서).

하는 일: 사용자별 카카오 토큰 보관(연결), 만료 전 갱신, 메시지 보내기, 연결 해제, 탈퇴 때 지우기.
HTTP 요청·응답은 라우터(routers/kakao.py)가, 카카오 서버 호출은 clients/kakao.py가 한다. 여기는 DB와 규칙만 안다.
나중에 만들 "판정이 바뀌면 알림" 작업도 HTTP 없이 send_to_user를 그대로 부른다.

왜 이렇게 했나:
- state를 서명하고 10분 뒤 만료시킨다: 연결을 시작한 사람이 누구인지 동의 화면 왕복 동안 들고 다니는 글자다.
  콜백은 로그인한 화면이 부르므로(routers/kakao.py), 라우터가 state 속 user_id와 지금 로그인한 사용자가 같은지 비교한다.
  서명이 없으면 남의 user_id를 넣어 위조할 수 있다. 서명 열쇠는 KAKAO_CLIENT_SECRET에서
  용도 이름을 붙여 갈라 쓴다(crypto.fingerprint와 같은 방식). 따로 비밀값을 하나 더 두지 않는다
- 토큰은 암호화해서 저장한다: 알림은 사용자가 화면을 안 볼 때 보내므로 서버가 토큰을 들고 있어야 한다.
  토큰이 새면 그 사람 카카오톡으로 메시지를 보낼 수 있어, 회원 정보와 같은 PII 열쇠(crypto.encrypt_pii)로 잠근다.
  열쇠가 없으면 원문을 저장하지 않는다
- 보내기는 재시도하지 않는다: 같은 알림이 두 번 가면 사용자가 불안해한다. 토큰 갱신(만료 5분 전)만 보내기 전에 한 번 한다
- 토큰이 죽었다(unauthorized)면 저장된 줄을 지우고 "다시 연결" 신호를 낸다. 죽은 토큰으로 계속 부르지 않으려는 것이다

토큰·인가 코드·시크릿은 로그와 오류에 넣지 않는다. 로그에는 오류 종류만 남긴다 (log_failure 규칙).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from datetime import datetime, timedelta, timezone

from backend.app import crypto
from backend.app.clients import kakao
from backend.app.clients.kakao import KakaoError, Tokens
from backend.app.observability.logging import log_failure

STATE_TTL_SEC = 600                 # state 유효 시간: 동의 화면을 넘기는 데 충분하고, 주워 쓰기엔 짧다
REFRESH_BEFORE = timedelta(minutes=5)  # access 토큰이 이 안에 만료되면 보내기 전에 갈아 끼운다
# refresh 토큰 수명 (카카오 문서: 60일). 응답에 기간이 빠졌을 때만 쓰는 대비값
REFRESH_DEFAULT_SEC = 60 * 24 * 3600


class KakaoLinkError(Exception):
    """우리 쪽 규칙 때문에 못 했다. kind: no_key(PII 열쇠 없음) / failed(refresh 토큰 없음)
    / not_linked(연결 안 됨) / relink(토큰이 죽어 다시 연결해야 함)."""

    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


# ── state: 누가 연결을 시작했는지 callback에 전하는 서명 글자 ──

def _state_key() -> bytes | None:
    """KAKAO_CLIENT_SECRET에서 state 전용 열쇠를 갈라 만든다. 시크릿이 없으면 None."""
    secret = os.environ.get("KAKAO_CLIENT_SECRET", "").strip()
    if not secret:
        return None
    return hashlib.sha256(b"marvia-kakao-state:" + secret.encode("utf-8")).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def make_state(user_id: str) -> str:
    """'<user_id|만료시각>.<서명>' 을 base64url로 만든다. 시크릿이 없으면 서명할 수 없으니 KakaoError(not_configured)."""
    key = _state_key()
    if key is None:
        raise KakaoError("not_configured")
    payload = f"{user_id}|{int(time.time()) + STATE_TTL_SEC}".encode("utf-8")
    return f"{_b64(payload)}.{_b64(hmac.new(key, payload, hashlib.sha256).digest())}"


def read_state(state: str | None) -> str | None:
    """서명이 맞고 만료 전이면 user_id, 아니면(위조·만료·깨짐·시크릿 없음) None."""
    key = _state_key()
    if key is None or not state:
        return None
    try:
        payload_part, sig_part = state.split(".")
        payload, sig = _unb64(payload_part), _unb64(sig_part)
        user_id, expiry = payload.decode("utf-8").rsplit("|", 1)
        expiry_at = int(expiry)
    except (ValueError, UnicodeDecodeError):  # 모양이 틀린 글자는 모두 위조로 본다
        return None
    if not hmac.compare_digest(sig, hmac.new(key, payload, hashlib.sha256).digest()):
        return None
    if expiry_at < time.time():
        return None
    return user_id or None


# ── 저장·조회 ──

def _now() -> datetime:
    return datetime.now(timezone.utc)


def save_link(conn, user_id: str, tokens: Tokens) -> None:
    """토큰을 잠가서 저장한다. 이미 연결돼 있으면 새 토큰으로 덮어쓴다(다시 연결).
    refresh 토큰이 없거나 하나라도 못 잠그면(열쇠 없음) 아무것도 저장하지 않는다."""
    if tokens.refresh_token is None:
        raise KakaoLinkError("failed")
    access_enc = crypto.encrypt_pii(tokens.access_token)
    refresh_enc = crypto.encrypt_pii(tokens.refresh_token)
    if access_enc is None or refresh_enc is None:
        raise KakaoLinkError("no_key")
    now = _now()
    conn.execute(
        """
        INSERT INTO kakao_links (user_id, access_token_enc, refresh_token_enc, access_expires_at, refresh_expires_at,
                                 linked_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, now(), now())
        ON CONFLICT (user_id) DO UPDATE SET access_token_enc = EXCLUDED.access_token_enc,
          refresh_token_enc = EXCLUDED.refresh_token_enc, access_expires_at = EXCLUDED.access_expires_at,
          refresh_expires_at = EXCLUDED.refresh_expires_at, linked_at = now(), updated_at = now()
        """,
        [user_id, access_enc, refresh_enc, now + timedelta(seconds=tokens.access_expires_in),
         now + timedelta(seconds=tokens.refresh_expires_in or REFRESH_DEFAULT_SEC)],
    )


def is_linked(conn, user_id: str) -> bool:
    return conn.execute("SELECT 1 FROM kakao_links WHERE user_id = %s", [user_id]).fetchone() is not None


def link_times(conn, user_id: str) -> tuple[datetime, datetime | None] | None:
    """(연결한 시각, 마지막 발송 시각). 연결이 없으면 None. 발송한 적 없으면 두 번째 값이 None."""
    row = conn.execute("SELECT linked_at, last_sent_at FROM kakao_links WHERE user_id = %s", [user_id]).fetchone()
    return (row[0], row[1]) if row else None


def delete(conn, user_id: str) -> int:
    """줄을 지운다. 연결 해제와 탈퇴(services/account/account.py)가 쓴다. 지운 줄 수."""
    return conn.execute("DELETE FROM kakao_links WHERE user_id = %s", [user_id]).rowcount


def _refresh_access(conn, user_id: str, refresh_token: str) -> str:
    """access 토큰을 갈아 끼우고 새 access 토큰을 돌려준다.
    카카오는 refresh 토큰 남은 기간이 길면 새 refresh 토큰을 주지 않는다. 준 경우에만 바꾼다."""
    new = kakao.refresh(refresh_token)
    access_enc = crypto.encrypt_pii(new.access_token)
    refresh_enc = crypto.encrypt_pii(new.refresh_token) if new.refresh_token else None
    if access_enc is None or (new.refresh_token and refresh_enc is None):
        raise KakaoLinkError("no_key")
    now = _now()
    access_at = now + timedelta(seconds=new.access_expires_in)
    if refresh_enc is None:
        conn.execute("UPDATE kakao_links SET access_token_enc = %s, access_expires_at = %s, updated_at = now() "
                     "WHERE user_id = %s", [access_enc, access_at, user_id])
    else:
        refresh_at = now + timedelta(seconds=new.refresh_expires_in or REFRESH_DEFAULT_SEC)
        conn.execute("UPDATE kakao_links SET access_token_enc = %s, access_expires_at = %s, refresh_token_enc = %s, "
                     "refresh_expires_at = %s, updated_at = now() WHERE user_id = %s",
                     [access_enc, access_at, refresh_enc, refresh_at, user_id])
    return new.access_token


def send_to_user(conn, user_id: str, text: str, link_url: str) -> None:
    """그 사용자의 카카오톡 "나에게 보내기" 채팅방으로 메시지를 보낸다. 재시도하지 않는다.
    KakaoLinkError: not_linked / no_key / relink. KakaoError: no_consent·failed·not_configured는 그대로 올린다."""
    row = conn.execute("SELECT access_token_enc, refresh_token_enc, access_expires_at FROM kakao_links "
                       "WHERE user_id = %s", [user_id]).fetchone()
    if row is None:
        raise KakaoLinkError("not_linked")
    access, refresh_token = crypto.decrypt_pii(row[0]), crypto.decrypt_pii(row[1])
    if access is None or refresh_token is None:  # 열쇠가 없거나 바뀜
        raise KakaoLinkError("no_key")
    try:
        if row[2] - _now() <= REFRESH_BEFORE:
            access = _refresh_access(conn, user_id, refresh_token)
        kakao.send_memo(access, text, link_url)
        # 보냈다는 시각. 설정 화면이 "마지막 발송"으로 보여 준다 (022). 실패한 시도는 적지 않는다
        conn.execute("UPDATE kakao_links SET last_sent_at = now() WHERE user_id = %s", [user_id])
    except KakaoError as e:
        if e.kind != "unauthorized":
            raise
        # 토큰이 죽었다(사용자가 카카오에서 연결을 끊었거나 refresh 기한 만료). 줄을 지우고 다시 연결을 안내한다
        log_failure("kakao_send", "unauthorized")
        delete(conn, user_id)
        raise KakaoLinkError("relink") from None


def unlink_user(conn, user_id: str) -> None:
    """카카오 쪽 연결을 끊고(실패해도 계속) 우리 줄을 지운다. 연결이 없어도 괜찮다.
    access 토큰은 12시간쯤이면 죽는다. 죽은 토큰으로 끊으면 카카오가 401을 주고 clients/kakao.unlink는 그것을
    "이미 끊김"으로 보므로, 카카오 쪽 연결이 남은 채 우리 줄만 지워진다. 그래서 만료가 가까우면 먼저 갱신한다(send_to_user와 같은 규칙).
    카카오가 안 닿아도 사용자의 해제 요청은 우리 쪽에서 끝나야 해서, 갱신·끊기 실패는 종류만 남기고 줄은 늘 지운다."""
    row = conn.execute("SELECT access_token_enc, refresh_token_enc, access_expires_at FROM kakao_links "
                       "WHERE user_id = %s", [user_id]).fetchone()
    if row is not None:
        access, refresh_token = crypto.decrypt_pii(row[0]), crypto.decrypt_pii(row[1])
        try:
            if access is not None and refresh_token is not None and row[2] - _now() <= REFRESH_BEFORE:
                access = _refresh_access(conn, user_id, refresh_token)
            if access is not None:
                kakao.unlink(access)
        except (KakaoError, KakaoLinkError) as e:
            log_failure("kakao_unlink", e.kind)
    delete(conn, user_id)
