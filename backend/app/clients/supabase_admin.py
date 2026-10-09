"""Supabase 관리자 API: 계정 삭제(삭제 3단계, 회원 탈퇴)와 고객 목록(운영자 관리, docs/specs/operator-admin.md).

구글 계정 연결 정보는 Supabase Auth가 갖고 있다. 사용자는 보안상 자기 계정을 스스로 못 지우므로
서버가 관리자 키로 대신 지운다 (결정 (가): 사용자가 늘면 사람이 일일이 지울 수 없다).

왜 이렇게 했나:
- 관리자 키는 새 방식 secret 키(sb_secret_..., 이름 marvia-api)다. 옛 service_role 키는 쓰지 않는다 (Supabase API keys 문서)
- 키는 apikey 헤더 하나로 보낸다. 읽기 전용 요청(회원 목록)으로 이 방식이 200인 것을 확인했다
- 가장 강한 키라 주소·로그에 넣지 않는다. httpx 요청 로그는 main에서 WARNING으로 꺼 두었다 (b3b1825)
- 외부 호출 규칙대로 타임아웃과 재시도(clients/retry.py)를 건다 (SDD 8절)
- 이미 없는 계정(404)은 성공으로 본다. 탈퇴를 두 번 눌러도 같은 결과여야 한다
"""
from __future__ import annotations

import os

import httpx

from backend.app.auth import supabase_url
from backend.app.clients.retry import with_retry

TIMEOUT_SEC = 10  # 계정 삭제는 가벼운 요청이다. ShipFinder 타임아웃(10초)과 맞춘다


class AdminError(Exception):
    """계정을 지우지 못했다. kind: not_configured(키·주소 없음) / failed(요청 실패)."""

    def __init__(self, kind: str, code: int | None = None):
        super().__init__(kind)
        self.kind, self.code = kind, code


def delete_account(user_id: str) -> None:
    """Supabase에서 이 사용자 계정을 지운다. 이미 없으면 그대로 끝낸다. 못 지우면 AdminError."""
    base, key = supabase_url(), os.environ.get("SUPABASE_SECRET_KEY", "").strip()
    if not base or not key:
        raise AdminError("not_configured")

    def call() -> httpx.Response:
        resp = httpx.delete(f"{base}/auth/v1/admin/users/{user_id}", headers={"apikey": key}, timeout=TIMEOUT_SEC)
        if resp.status_code != 404:  # 404 = 이미 없는 계정. 재시도하지 않고 성공으로 본다
            resp.raise_for_status()
        return resp

    try:
        with_retry(call, name="supabase:delete_user")
    except httpx.HTTPStatusError as e:
        raise AdminError("failed", e.response.status_code) from None
    except httpx.HTTPError:
        raise AdminError("failed") from None


# 고객 목록 한 페이지 크기. Supabase 관리자 API 최대값(1000)보다 작게, 화면 한 번에 다 보일 만큼 (docs/specs/operator-admin.md)
LIST_PER_PAGE = 200


def list_users(page: int = 1, per_page: int = LIST_PER_PAGE) -> list[dict]:
    """가입자 목록 한 페이지 (GET /auth/v1/admin/users). 원문 이메일이 들어 있으므로 부르는 쪽(services/account/operators.py)이
    가린 뒤에만 밖으로 낸다. 못 받으면 AdminError. 읽기라 재시도해도 안전하다."""
    base, key = supabase_url(), os.environ.get("SUPABASE_SECRET_KEY", "").strip()
    if not base or not key:
        raise AdminError("not_configured")

    def call() -> httpx.Response:
        resp = httpx.get(f"{base}/auth/v1/admin/users", params={"page": page, "per_page": per_page},
                         headers={"apikey": key}, timeout=TIMEOUT_SEC)
        resp.raise_for_status()
        return resp

    try:
        body = with_retry(call, name="supabase:list_users").json()
    except httpx.HTTPStatusError as e:
        raise AdminError("failed", e.response.status_code) from None
    except (httpx.HTTPError, ValueError):
        raise AdminError("failed") from None
    return body.get("users", []) if isinstance(body, dict) else []


def _admin_call(method: str, path: str, *, name: str, json: dict | None = None) -> httpx.Response | None:
    """관리자 API 한 번 (재시도 포함). 404면 None. 키가 없거나 실패하면 AdminError."""
    base, key = supabase_url(), os.environ.get("SUPABASE_SECRET_KEY", "").strip()
    if not base or not key:
        raise AdminError("not_configured")

    def call() -> httpx.Response:
        resp = httpx.request(method, f"{base}{path}", json=json, headers={"apikey": key}, timeout=TIMEOUT_SEC)
        if resp.status_code != 404:
            resp.raise_for_status()
        return resp

    try:
        resp = with_retry(call, name=name)
    except httpx.HTTPStatusError as e:
        raise AdminError("failed", e.response.status_code) from None
    except httpx.HTTPError:
        raise AdminError("failed") from None
    return None if resp.status_code == 404 else resp


def get_user(user_id: str) -> dict | None:
    """사용자 한 명 (GET /auth/v1/admin/users/{id}). 없으면 None. 원문 이메일이 들어 있다. 마스킹 해제·강제 탈퇴에서만 쓴다."""
    resp = _admin_call("GET", f"/auth/v1/admin/users/{user_id}", name="supabase:get_user")
    return resp.json() if resp is not None else None


def create_user(email: str, full_name: str, metadata: dict | None = None) -> dict:
    """확인된 계정을 만든다 (POST /auth/v1/admin/users). 테스트 고객 만들기(scripts/ops/seed_test_users.py)에서만 쓴다.
    비밀번호는 넣지 않는다. 그 계정으로 로그인할 일이 없는 가공 고객이다."""
    resp = _admin_call("POST", "/auth/v1/admin/users", name="supabase:create_user",
                       json={"email": email, "email_confirm": True, "user_metadata": {"full_name": full_name, **(metadata or {})}})
    return resp.json() if resp is not None else {}


# Supabase가 받는 기간 문자열. 정지는 사실상 무기한(100년), 해제는 "none" (Supabase Auth admin updateUserById ban_duration)
BAN_FOREVER, BAN_NONE = "876000h", "none"


def set_ban(user_id: str, banned: bool) -> None:
    """계정을 차단하거나 푼다 (PUT /auth/v1/admin/users/{id}). 차단되면 새 로그인과 출입증 갱신이 막힌다.
    없는 계정이면 AdminError(failed, 404). 고객 일시 정지(services/account/customers.py)에서만 쓴다."""
    resp = _admin_call("PUT", f"/auth/v1/admin/users/{user_id}", name="supabase:set_ban",
                       json={"ban_duration": BAN_FOREVER if banned else BAN_NONE})
    if resp is None:
        raise AdminError("failed", 404)
