"""화면 서버 로그인 확인 시험 (계획 4b Task 4, C4). 시험 안에서 만든 ES256 키로 돌고 네트워크를 안 쓴다."""

import io
import json
import time
import urllib.request

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from marvia.auth import (
    DEV_USER,
    TRACING_VARS,
    AuthError,
    check_startup,
    dev_verifier,
    supabase_verifier,
    user_from_header,
)
from marvia.config import Settings

BASE = "https://demo.supabase.test"
KEY = ec.generate_private_key(ec.SECP256R1())  # [왜] 시험 안에서 만든 키. 저장소에 키를 두지 않는다
OTHER = ec.generate_private_key(ec.SECP256R1())
SETTINGS = Settings(_env_file=None, supabase_url=BASE, owner_ids="owner-1, owner-2")


def token(key=KEY, headers=None, **changes) -> str:
    claims = {
        "sub": "owner-1",
        "iss": f"{BASE}/auth/v1",
        "aud": "authenticated",
        "exp": int(time.time()) + 300,
    }
    claims = {k: v for k, v in (claims | changes).items() if v is not None}
    return jwt.encode(claims, key, algorithm="ES256", headers=headers)


def forged(algorithm: str, key) -> str:
    """alg를 바꿔 만든 위조 토큰. 내용(claims)은 올바른 토큰과 같다."""
    claims = {
        "sub": "owner-1",
        "iss": f"{BASE}/auth/v1",
        "aud": "authenticated",
        "exp": int(time.time()) + 300,
    }
    return jwt.encode(claims, key, algorithm=algorithm)


VERIFY = supabase_verifier(SETTINGS, signing_key=lambda raw: KEY.public_key())


def test_a_signed_token_of_an_owner_gives_its_user_id():
    assert user_from_header(f"Bearer {token()}", VERIFY) == "owner-1"


@pytest.mark.parametrize(
    "bad",
    [
        token(OTHER),  # 서명이 다른 키
        token(exp=int(time.time()) - 120),  # 만료 (leeway 30초보다 오래전)
        token(iss="https://other.supabase.test/auth/v1"),  # 다른 프로젝트가 발급
        token(aud="anon"),  # 로그인한 사용자 토큰이 아니다
        token(exp=None),  # 만료 시각이 없다
        "not-a-jwt",
        forged(
            "HS256", "x" * 64
        ),  # [왜] 알고리즘 목록을 ES256 하나로 닫았는지 본다. 목록이 열리면 이 토큰이 통한다
        forged("none", None),  # 서명 없는 토큰
    ],
    ids=["signature", "expired", "issuer", "audience", "no-exp", "garbage", "alg-hs256", "alg-none"],
)
def test_bad_tokens_are_401_without_the_reason_text(bad):
    with pytest.raises(AuthError) as refused:
        user_from_header(f"Bearer {bad}", VERIFY)
    assert refused.value.status == 401 and str(refused.value) == "로그인을 확인하지 못했어요"


def test_a_signed_token_outside_the_owner_list_is_403():
    with pytest.raises(AuthError) as refused:
        user_from_header(f"Bearer {token(sub='stranger')}", VERIFY)
    assert refused.value.status == 403


@pytest.mark.parametrize("header", [None, "", "Basic abc", "Bearer ", "Bearer"])
def test_a_missing_or_other_scheme_header_is_401(header):
    with pytest.raises(AuthError) as refused:
        user_from_header(header, VERIFY)
    assert refused.value.status == 401


def test_dev_login_takes_only_its_fixed_token():
    verify = dev_verifier(Settings(_env_file=None, auth="dev", dev_token="local-dev-token"))
    assert user_from_header("Bearer local-dev-token", verify) == DEV_USER
    with pytest.raises(AuthError) as refused:
        user_from_header("Bearer local-dev-token-x", verify)
    assert refused.value.status == 401


@pytest.mark.parametrize(
    ("changes", "cloud_run", "message"),
    [
        ({"auth": "dev", "dev_token": "t"}, True, "Cloud Run"),
        ({"auth": "dev"}, False, "MARVIA_DEV_TOKEN"),
        ({"owner_ids": "owner-1"}, False, "MARVIA_SUPABASE_URL"),
        ({"supabase_url": BASE}, False, "MARVIA_OWNER_IDS"),
    ],
    ids=["dev-on-cloud-run", "dev-without-token", "no-supabase-url", "no-owners"],
)
def test_the_server_refuses_to_start_with_an_unsafe_login_setting(monkeypatch, changes, cloud_run, message):
    # [왜] 개발 로그인이 운영에 켜진 채 배포되거나, 로그인 확인 없이 뜨는 일을 시작에서 막는다 (fail-closed)
    for name in ("MARVIA_AUTH", "MARVIA_SUPABASE_URL", "MARVIA_OWNER_IDS", "MARVIA_DEV_TOKEN"):
        monkeypatch.delenv(name, raising=False)  # [왜] 셸에 걸린 값이 시험의 빈 설정을 채우지 않게 한다
    if cloud_run:
        monkeypatch.setenv("K_SERVICE", "marvia-api")  # Cloud Run이 넣는 환경 변수
    else:
        monkeypatch.delenv("K_SERVICE", raising=False)
    with pytest.raises(RuntimeError, match=message):
        check_startup(Settings(_env_file=None, **changes))


