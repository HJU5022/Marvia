"""운영자·이력의 평문 이메일을 지문·암호문·가린 값으로 옮기고 평문을 비운다 (013, docs/specs/operator-admin.md).

마이그레이션(SQL)은 열쇠로 잠글 수 없어서 기존 행은 이 스크립트가 옮긴다. 새 행은 코드가 처음부터 평문을 쓰지 않는다.
한 트랜잭션이다. 하나라도 잠그지 못하면(열쇠 없음) 전부 되돌린다. 다시 돌려도 평문이 남은 행만 건드린다.

    python -m scripts.ops.encrypt_operator_emails

operator_audit·admin_actions는 INSERT만 하는 이력이지만, 평문을 지우는 이 이전 한 번만 기존 줄을 고친다 (Spec에 기록).
"""
from __future__ import annotations

import sys

from dotenv import load_dotenv

from backend.app import crypto
from backend.app.db import apply_migrations, connect
from backend.app.services.account import operators as ops


def _sealed(email: str) -> tuple[str, str, str]:
    """(지문, 암호문, 가린 값). 열쇠가 없으면 RuntimeError로 전체를 되돌린다."""
    h, enc = crypto.fingerprint(email), crypto.encrypt(email)
    if not h or not enc:
        raise RuntimeError("BL_ENCRYPTION_KEY가 없어 잠글 수 없습니다. 아무것도 바꾸지 않았습니다")
    return h, enc, ops.mask_email(email)


def main() -> int:
    load_dotenv(".env")
    with connect() as conn:
        apply_migrations(conn)
        # 018_db_cleanup이 평문 이메일 칸(operators.email 등)을 지웠다. 그 뒤에는 옮길 평문이 없고 아래 SQL이 칸을 못 찾아 실패한다.
        # 칸이 없으면 이미 끝난 이전이라 알리고 끝낸다
        if not conn.execute("SELECT 1 FROM information_schema.columns WHERE table_name = 'operators' AND column_name = 'email'").fetchone():
            print("018 이후라 평문 이메일 칸이 없습니다. 옮길 것이 없습니다")
            return 0
        with conn.transaction():
            moved = {"operators": 0, "operator_audit": 0, "admin_actions": 0}
            for (email,) in conn.execute("SELECT email FROM operators WHERE email IS NOT NULL").fetchall():
                h, enc, masked = _sealed(email.lower())
                conn.execute("UPDATE operators SET email_hash = %s, email_enc = %s, email_masked = %s, email = NULL WHERE email = %s",
                             [h, enc, masked, email])
                moved["operators"] += 1
            for rid, target, actor in conn.execute(
                    "SELECT id, target_email, actor_email FROM operator_audit WHERE target_email IS NOT NULL OR actor_email IS NOT NULL").fetchall():
                t = _sealed(target) if target else (None, None, None)
                a = _sealed(actor) if actor else (None, None, None)
                conn.execute(
                    "UPDATE operator_audit SET target_email_enc = %s, target_email_masked = %s, actor_email_enc = %s, "
                    "actor_email_masked = %s, target_email = NULL, actor_email = NULL WHERE id = %s",
                    [t[1], t[2], a[1], a[2], rid])
                moved["operator_audit"] += 1
            for rid, actor in conn.execute("SELECT id, actor_email FROM admin_actions WHERE actor_email IS NOT NULL").fetchall():
                _, enc, masked = _sealed(actor)
                conn.execute("UPDATE admin_actions SET actor_email_enc = %s, actor_email_masked = %s, actor_email = NULL WHERE id = %s",
                             [enc, masked, rid])
                moved["admin_actions"] += 1
        left = {t: conn.execute(f"SELECT count(*) FROM {t} WHERE {c}").fetchone()[0] for t, c in [
            ("operators", "email IS NOT NULL"),
            ("operator_audit", "target_email IS NOT NULL OR actor_email IS NOT NULL"),
            ("admin_actions", "actor_email IS NOT NULL")]}
    print("옮긴 줄:", moved)
    print("평문이 남은 줄:", left)
    return 0 if not any(left.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
