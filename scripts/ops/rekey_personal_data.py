"""개인정보를 B/L 열쇠에서 PII 열쇠로 옮긴다 (열쇠 분리, docs/specs/user-profile.md).

회원 정보(user_profiles)와 운영자 이메일(operators, operator_audit, admin_actions)은 처음에 BL_ENCRYPTION_KEY로
잠갔다. 이 스크립트가 옛 열쇠로 풀어 PII_ENCRYPTION_KEY로 다시 잠그고, 운영자 지문(email_hash)도 새 열쇠로 다시 만든다.
한 트랜잭션이다. 하나라도 못 풀거나 못 잠그면 전부 되돌린다. 이미 새 열쇠로 잠긴 값은 건너뛴다(다시 돌려도 안전).

    python -m scripts.ops.rekey_personal_data

두 열쇠가 모두 .env에 있어야 한다. 같은 DB를 쓰는 팀원도 PII_ENCRYPTION_KEY를 같은 값으로 받아야 회원 정보를 읽는다.
"""
from __future__ import annotations

import sys

from dotenv import load_dotenv

from backend.app import crypto
from backend.app.db import apply_migrations, connect


def _move(token: str | None) -> tuple[str | None, str | None]:
    """(새 암호문, 원문). 이미 새 열쇠면 그대로. 옛 열쇠로도 못 풀면 RuntimeError로 전체를 되돌린다."""
    if not token:
        return None, None
    plain = crypto.decrypt_pii(token)
    if plain is not None:
        return token, plain
    plain = crypto.decrypt(token)  # 옛 열쇠 (BL_ENCRYPTION_KEY)
    if plain is None:
        raise RuntimeError("어느 열쇠로도 풀리지 않는 값이 있습니다. 아무것도 바꾸지 않았습니다")
    new = crypto.encrypt_pii(plain)
    if new is None:
        raise RuntimeError("PII_ENCRYPTION_KEY가 없습니다. 아무것도 바꾸지 않았습니다")
    return new, plain


def main() -> int:
    load_dotenv(".env")
    if crypto.encrypt_pii("x") is None or crypto.encrypt("x") is None:
        print("BL_ENCRYPTION_KEY와 PII_ENCRYPTION_KEY가 모두 필요합니다")
        return 1
    counts = {"user_profiles": 0, "operators": 0, "operator_audit": 0, "admin_actions": 0}
    with connect() as conn:
        apply_migrations(conn)
        with conn.transaction():
            for uid, *cols in conn.execute("SELECT user_id, name_enc, phone_enc, address_enc FROM user_profiles").fetchall():
                new = [_move(c)[0] for c in cols]
                if new != cols:
                    conn.execute("UPDATE user_profiles SET name_enc = %s, phone_enc = %s, address_enc = %s WHERE user_id = %s",
                                 [*new, uid])
                    counts["user_profiles"] += 1
            for old_hash, enc in conn.execute("SELECT email_hash, email_enc FROM operators").fetchall():
                new_enc, email = _move(enc)
                new_hash = crypto.fingerprint(email) if email else old_hash
                if (new_enc, new_hash) != (enc, old_hash):
                    conn.execute("UPDATE operators SET email_enc = %s, email_hash = %s WHERE email_hash = %s",
                                 [new_enc, new_hash, old_hash])
                    counts["operators"] += 1
            for rid, t, a in conn.execute("SELECT id, target_email_enc, actor_email_enc FROM operator_audit").fetchall():
                nt, na = _move(t)[0], _move(a)[0]
                if (nt, na) != (t, a):
                    conn.execute("UPDATE operator_audit SET target_email_enc = %s, actor_email_enc = %s WHERE id = %s", [nt, na, rid])
                    counts["operator_audit"] += 1
            for rid, a in conn.execute("SELECT id, actor_email_enc FROM admin_actions").fetchall():
                na = _move(a)[0]
                if na != a:
                    conn.execute("UPDATE admin_actions SET actor_email_enc = %s WHERE id = %s", [na, rid])
                    counts["admin_actions"] += 1
    print("새 열쇠로 옮긴 줄:", counts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