@pytest.mark.parametrize(
    "name", ["LANGSMITH_TRACING", "LANGSMITH_TRACING_V2", "LANGCHAIN_TRACING", "LANGCHAIN_TRACING_V2"]
)
@pytest.mark.parametrize("auth", ["supabase", "dev"])
def test_the_server_refuses_to_start_with_langsmith_tracing_on(monkeypatch, name, auth):
    # [왜] R-069: langsmith는 환경 변수만으로 추적을 켜고 콜백 값을 scrub 없이 밖으로 보낸다
    for var in (
        "K_SERVICE",
        "LANGSMITH_TRACING",
        "LANGSMITH_TRACING_V2",
        "LANGCHAIN_TRACING",
        "LANGCHAIN_TRACING_V2",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv(name, "true")
    ok = Settings(_env_file=None, supabase_url=BASE, owner_ids="owner-1", auth=auth, dev_token="t")
    with pytest.raises(RuntimeError, match=name):
        check_startup(ok)
    monkeypatch.setenv(name, "false")
    check_startup(ok)  # 꺼 두면 뜬다


@pytest.mark.parametrize(
    "name", ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_TRACING_ENVIRONMENT"]
)
def test_the_server_refuses_to_start_with_a_raw_langfuse_env_var(monkeypatch, name):
    # [왜] SDK가 이 이름을 직접 읽어 가림 연결(MARVIA_LANGFUSE_*) 밖에서 켜질 수 있다 (계획 6b)
    for var in ("K_SERVICE", *TRACING_VARS):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv(name, "x")
    ok = Settings(
        _env_file=None,
        supabase_url=BASE,
        owner_ids="owner-1",
        langfuse_public_key="pk-x",
        langfuse_secret_key="sk-x",
        langfuse_host="https://x.test",
    )
    with pytest.raises(RuntimeError, match=name):
        check_startup(ok)
    monkeypatch.delenv(name)
    check_startup(ok)  # MARVIA_LANGFUSE_*만 있으면 뜬다


def over_the_wire(monkeypatch, reply):
    """JWKS 받기를 네트워크 없이 바꿔 끼운다. reply가 예외면 던지고, 아니면 그 바이트를 200 본문으로 준다."""
    asked = []

    def fake_open(self, request, data=None, timeout=None):
        asked.append((request.full_url, timeout))
        if isinstance(reply, Exception):
            raise reply
        return io.BytesIO(reply)

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", fake_open)
    return asked


@pytest.mark.parametrize(
    "reply", [b"<html>not json</html>", ConnectionResetError("reset")], ids=["non-json-200", "reset"]
)
def test_a_broken_key_list_is_401_not_a_raw_exception(monkeypatch, reply):
    asked = over_the_wire(monkeypatch, reply)
    verify = supabase_verifier(SETTINGS)
    with pytest.raises(AuthError) as refused:
        user_from_header(f"Bearer {token(headers={'kid': 'k1'})}", verify)
    assert refused.value.status == 401 and str(refused.value) == "로그인을 확인하지 못했어요"
    assert asked[0][1] == 5  # rules/server.yaml auth.jwks_timeout_s


@pytest.mark.parametrize(("ahead", "ok"), [(10, True), (120, False)], ids=["within-leeway", "beyond-leeway"])
def test_clock_skew_is_allowed_only_up_to_the_leeway(ahead, ok):
    early = token(iat=int(time.time()) + ahead)
    if ok:
        assert user_from_header(f"Bearer {early}", VERIFY) == "owner-1"
    else:
        with pytest.raises(AuthError) as refused:
            user_from_header(f"Bearer {early}", VERIFY)
        assert refused.value.status == 401


def test_a_permission_error_from_the_key_lookup_is_not_swallowed():
    # [왜] MissingUser는 PermissionError(OSError의 하위)다. 키 받기 오류를 잡는 except가 넓어지면 삼켜진다

    def broken(raw):
        raise PermissionError("not a fetch error")

    with pytest.raises(PermissionError):
        user_from_header(f"Bearer {token()}", supabase_verifier(SETTINGS, signing_key=broken))


def test_the_server_refuses_to_start_with_a_plain_http_supabase_url(monkeypatch):
    for name in (
        "K_SERVICE",
        "LANGSMITH_TRACING",
        "LANGSMITH_TRACING_V2",
        "LANGCHAIN_TRACING",
        "LANGCHAIN_TRACING_V2",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="https"):
        check_startup(Settings(_env_file=None, supabase_url="http://demo.supabase.test", owner_ids="owner-1"))


def test_a_signed_token_without_sub_is_401():
    with pytest.raises(AuthError) as refused:
        user_from_header(f"Bearer {token(sub=None)}", VERIFY)
    assert refused.value.status == 401


def test_every_name_in_the_comma_separated_owner_list_gets_in():
    # [왜] SETTINGS의 소유자 목록은 "owner-1, owner-2"(쉼표 뒤 공백)다
    assert user_from_header(f"Bearer {token(sub='owner-2')}", VERIFY) == "owner-2"


def test_the_key_list_path_asks_the_supabase_url_and_picks_the_key_by_kid(monkeypatch):
    jwk = jwt.algorithms.ECAlgorithm.to_jwk(KEY.public_key(), as_dict=True) | {"kid": "k1", "use": "sig"}
    asked = over_the_wire(monkeypatch, json.dumps({"keys": [jwk]}).encode())
    verify = supabase_verifier(SETTINGS)
    assert user_from_header(f"Bearer {token(headers={'kid': 'k1'})}", verify) == "owner-1"
    assert asked[0][0] == f"{BASE}/auth/v1/.well-known/jwks.json"
    with pytest.raises(AuthError) as refused:
        user_from_header(f"Bearer {token(headers={'kid': 'unknown'})}", verify)
    assert refused.value.status == 401
