"""운영자 권한, 등록·해지 이력, 고객 목록 마스킹 (docs/specs/operator-admin.md).

라우터(routers/admin.py)는 창구만 하고, 무엇을 어떤 규칙으로 하는지는 여기 있다.
- 운영자인지: 서명 확인한 출입증의 email을 operators 표와 대조한다 (화면 값은 믿지 않는다)
- 등록·해지: operators의 지금 상태를 바꾸고 operator_audit에 한 줄 쌓는다. 같은 연결의 한 트랜잭션으로 묶는다
- 고객 목록: Supabase 관리자 API에서 받아 이메일·이름을 가려서 돌려준다. 원문은 응답에 넣지 않는다
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from backend.app.db import connect

BOOTSTRAP_ACTOR = "bootstrap"  # 스크립트로 넣은 최초 운영자의 등록자 (scripts/grant_operator.py)
AUDIT_LIMIT = 100  # 관리 화면에 보여 줄 이력 수. 오래된 것은 DB에 남고 화면에만 안 나온다

# 흔한 이메일 모양만 받는다. 정확한 RFC 검사는 하지 않는다. 오타(공백, @ 없음)를 막는 게 목적이다
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class OperatorError(Exception):
    """등록·해지를 할 수 없다. kind: invalid_email / already / not_found / self_revoke."""

    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


def normalize_email(email: str) -> str:
    """앞뒤 공백을 빼고 소문자로. 형식이 아니면 OperatorError(invalid_email). 009의 CHECK(email = lower(email))와 맞춘다."""
    value = (email or "").strip().lower()
    if not _EMAIL.match(value):
        raise OperatorError("invalid_email")
    return value


def mask_email(email: str | None) -> str | None:
    """ka***@g***.com 모양으로 가린다 (Spec "마스킹"). 앞 2자, 도메인 첫 글자, 최상위 도메인만 남긴다.
    짧은 아이디(1~2자)는 첫 글자만 남겨 원문이 그대로 보이지 않게 한다."""
    if not email or "@" not in email:
        return None
    local, _, domain = email.partition("@")
    keep = local[:2] if len(local) > 2 else local[:1]
    host, dot, tld = domain.rpartition(".")
    masked_domain = f"{host[:1]}***{dot}{tld}" if dot else f"{domain[:1]}***"
    return f"{keep}***@{masked_domain}"


def mask_name(name: str | None) -> str | None:
    """첫 글자만 남기고 나머지는 *로. 김승욱 -> 김**, Alex Kim -> A*******."""
    if not name or not name.strip():
        return None
    name = name.strip()
    return name[0] + "*" * (len(name) - 1)


def is_operator(conn, email: str | None) -> bool:
    """지금 활성 운영자인가. 이메일이 없으면(출입증에 없음) 운영자가 아니다."""
    if not email:
        return False
    row = conn.execute("SELECT 1 FROM operators WHERE email = %s AND revoked_at IS NULL", [email.lower()]).fetchone()
    return row is not None


def active_operator_emails(conn) -> set[str]:
    """활성 운영자 이메일 전부. 고객 목록에 운영자 표시를 붙일 때 쓴다."""
    return {r[0] for r in conn.execute("SELECT email FROM operators WHERE revoked_at IS NULL").fetchall()}


def grant(conn, email: str, actor_user_id: str, actor_email: str | None) -> None:
    """운영자로 등록한다. 이미 활성이면 OperatorError(already), 이력은 남기지 않는다 (Spec EC-03).
    해지됐던 사람이면 같은 줄을 다시 활성으로 돌리고 이력은 한 줄 더 쌓는다 (EC-05)."""
    target = normalize_email(email)
    with conn.transaction():
        row = conn.execute("SELECT revoked_at FROM operators WHERE email = %s FOR UPDATE", [target]).fetchone()
        if row is not None and row[0] is None:
            raise OperatorError("already")
        conn.execute(
            """
            INSERT INTO operators (email, granted_by, granted_at, revoked_by, revoked_at)
            VALUES (%s, %s, now(), NULL, NULL)
            ON CONFLICT (email) DO UPDATE SET granted_by = EXCLUDED.granted_by, granted_at = now(),
                                              revoked_by = NULL, revoked_at = NULL
            """,
            [target, actor_user_id],
        )
        _audit(conn, "grant", target, actor_user_id, actor_email)


def revoke(conn, email: str, actor_user_id: str, actor_email: str | None) -> None:
    """운영자를 해지한다. 자기 자신은 못 한다(EC-04: 마지막 운영자가 사라지는 것을 막는다). 활성 운영자가 아니면 not_found."""
    target = normalize_email(email)
    if actor_email and target == actor_email.lower():
        raise OperatorError("self_revoke")
    with conn.transaction():
        updated = conn.execute(
            "UPDATE operators SET revoked_by = %s, revoked_at = now() WHERE email = %s AND revoked_at IS NULL",
            [actor_user_id, target],
        ).rowcount
        if not updated:
            raise OperatorError("not_found")
        _audit(conn, "revoke", target, actor_user_id, actor_email)


def _audit(conn, action: str, target_email: str, actor_user_id: str, actor_email: str | None) -> None:
    """이력 한 줄. INSERT만 한다. 이 표를 고치거나 지우는 함수는 두지 않는다 (Spec "이력은 쌓기만")."""
    conn.execute(
        "INSERT INTO operator_audit (action, target_email, actor_user_id, actor_email) VALUES (%s, %s, %s, %s)",
        [action, target_email, actor_user_id, actor_email],
    )


def list_operators(conn) -> list[dict]:
    """활성 운영자. 운영자끼리는 누가 권한을 가졌는지 알아야 하므로 이메일 원문을 보여 준다 (Spec "마스킹")."""
    rows = conn.execute(
        "SELECT email, granted_by, granted_at FROM operators WHERE revoked_at IS NULL ORDER BY granted_at"
    ).fetchall()
    return [{"email": r[0], "granted_by": r[1], "granted_at": r[2]} for r in rows]


def list_audit(conn, limit: int = AUDIT_LIMIT) -> list[dict]:
    """등록·해지 이력, 최신순."""
    rows = conn.execute(
        "SELECT action, target_email, actor_user_id, actor_email, created_at FROM operator_audit "
        "ORDER BY created_at DESC, id DESC LIMIT %s",
        [limit],
    ).fetchall()
    return [{"action": r[0], "target_email": r[1], "actor_user_id": r[2], "actor_email": r[3], "created_at": r[4]}
            for r in rows]


@dataclass(frozen=True)
class Customer:
    """고객 목록 한 줄. 원문 이메일·이름은 담지 않는다."""

    user_id: str
    email_masked: str | None
    name_masked: str | None
    created_at: str | None
    last_sign_in_at: str | None
    is_operator: bool


def mask_customers(users: list[dict], operator_emails: set[str]) -> list[Customer]:
    """Supabase 관리자 API의 사용자 목록을 가려서 옮긴다. 운영자 여부는 원문 이메일로 대조한 뒤 원문은 버린다."""
    out = []
    for u in users:
        email = (u.get("email") or "").lower() or None
        meta = u.get("user_metadata") or {}
        out.append(Customer(
            user_id=u.get("id", ""),
            email_masked=mask_email(email),
            name_masked=mask_name(meta.get("full_name") or meta.get("name")),
            created_at=u.get("created_at"),
            last_sign_in_at=u.get("last_sign_in_at"),
            is_operator=bool(email and email in operator_emails),
        ))
    # 최근 가입이 위로. 가입일 없는 줄은 아래로
    return sorted(out, key=lambda c: c.created_at or "", reverse=True)


def open_conn():
    """라우터·스크립트가 쓰는 연결. 테스트는 이 함수를 가짜로 바꿔 끼운다."""
    return connect()
