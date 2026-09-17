"""로그인 확인. 요청 헤더의 토큰이 진짜인지 검사하고 user_id를 꺼낸다. (SDD 2절)

흐름:
  브라우저가 구글 로그인 → Supabase가 액세스 토큰(JWT) 발급 → 브라우저가 우리 API를 부를 때
  헤더 `Authorization: Bearer <토큰>` 을 붙임 → 이 파일이 토큰을 검사 → 통과하면 user_id 반환.

검사 방식 (결정 09-17, 원안 유지):
  Supabase가 토큰에 찍은 서명을 우리 서버가 SUPABASE_JWT_SECRET(같은 비밀값)으로 직접 대조한다.
  네트워크를 타지 않아 요청마다 Supabase에 물어볼 필요가 없다. 실무에서 가장 흔한 방식.
  비밀값은 Supabase 대시보드 > 프로젝트 설정 > API > JWT Secret.

쓰는 법:
  라우터 함수 인자에 `user_id: str = Depends(current_user)` 한 줄을 붙이면, FastAPI가 요청마다
  current_user를 먼저 실행하고 통과한 user_id만 함수에 넣어준다. 막히면 함수는 실행되지 않는다.
  /health 를 뺀 모든 엔드포인트에 붙인다 (결정 4).

이 파일은 DB를 건드리지 않는다. user_id를 받아 저장하는 건 services/store.py.
"""
from __future__ import annotations

import os

import jwt  # PyJWT
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# HTTPBearer: "Authorization: Bearer xxx" 헤더를 읽어 xxx만 꺼내 준다.
# auto_error=False → 헤더가 없어도 FastAPI가 알아서 403을 내지 않고 None을 준다.
# 우리는 아래에서 직접 401로 통일한다 (SDD 2절: "없거나 틀리면 401").
_bearer = HTTPBearer(auto_error=False)


def _secret() -> str:
    """SUPABASE_JWT_SECRET. 없으면 서버가 뜨자마자 실패하는 게 낫다 — 검사를 건너뛴 채 돌면 안 되므로."""
    return os.environ["SUPABASE_JWT_SECRET"]


def verify_token(token: str) -> str:
    """토큰 문자열 → user_id. 틀리면 jwt 예외를 그대로 낸다 (current_user가 401로 바꿈).

    검사하는 것 (PyJWT가 한 번에):
      - 서명이 비밀값과 맞는가 (위조 여부)
      - exp(만료 시각)가 지나지 않았는가 — Supabase 기본 1시간. 프론트 라이브러리가 만료 전에 자동 갱신한다
      - aud가 "authenticated"인가 — Supabase가 로그인 사용자 토큰에 넣는 값. 다른 용도 토큰 차단
    Supabase는 HS256으로 서명한다. 알고리즘을 고정해 두는 이유는 "alg: none" 같은 우회를 막기 위해서다.

    user_id는 토큰의 sub 필드. auth.users.id 와 같은 uuid. sessions.user_id 에 들어가는 값 (테이블정의서 1절).
    """
    payload = jwt.decode(
        token,
        _secret(),
        algorithms=["HS256"],
        audience="authenticated",
    )
    return payload["sub"]


async def current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """FastAPI 의존성. 라우터에서 `user_id: str = Depends(current_user)` 로 쓴다.

    실패는 전부 401 하나로 돌려준다. "토큰이 없다 / 만료됐다 / 위조다"를 구분해 알려주면
    공격자에게 힌트가 되므로 이유는 서버 로그에만 남기고 응답은 같게 한다.
    401을 내면 LLM 호출까지 가지 않는다 (결정 4, 비용 방어).
    """
    if cred is None or cred.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")
    try:
        return verify_token(cred.credentials)
    except jwt.PyJWTError:
        # ExpiredSignatureError, InvalidSignatureError, InvalidAudienceError 등 전부 여기로
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")
