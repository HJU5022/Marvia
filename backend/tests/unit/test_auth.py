"""로그인 출입증 확인 테스트 (G3, backend/app/auth.py).

테스트 안에서 ES256 키 쌍을 만들어 출입증을 직접 서명한다. 공개키 조회(_signing_key)를 바꿔 끼워 네트워크 없이 돈다.
"""
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException

from backend.app import auth

BASE = "https://test-project.supabase.co"
PRIVATE = ec.generate_private_key(ec.SECP256R1())  # Supabase가 가진 도장 역할
OTHER = ec.generate_private_key(ec.SECP256R1())  # 위조범의 도장


def _token(key=PRIVATE, algorithm="ES256", **over) -> str:
    now = int(time.time())
    claims = {"sub": "user-123", "aud": "authenticated", "iss": f"{BASE}/auth/v1", "iat": now, "exp": now + 3600}
    claims.update(over)
    return jwt.encode(claims, key, algorithm=algorithm)


@pytest.fixture(autouse=True)
def login_on(monkeypatch):
    """로그인 켬 + 공개키는 테스트 도장의 견본으로."""
    monkeypatch.setenv("SUPABASE_URL", BASE + "/")  # 끝 슬래시가 있어도 같은 주소로 본다
    monkeypatch.setattr(auth, "_signing_key", lambda token, base_url: PRIVATE.public_key())


def _status(header: str | None) -> int:
    with pytest.raises(HTTPException) as e:
        auth.current_user_id(authorization=header)
    return e.value.status_code


def test_valid_token_gives_user_id():
    assert auth.current_user_id(authorization=f"Bearer {_token()}") == "user-123"


def test_no_header_is_rejected_when_login_on():
    """로그인 필수. 손님으로 넘기지 않는다."""
    assert _status(None) == 401


def test_login_off_without_header_passes(monkeypatch):
    """SUPABASE_URL이 없으면(채점용 compose) 로그인 기능이 꺼져 헤더 없이도 돈다."""
    monkeypatch.delenv("SUPABASE_URL")
    assert auth.current_user_id(authorization=None) is None


def test_login_off_is_guest_even_with_header(monkeypatch):
    """SUPABASE_URL이 없으면(채점용 compose) 출입증을 보지 않고 손님으로 둔다."""
    monkeypatch.delenv("SUPABASE_URL")
    assert auth.current_user_id(authorization=f"Bearer {_token()}") is None


def test_expired_token_rejected():
    assert _status(f"Bearer {_token(exp=int(time.time()) - 10)}") == 401


def test_forged_signature_rejected():
    assert _status(f"Bearer {_token(key=OTHER)}") == 401


def test_other_project_issuer_rejected():
    assert _status(f"Bearer {_token(iss='https://other.supabase.co/auth/v1')}") == 401


def test_wrong_audience_rejected():
    """로그인하지 않은 공개 키(anon)로 만든 출입증 같은 것은 대상이 달라 막힌다."""
    assert _status(f"Bearer {_token(aud='anon')}") == 401


def test_hs256_token_rejected():
    """알고리즘을 HS256으로 바꾼 위조 출입증. ES256만 받으므로 막힌다.
    위조범의 비밀값은 실행 중에 만든다. 문자열로 적으면 비밀값 검사(gitleaks)가 키로 오인한다."""
    forged_secret = "x" * 32  # HS256은 32바이트 이상 비밀값을 요구한다. 아무 값이면 된다
    assert _status(f"Bearer {_token(key=forged_secret, algorithm='HS256')}") == 401


def test_missing_sub_rejected():
    assert _status(f"Bearer {_token(sub=None)}") == 401


def test_wrong_scheme_rejected():
    assert _status(f"Basic {_token()}") == 401


def test_jwks_unreachable_is_503(monkeypatch):
    """공개키를 못 받은 건 사용자 잘못이 아니므로 401(다시 로그인)이 아니라 503."""
    def fail(token, base_url):
        raise jwt.PyJWKClientConnectionError("down")

    monkeypatch.setattr(auth, "_signing_key", fail)
    assert _status(f"Bearer {_token()}") == 503
