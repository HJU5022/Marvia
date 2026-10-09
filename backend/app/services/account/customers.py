"""운영자가 고객에게 하는 일: 수정, 강제 탈퇴, 마스킹 해제 (docs/specs/operator-admin.md 추가 절).

세 동작 모두 admin_actions에 한 줄 남긴다 (INSERT만).
- 마스킹 해제: 사유를 검사하고 먼저 기록한 뒤에 원문을 돌려준다. 기록이 실패하면 원문은 나가지 않는다
- 강제 탈퇴: 운영자 계정은 해지 먼저, 자기 자신은 안 됨. 지우는 순서는 본인 탈퇴(services/account/account.py)와 같다
- 수정: 검사 규칙은 본인 입력과 같다(services/account/profile.clean). 동의 시각은 바꾸지 않는다
"""
from __future__ import annotations

from backend.app.clients.supabase_admin import get_user, set_ban
from backend.app.services.account import operators as ops
from backend.app.services.account import profile as profile_svc
from backend.app.services.account.account import withdraw

REASON_MIN, REASON_MAX = 10, 500  # 사유서 길이 (Spec EC-09). 한 단어로 때우지 못하게 하한을 둔다
ACTION_LIMIT = 100  # 화면에 보여 줄 이력 수


class CustomerError(Exception):
    """kind: reason / not_found / is_operator / self / already_suspended / not_suspended."""

    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


def _record(conn, action: str, target_user_id: str, target_email: str | None, actor_id: str,
            actor_email: str | None, reason: str | None = None) -> None:
    """이력 한 줄. 대상은 가린 이메일로만 남긴다 (탈퇴 뒤에도 누구였는지 알아볼 정도만)."""
    # 처리한 운영자 이메일도 평문으로 두지 않는다 (013). 암호문 + 가린 값
    a_enc, a_masked = ops._seal(actor_email)
    conn.execute(
        "INSERT INTO admin_actions (action, target_user_id, target_email_masked, actor_user_id, actor_email_enc, "
        "actor_email_masked, reason) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        [action, target_user_id, ops.mask_email(target_email), actor_id, a_enc, a_masked, reason],
    )


def _user_or_404(user_id: str) -> dict:
    user = get_user(user_id)
    if not user:
        raise CustomerError("not_found")  # EC-10
    return user


def unmask(conn, user_id: str, actor_id: str, actor_email: str | None, reason: str) -> dict:
    """사유를 남기고 고객 한 명의 원문을 돌려준다. 사유가 짧으면 기록도 원문도 없다 (EC-09)."""
    reason = " ".join((reason or "").split())
    if not REASON_MIN <= len(reason) <= REASON_MAX:
        raise CustomerError("reason")
    user = _user_or_404(user_id)
    email = (user.get("email") or "").lower() or None
    _record(conn, "unmask", user_id, email, actor_id, actor_email, reason)  # 먼저 기록, 실패하면 여기서 예외
    p = profile_svc.load(conn, user_id)
    meta = user.get("user_metadata") or {}
    return {
        "email": email,
        "name": p.name if p else (meta.get("full_name") or meta.get("name")),
        "phone": profile_svc.format_phone(p.phone) if p else None,
        "address": p.address if p else None,
    }


def update(conn, user_id: str, actor_id: str, actor_email: str | None, name: str, phone: str, address: str) -> None:
    """운영자가 고객 정보를 고친다. 동의는 고객 본인이 한 것이라 검사에서는 동의를 있다고 보고 시각은 그대로 둔다."""
    user = _user_or_404(user_id)
    p = profile_svc.clean(name, phone, address, consent=True)
    with conn.transaction():
        profile_svc.save(conn, user_id, p, by_operator=True)
        _record(conn, "customer_update", user_id, user.get("email"), actor_id, actor_email)


def delete(conn, user_id: str, actor_id: str, actor_email: str | None) -> int:
    """강제 탈퇴. 지운 조회 기록 수를 돌려준다. 운영자 계정이면 해지 먼저 (EC-12), 자기 자신은 안 된다."""
    if user_id == actor_id:
        raise CustomerError("self")
    user = _user_or_404(user_id)
    email = (user.get("email") or "").lower() or None
    if ops.is_operator(conn, email):
        raise CustomerError("is_operator")
    deleted = withdraw(user_id)  # 기록 → 회원 정보 → 계정. 실패하면 WithdrawError (다시 누르면 이어서)
    conn.execute("DELETE FROM suspended_users WHERE user_id = %s", [user_id])  # 정지 중이었으면 함께 정리
    _record(conn, "customer_delete", user_id, email, actor_id, actor_email)
    return deleted


def list_actions(conn, limit: int = ACTION_LIMIT) -> list[dict]:
    """운영자 작업 이력, 최신순."""
    rows = conn.execute(
        "SELECT action, target_user_id, target_email_masked, actor_user_id, actor_email_enc, actor_email_masked, reason, "
        "created_at FROM admin_actions ORDER BY created_at DESC, id DESC LIMIT %s", [limit]).fetchall()
    return [{"action": r[0], "target_user_id": r[1], "target_email_masked": r[2], "actor_user_id": r[3],
             "actor_email": ops._open(r[4], r[5]), "reason": r[6], "created_at": r[7]} for r in rows]


# ── 일시 정지 (operator-admin "고객 계정 일시 정지") ──

def is_suspended(conn, user_id: str) -> bool:
    """지금 정지 중인가. auth.current_user가 요청마다 부른다."""
    return conn.execute("SELECT 1 FROM suspended_users WHERE user_id = %s", [user_id]).fetchone() is not None


def suspended_ids(conn) -> set[str]:
    """정지 중인 사람 전부. 고객 목록에 표시할 때."""
    return {r[0] for r in conn.execute("SELECT user_id FROM suspended_users").fetchall()}


def suspend(conn, user_id: str, actor_id: str, actor_email: str | None, reason: str) -> None:
    """정지. 사유 필수. 운영자·자기 자신 불가. Supabase 차단을 먼저 걸고(실패면 DB를 건드리지 않음) 우리 표와 이력에 남긴다."""
    reason = " ".join((reason or "").split())
    if not REASON_MIN <= len(reason) <= REASON_MAX:
        raise CustomerError("reason")
    if user_id == actor_id:
        raise CustomerError("self")
    user = _user_or_404(user_id)
    email = (user.get("email") or "").lower() or None
    if ops.is_operator(conn, email):
        raise CustomerError("is_operator")
    if is_suspended(conn, user_id):
        raise CustomerError("already_suspended")
    set_ban(user_id, True)
    with conn.transaction():
        conn.execute("INSERT INTO suspended_users (user_id, suspended_by, reason) VALUES (%s, %s, %s)",
                     [user_id, actor_id, reason])
        _record(conn, "customer_suspend", user_id, email, actor_id, actor_email, reason)


def resume(conn, user_id: str, actor_id: str, actor_email: str | None) -> None:
    """정지 해제. Supabase 차단을 먼저 풀고 우리 표에서 지운다."""
    if not is_suspended(conn, user_id):
        raise CustomerError("not_suspended")
    user = get_user(user_id)  # 이미 탈퇴한 계정이면 None. 그래도 우리 표는 정리한다
    if user:
        set_ban(user_id, False)
    with conn.transaction():
        conn.execute("DELETE FROM suspended_users WHERE user_id = %s", [user_id])
        _record(conn, "customer_resume", user_id, (user or {}).get("email"), actor_id, actor_email)
