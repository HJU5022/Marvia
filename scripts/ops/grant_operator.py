"""최초 운영자 등록 (docs/specs/operator-admin.md Happy Path 1).

운영자만 운영자를 등록할 수 있어서 첫 사람은 화면 밖에서 넣는다. 이력(operator_audit)에 등록자는 'bootstrap'으로 남는다.
두 번째부터는 관리 화면에서 등록한다.

    python -m scripts.ops.grant_operator someone@example.com
    docker compose exec api python -m scripts.ops.grant_operator someone@example.com

DATABASE_URL을 .env에서 읽는다. 마이그레이션(009)을 먼저 적용하므로 서버를 한 번도 안 띄웠어도 된다.
"""
from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from backend.app.db import apply_migrations, connect
from backend.app.services.account import operators as ops


def main() -> int:
    load_dotenv()  # 이미 있는 환경변수는 덮지 않는다
    parser = argparse.ArgumentParser(description="최초 운영자 등록")
    parser.add_argument("email", help="운영자로 등록할 구글 로그인 이메일")
    args = parser.parse_args()
    try:
        with connect() as conn:
            apply_migrations(conn)
            ops.grant(conn, args.email, ops.BOOTSTRAP_ACTOR, None)
    except ops.OperatorError as e:
        print({"invalid_email": "이메일 형식이 아닙니다", "already": "이미 운영자입니다"}.get(e.kind, e.kind))
        return 1
    except KeyError:
        print("DATABASE_URL이 없습니다. .env를 확인하세요")
        return 1
    print(f"운영자로 등록했습니다: {ops.mask_email(ops.normalize_email(args.email))} (이력: bootstrap)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
