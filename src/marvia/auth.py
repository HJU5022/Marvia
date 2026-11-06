"""화면 서버의 로그인 확인 (설계 10절 로그인, 12절 신뢰 경계, 계획 4b Task 4).

사용자 id는 서명을 확인한 토큰에서만 꺼낸다. 화면이 보낸 user_id·state는 받지 않는다.
- supabase(기본): Supabase Auth가 발급한 JWT를 공개키(JWKS, ES256)로 확인한다. aud·iss·exp·sub가 없으면
  거절하고, sub가 소유자 목록(MARVIA_OWNER_IDS)에 없으면 403이다. 우리 쪽에 JWT 비밀값을 두지 않는다.
- dev: 이 컴퓨터에서 화면을 돌려 볼 때만 쓰는 고정 토큰(MARVIA_DEV_TOKEN). 사용자는 DEV_USER 하나다.
시작 검사(check_startup)는 트레이싱 환경 변수(R-069)와 로그인 설정(https, 소유자, 개발 로그인)을 본다.
하지 않는 일: 로그인 화면·가입(Supabase가 한다), 토큰 발급. 가입 막기는 Supabase 설정에서 한다(배포 절차서).
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Callable
from typing import Any

import jwt

from marvia.config import Settings
from marvia.tools.rules import load_rules

DEV_USER = "dev-owner"
TRACING_VARS = (
    "LANGSMITH_TRACING_V2",
    "LANGCHAIN_TRACING_V2",
    "LANGSMITH_TRACING",
    "LANGCHAIN_TRACING",
)
Verify = Callable[[str], str]  # 토큰 → 사용자 id. 통과 못 하면 AuthError


class AuthError(Exception):
    """401·403으로 돌려줄 로그인 실패. 글에는 토큰·사유 원문을 넣지 않는다."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def owners(settings: Settings) -> set[str]:
    """MARVIA_OWNER_IDS(쉼표 구분)를 집합으로."""
    return {owner.strip() for owner in settings.owner_ids.split(",") if owner.strip()}


def check_startup(settings: Settings) -> None:
    """띄우기 전에 트레이싱 환경 변수(R-069)와 로그인 설정을 본다. 맞지 않으면 시작하지 않는다."""
    # [왜] langsmith는 이 환경 변수만으로 추적을 켜고 콜백 값(실제 번호 포함)을 scrub 없이 밖으로 보낸다
    #      (R-069). 트레이서 연결 작업이 scrub을 거치게 하기 전까지 켜진 채로는 뜨지 않는다.
    #      이름은 langsmith/utils.py의 tracing_is_enabled가 보는 것(접두어 LANGSMITH·LANGCHAIN의
    #      TRACING_V2, TRACING)이고 켜는 값은 "true"다
    for name in TRACING_VARS:
        if os.environ.get(name, "").strip().lower() == "true":
            raise RuntimeError(
                f"{name}=true라 트레이스가 켜집니다. 가림(scrub) 없이 밖으로 나가므로 시작하지 않습니다"
            )
    if settings.auth == "dev":
        # [왜] K_SERVICE는 Cloud Run이 넣는 환경 변수다. 개발 로그인이 운영에 켜진 채 배포되는 일을 막는다
        if os.environ.get("K_SERVICE"):
            raise RuntimeError("Cloud Run에서는 개발 로그인(MARVIA_AUTH=dev)으로 시작하지 않습니다")
        if not settings.dev_token.get_secret_value():
            raise RuntimeError("MARVIA_AUTH=dev인데 MARVIA_DEV_TOKEN이 비어 있습니다")
        return
    if not settings.supabase_url:
        raise RuntimeError("MARVIA_SUPABASE_URL이 없어 로그인을 확인할 수 없습니다")
    if not settings.supabase_url.startswith("https://"):
        raise RuntimeError("MARVIA_SUPABASE_URL은 https://로 시작해야 합니다(공개키를 평문으로 받지 않는다)")
    if not owners(settings):
        raise RuntimeError("MARVIA_OWNER_IDS가 비어 있습니다. 쓸 수 있는 사용자를 정해야 서버가 뜹니다")


def supabase_verifier(settings: Settings, signing_key: Callable[[str], Any] | None = None) -> Verify:
    """Supabase JWT 확인 함수. signing_key(토큰 → 공개키)를 주면 JWKS 대신 쓴다(시험은 네트워크 없이 돈다)."""
    base = settings.supabase_url.rstrip("/")
    allowed = owners(settings)
    cfg = load_rules("server")["auth"]
    if signing_key is None:
        # [왜] 공개키 목록은 한 번 받아 두고, 토큰의 kid가 목록에 없을 때만 다시 받는다(PyJWKClient 캐시)
        client = jwt.PyJWKClient(f"{base}/auth/v1/.well-known/jwks.json", timeout=cfg["jwks_timeout_s"])

        def from_jwks(token: str) -> Any:
            return client.get_signing_key_from_jwt(token).key

        key_of = from_jwks
    else:
        key_of = signing_key

    def verify(token: str) -> str:
        try:
            key = key_of(token)
        except (jwt.PyJWTError, ValueError, OSError) as error:
            # [주의] 공개키 받기 오류(JSON 아님, 연결 끊김)도 401이다. 사유 글은 넣지 않는다.
            #        MissingUser(PermissionError)가 이 길로 들어오면 안 되므로 키 받기 둘레만 잡는다
            if isinstance(error, PermissionError):
                raise
            raise AuthError(401, "로그인을 확인하지 못했어요") from None
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=cfg["algorithms"],
                audience=cfg["audience"],
                issuer=f"{base}/auth/v1",  # [왜] 다른 Supabase 프로젝트에서 받은 토큰을 막는다
                leeway=cfg["leeway_s"],
                options={"require": ["exp", "sub", "iss", "aud"]},
            )
        except jwt.PyJWTError:
            # [주의] 사유 원문(만료 시각, 기대한 발급처 등)은 응답에 넣지 않는다
            raise AuthError(401, "로그인을 확인하지 못했어요") from None
        if claims["sub"] not in allowed:
            raise AuthError(403, "이 서비스를 쓸 수 있는 계정이 아니에요")
        return claims["sub"]

    return verify


def dev_verifier(settings: Settings) -> Verify:
    """개발 로그인 확인 함수: 고정 토큰과 상수 시간으로 비교한다."""
    expected = settings.dev_token.get_secret_value().encode()

    def verify(token: str) -> str:
        if not expected or not hmac.compare_digest(token.encode(), expected):
            raise AuthError(401, "로그인을 확인하지 못했어요")
        return DEV_USER

    return verify


def verifier(settings: Settings) -> Verify:
    """설정에 맞는 확인 함수. 시작 검사를 먼저 한다."""
    check_startup(settings)
    return dev_verifier(settings) if settings.auth == "dev" else supabase_verifier(settings)


def user_from_header(header: str | None, verify: Verify) -> str:
    """Authorization 머리글("Bearer <토큰>")에서 사용자 id를 꺼낸다. 없거나 모양이 틀리면 401."""
    scheme, _, token = (header or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthError(401, "로그인이 필요해요")
    return verify(token.strip())
