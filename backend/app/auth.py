"""로그인 출입증(JWT) 확인 (작업 G3 로그인).

구글 로그인은 Supabase Auth가 하고, 화면은 받은 출입증을 Authorization: Bearer <JWT>로 보낸다.
여기서는 서명·만료·발급처·대상만 확인하고 사용자 ID(sub)를 꺼낸다. 백엔드는 구글과 직접 통신하지 않는다.

서명 확인은 공개키 방식(ES256)이다. Supabase가 공개한 견본(JWKS)과 대조하므로
우리 .env에 JWT_SECRET 같은 비밀값을 두지 않는다. 필요한 설정은 SUPABASE_URL(비밀 아님) 하나다.
실제 JWKS를 읽어 ES256 공개키 1개를 확인했다. 서명 계산은 직접 짜지 않고 PyJWT에 맡긴다 (Supabase 문서 권고).

로그인은 필수다. 손님으로 쓰는 길은 없다. 세 갈래로 나뉜다:
- SUPABASE_URL 없음 → None(로그인 기능 자체가 꺼짐). 채점용 compose는 Supabase가 없어 이 길로 데모가 돈다.
  이때만 예전처럼 session_id로 구분한다
- 로그인 켜짐 + 헤더 없음 → 401. 메모리·등록·알림이 전부 사람에 묶이는 기능이라 주인 없는 기록을 만들지 않는다
- 헤더가 있는데 가짜·만료·다른 발급처 → 401
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Header, HTTPException

from backend.app.observability.logging import log_failure, request_user_var

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
    return verify_claims(token, base_url)["sub"]


def verify_claims(token: str, base_url: str) -> dict:
    """출입증을 확인하고 클레임 전체를 돌려준다. 운영자 판단에 email이 필요해서 따로 뺐다 (docs/specs/operator-admin.md).
    서명을 확인한 뒤의 값이라 화면이 보낸 값과 달리 믿을 수 있다."""
    return jwt.decode(
        token,
        _signing_key(token, base_url),
        algorithms=ALGORITHMS,
        audience=AUDIENCE,
        issuer=f"{base_url}/auth/v1",  # 다른 Supabase 프로젝트에서 받은 출입증을 막는다
        options={"require": ["exp", "sub", "iss", "aud"]},
    )


def current_user_id(authorization: str | None = Header(default=None)) -> str | None:
    """라우터가 Depends로 쓰는 입구. 사용자 ID를 돌려준다. 로그인 기능이 꺼져 있을 때만 None."""
    user = current_user(authorization)
    return user.id if user else None


@dataclass(frozen=True)
class CurrentUser:
    """로그인한 사람. email은 구글 로그인이면 항상 있지만, 출입증에 없으면 None이다."""

    id: str
    email: str | None


def current_user(authorization: str | None = Header(default=None)) -> CurrentUser | None:
    """사용자 ID와 이메일을 같이 돌려준다. 운영자 판단용 (routers/admin.py). 오류 처리는 current_user_id와 같다."""
    base_url = supabase_url()
    if not base_url:
        return None
    if not authorization:
        log_failure("auth", "missing")
        raise HTTPException(status_code=401, detail="로그인이 필요합니다",
                            headers={"WWW-Authenticate": "Bearer"})

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        log_failure("auth", "bad_scheme")
        raise _unauthorized()
    try:
        claims = verify_claims(token.strip(), base_url)
        user = CurrentUser(id=claims["sub"], email=verified_email(claims))
    except jwt.PyJWKClientConnectionError:
        # 공개키를 못 받은 것은 사용자 잘못이 아니다. 401을 주면 다시 로그인해도 안 풀린다
        log_failure("auth", "jwks_unreachable")
        raise HTTPException(status_code=503, detail="로그인 확인 서버에 연결하지 못했습니다. 잠시 뒤 다시 시도하세요")
    except jwt.PyJWTError as e:
        # 오류 종류만 남긴다. 출입증 원문은 로그에 넣지 않는다
        log_failure("auth", type(e).__name__)
        raise _unauthorized()
    if _suspended(user.id):
        log_failure("auth", "suspended")
        raise HTTPException(status_code=403, detail=SUSPENDED)
    # 하루 토큰 한도의 운영자 예외가 이 이메일을 본다 (services/account/quota.py). 서명을 확인한 값만 적는다.
    # 로그인 확인은 스레드풀에서 돌아 새 대입은 핸들러로 안 넘어가고, 미들웨어가 만든 dict를 고치면 넘어간다
    holder = request_user_var.get()
    if holder is not None:
        holder["email"] = user.email
    return user


def verified_email(claims: dict) -> str | None:
    """출입증의 이메일. 확인되지 않은 이메일이면 None.

    운영자 판단(services/account/operators.is_operator)과 토큰 한도 운영자 예외(services/account/quota.is_exempt)가 이 이메일을 본다.
    확인 안 된 이메일을 믿으면, 이메일 확인을 끈 가입 경로로 운영자 주소를 등록한 사람이 운영자가 된다.
    Supabase 출입증은 email_verified를 맨 위나 user_metadata 안에 둔다(구글 로그인은 user_metadata.email_verified=true).
    둘 중 하나라도 있으면 true일 때만 이메일을 쓴다. 둘 다 없으면 예전처럼 쓴다(그런 출입증을 주는 로그인 경로가 지금 없다).
    user_metadata는 사용자가 고칠 수 있는 칸이라 이 검사는 "확인 안 됨"을 걸러 내는 데만 의미가 있다.
    """
    email = claims.get("email")
    if not isinstance(email, str) or not email.strip():
        return None
    metadata = claims.get("user_metadata") if isinstance(claims.get("user_metadata"), dict) else {}
    for flag in (claims.get("email_verified"), metadata.get("email_verified")):
        if flag is not None and flag is not True:
            return None
    return email.strip().lower()


SUSPENDED = "account_suspended"  # 화면이 이 값으로 정지 안내를 띄운다 (lib/api.ts)


def _suspended(user_id: str) -> bool:
    """운영자가 정지한 계정인가 (docs/specs/operator-admin.md 일시 정지, 012).
    Supabase 차단은 새 로그인만 막고, 이미 받은 출입증은 기한(최대 1시간)까지 통과한다. 그래서 여기서 한 번 더 본다.
    DB가 없거나 못 읽으면 건너뛴다. 서비스 전체를 멈추지 않으려는 것이고, Supabase 차단은 그대로 유효하다."""
    if not os.environ.get("DATABASE_URL"):
        return False
    try:
        # 함수 안에서 불러온다. 순환 import를 피하고, 테스트는 operators.open_conn을 가짜로 바꿔 끼운다
        from backend.app.services.account.customers import is_suspended
        from backend.app.services.account.operators import open_conn
        with open_conn() as conn:
            return is_suspended(conn, user_id)
    except Exception as e:
        log_failure("suspension_check", type(e).__name__)
        return False


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="로그인이 만료되었거나 올바르지 않습니다. 다시 로그인하세요",
        headers={"WWW-Authenticate": "Bearer"},
    )
