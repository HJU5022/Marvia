"""로그인 출입증(JWT) 확인 (작업 G3 로그인).

구글 로그인은 Supabase Auth가 하고, 화면은 받은 출입증을 Authorization: Bearer <JWT>로 보낸다.
여기서는 서명·만료·발급처·대상만 확인하고 사용자 ID(sub)를 꺼낸다. 백엔드는 구글과 직접 통신하지 않는다.

서명 확인은 공개키 방식(ES256)이다 (09-30 결정). Supabase가 공개한 견본(JWKS)과 대조하므로
우리 .env에 JWT_SECRET 같은 비밀값을 두지 않는다. 필요한 설정은 SUPABASE_URL(비밀 아님) 하나다.
09-30 실제 JWKS를 읽어 ES256 공개키 1개를 확인했다. 서명 계산은 직접 짜지 않고 PyJWT에 맡긴다 (Supabase 문서 권고).

세 갈래로 나뉜다:
- 헤더 없음 → None(손님). 지금처럼 session_id로만 구분한다
- SUPABASE_URL 없음 → None(로그인 꺼짐). 채점용 compose·키 없는 데모가 그대로 돈다
- 헤더가 있는데 가짜·만료·다른 발급처 → 401. 조용히 손님으로 넘기면 로그인이 풀린 걸 사용자가 모른다
"""
from __future__ import annotations

import os
from functools import lru_cache

import jwt
from fastapi import Header, HTTPException

from backend.app.observability.logging import log_failure

# 이 알고리즘만 받는다. 목록을 열어 두면 헤더의 alg를 HS256·none으로 바꾼 위조 출입증이 통할 수 있다
ALGORITHMS = ["ES256"]
# Supabase가 로그인한 사용자에게 발급하는 출입증의 대상(aud) 값
AUDIENCE = "authenticated"


def supabase_url() -> str:
    """SUPABASE_URL을 끝 슬래시 없이 돌려준다. 비어 있으면 로그인이 꺼진 상태다."""
    return os.environ.get("SUPABASE_URL", "").strip().rstrip("/")


@lru_cache(maxsize=2)
def _jwks_client(base_url: str) -> jwt.PyJWKClient:
    """공개키 목록을 한 번 받아 두고 재사용한다. 요청마다 Supabase에 묻지 않는다.

    출입증의 kid가 목록에 없을 때만 다시 받는다 (Supabase가 키를 바꾼 경우).
    """
    return jwt.PyJWKClient(f"{base_url}/auth/v1/.well-known/jwks.json")


def _signing_key(token: str, base_url: str):
    """출입증 헤더의 kid에 맞는 공개키를 고른다. 테스트는 이 함수를 바꿔 끼워 네트워크 없이 돈다."""
    return _jwks_client(base_url).get_signing_key_from_jwt(token).key


def verify_token(token: str, base_url: str) -> str:
    """출입증을 확인하고 사용자 ID(sub)를 돌려준다. 통과 못 하면 jwt 예외가 난다."""
    claims = jwt.decode(
        token,
        _signing_key(token, base_url),
        algorithms=ALGORITHMS,
        audience=AUDIENCE,
        issuer=f"{base_url}/auth/v1",  # 다른 Supabase 프로젝트에서 받은 출입증을 막는다
        options={"require": ["exp", "sub", "iss", "aud"]},
    )
    return claims["sub"]


def current_user_id(authorization: str | None = Header(default=None)) -> str | None:
    """라우터가 Depends로 쓰는 입구. 로그인했으면 사용자 ID, 손님이면 None."""
    base_url = supabase_url()
    if not authorization or not base_url:
        return None

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        log_failure("auth", "bad_scheme")
        raise _unauthorized()
    try:
        return verify_token(token.strip(), base_url)
    except jwt.PyJWKClientConnectionError:
        # 공개키를 못 받은 것은 사용자 잘못이 아니다. 401을 주면 다시 로그인해도 안 풀린다
        log_failure("auth", "jwks_unreachable")
        raise HTTPException(status_code=503, detail="로그인 확인 서버에 연결하지 못했습니다. 잠시 뒤 다시 시도하세요")
    except jwt.PyJWTError as e:
        # 오류 종류만 남긴다. 출입증 원문은 로그에 넣지 않는다
        log_failure("auth", type(e).__name__)
        raise _unauthorized()


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="로그인이 만료되었거나 올바르지 않습니다. 다시 로그인하세요",
        headers={"WWW-Authenticate": "Bearer"},
    )
