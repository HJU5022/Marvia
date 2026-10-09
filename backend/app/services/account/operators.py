"""운영자 권한, 등록·해지 이력, 고객 목록 마스킹 (docs/specs/operator-admin.md).

라우터(routers/admin.py)는 창구만 하고, 무엇을 어떤 규칙으로 하는지는 여기 있다.
- 운영자인지: 서명 확인한 출입증의 email을 operators 표와 대조한다 (화면 값은 믿지 않는다)
- 등록·해지: operators의 지금 상태를 바꾸고 operator_audit에 한 줄 쌓는다. 같은 연결의 한 트랜잭션으로 묶는다
- 고객 목록: Supabase 관리자 API에서 받아 이메일·이름을 가려서 돌려준다. 원문은 응답에 넣지 않는다
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from backend.app import crypto
from backend.app.db import connect

BOOTSTRAP_ACTOR = "bootstrap"  # 스크립트로 넣은 최초 운영자의 등록자 (scripts/ops/grant_operator.py)
AUDIT_LIMIT = 100  # 관리 화면에 보여 줄 이력 수. 오래된 것은 DB에 남고 화면에만 안 나온다

# 흔한 이메일 모양만 받는다. 정확한 RFC 검사는 하지 않는다. 오타(공백, @ 없음)를 막는 게 목적이다
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class OperatorError(Exception):
    """등록·해지를 할 수 없다. kind: invalid_email / already / not_found / self_revoke / no_key."""

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
    """첫 글자만 남기고 나머지는 *로. 홍길동 -> 홍**, Alex Kim -> A*******."""
    if not name or not name.strip():
        return None
    name = name.strip()
    return name[0] + "*" * (len(name) - 1)


def _seal(email: str | None) -> tuple[str | None, str | None]:
    """이메일을 (암호문, 가린 값)으로. 평문은 DB에 넣지 않는다 (013). 열쇠가 없으면 암호문은 None."""
    if not email:
        return None, None
    return crypto.encrypt_pii(email), mask_email(email)  # PII 열쇠 (분리)


def _open(enc: str | None, masked: str | None) -> str | None:
    """화면용 이메일. 풀 수 있으면 원문, 열쇠가 바뀌었으면 가린 값."""
    return (crypto.decrypt_pii(enc) if enc else None) or masked


def _hash(email: str) -> str:
    """운영자 찾기용 지문. 열쇠가 없으면 OperatorError(no_key): 평문으로 대신 저장·비교하지 않는다."""
    h = crypto.fingerprint(email)
    if h is None:
        raise OperatorError("no_key")
    return h


def is_operator(conn, email: str | None) -> bool:
    """지금 활성 운영자인가. 출입증 이메일의 지문을 operators.email_hash와 비교한다 (013).
    이메일이 없거나 열쇠가 없으면 운영자가 아니다(닫힌 쪽으로 실패).
    email은 확인된 이메일만 와야 한다. auth.current_user가 email_verified가 false인 출입증의 이메일을 None으로 넘긴다
    (auth.verified_email). 그래서 확인 안 된 이메일은 여기서 None이 되어 운영자가 아니다."""
    if not email:
        return False
    h = crypto.fingerprint(email.lower())
    if h is None:
        return False
    row = conn.execute("SELECT 1 FROM operators WHERE email_hash = %s AND revoked_at IS NULL", [h]).fetchone()
    return row is not None


def active_operator_hashes(conn) -> set[str]:
    """활성 운영자 이메일 지문 전부. 고객 목록에 운영자 표시를 붙일 때 고객 이메일 지문과 대조한다."""
    return {r[0] for r in conn.execute("SELECT email_hash FROM operators WHERE revoked_at IS NULL").fetchall() if r[0]}


def grant(conn, email: str, actor_user_id: str, actor_email: str | None) -> None:
    """운영자로 등록한다. 이미 활성이면 OperatorError(already), 이력은 남기지 않는다 (Spec EC-03).
    해지됐던 사람이면 같은 줄을 다시 활성으로 돌리고 이력은 한 줄 더 쌓는다 (EC-05). 평문 이메일은 저장하지 않는다."""
    target = normalize_email(email)
    h = _hash(target)
    enc, masked = _seal(target)
    if enc is None:
        raise OperatorError("no_key")
    with conn.transaction():
        row = conn.execute("SELECT revoked_at FROM operators WHERE email_hash = %s FOR UPDATE", [h]).fetchone()
        if row is not None and row[0] is None:
            raise OperatorError("already")
        conn.execute(
            """
            INSERT INTO operators (email_hash, email_enc, email_masked, granted_by, granted_at, revoked_by, revoked_at)
            VALUES (%s, %s, %s, %s, now(), NULL, NULL)
            ON CONFLICT (email_hash) DO UPDATE SET email_enc = EXCLUDED.email_enc, email_masked = EXCLUDED.email_masked,
              granted_by = EXCLUDED.granted_by, granted_at = now(), revoked_by = NULL, revoked_at = NULL
            """,
            [h, enc, masked, actor_user_id],
        )
        _audit(conn, "grant", target, actor_user_id, actor_email)


def revoke(conn, email: str, actor_user_id: str, actor_email: str | None) -> None:
    """운영자를 해지한다. 자기 자신은 못 한다(EC-04: 마지막 운영자가 사라지는 것을 막는다). 활성 운영자가 아니면 not_found."""
    target = normalize_email(email)
    if actor_email and target == actor_email.lower():
        raise OperatorError("self_revoke")
    h = _hash(target)
    with conn.transaction():
        updated = conn.execute(
            "UPDATE operators SET revoked_by = %s, revoked_at = now() WHERE email_hash = %s AND revoked_at IS NULL",
            [actor_user_id, h],
        ).rowcount
        if not updated:
            raise OperatorError("not_found")
        _audit(conn, "revoke", target, actor_user_id, actor_email)


def _audit(conn, action: str, target_email: str, actor_user_id: str, actor_email: str | None) -> None:
    """이력 한 줄. INSERT만 한다 (Spec "이력은 쌓기만"). 이메일은 암호문과 가린 값으로만 (013)."""
    t_enc, t_masked = _seal(target_email)
    a_enc, a_masked = _seal(actor_email)
    conn.execute(
        "INSERT INTO operator_audit (action, actor_user_id, target_email_enc, target_email_masked, actor_email_enc, actor_email_masked) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        [action, actor_user_id, t_enc, t_masked, a_enc, a_masked],
    )


def list_operators(conn) -> list[dict]:
    """활성 운영자. 운영자끼리는 누가 권한을 가졌는지 알아야 하므로 풀어서 보여 준다.
    granted_by_email: 등록한 사람의 이메일. operator_audit의 최신 grant 줄에서 찾는다 (A5).
    암호문은 같은 값이어도 매번 달라 SQL로 못 맞추므로, 풀어낸 이메일끼리 여기서 맞춘다. 못 찾거나 스크립트 등록이면 None."""
    rows = conn.execute(
        "SELECT email_enc, email_masked, granted_by, granted_at FROM operators WHERE revoked_at IS NULL ORDER BY granted_at"
    ).fetchall()
    granter: dict[str, str | None] = {}
    for t_enc, t_masked, a_enc, a_masked in conn.execute(
        "SELECT target_email_enc, target_email_masked, actor_email_enc, actor_email_masked "
        "FROM operator_audit WHERE action = 'grant' ORDER BY created_at DESC, id DESC"
    ).fetchall():
        granter.setdefault(_open(t_enc, t_masked) or "", _open(a_enc, a_masked))  # 최신 줄이 먼저 오므로 첫 값만 둔다
    out = []
    for r in rows:
        email = _open(r[0], r[1]) or ""
        out.append({"email": email, "granted_by": r[2], "granted_at": r[3], "granted_by_email": granter.get(email)})
    return out


def list_audit(conn, limit: int = AUDIT_LIMIT) -> list[dict]:
    """등록·해지 이력, 최신순. 이메일은 풀어서 (열쇠가 바뀌었으면 가린 값)."""
    rows = conn.execute(
        "SELECT action, target_email_enc, target_email_masked, actor_user_id, actor_email_enc, actor_email_masked, created_at "
        "FROM operator_audit ORDER BY created_at DESC, id DESC LIMIT %s",
        [limit],
    ).fetchall()
    return [{"action": r[0], "target_email": _open(r[1], r[2]) or "", "actor_user_id": r[3],
             "actor_email": _open(r[4], r[5]), "created_at": r[6]} for r in rows]


@dataclass(frozen=True)
class Customer:
    """고객 목록 한 줄. 원문 이메일·이름은 담지 않는다."""

    user_id: str
    email_masked: str | None
    name_masked: str | None
    created_at: str | None
    last_sign_in_at: str | None
    is_operator: bool


def mask_customers(users: list[dict], operator_hashes: set[str]) -> list[Customer]:
    """Supabase 관리자 API의 사용자 목록을 가려서 옮긴다. 운영자 여부는 이메일 지문으로 대조한 뒤 원문은 버린다."""
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
            is_operator=bool(email and crypto.fingerprint(email) in operator_hashes),
        ))
    # 최근 가입이 위로. 가입일 없는 줄은 아래로
    return sorted(out, key=lambda c: c.created_at or "", reverse=True)


def open_conn():
    """라우터·스크립트가 쓰는 연결. 테스트는 이 함수를 가짜로 바꿔 끼운다."""
    return connect()
