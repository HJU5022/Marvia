"""테스트 고객 3명 만들기 (docs/specs/operator-admin.md 추가 절 "테스트 고객").

고객 관리 화면(수정·강제 탈퇴·마스킹 해제)을 실제 사람 없이 시험하려고 가공 계정을 만든다.
- Supabase 계정: testuser1~3@marvia.test (관리자 API, user_metadata.test=true, 비밀번호 없음)
- 회원 정보: 이름 testUser1~3, 가공 전화·주소. 실제 사람·번호·주소가 아니다. 서버와 같은 방식으로 암호화해 저장한다
- 다시 돌리면 이미 있는 계정은 건너뛰고, 회원 정보만 가공값으로 다시 맞춘다

    python -m scripts.ops.seed_test_users

.env의 SUPABASE_URL, SUPABASE_SECRET_KEY, DATABASE_URL, BL_ENCRYPTION_KEY가 필요하다.
"""
from __future__ import annotations

import sys

from dotenv import load_dotenv

from backend.app.clients.supabase_admin import AdminError, create_user, list_users
from backend.app.db import apply_migrations, connect
from backend.app.services.account import operators as ops
from backend.app.services.account import profile as profile_svc

# 가공값. 010-0000-000N은 실제로 쓰이지 않는 번호 꼴로 골랐다
TEST_USERS = [
    ("testuser1@marvia.test", "testUser1", "010-0000-0001", "서울특별시 테스트구 가공로 1"),
    ("testuser2@marvia.test", "testUser2", "010-0000-0002", "부산광역시 테스트구 가공로 2"),
    ("testuser3@marvia.test", "testUser3", "010-0000-0003", "인천광역시 테스트구 가공로 3"),
]


def main() -> int:
    load_dotenv(".env")
    try:
        existing = {(u.get("email") or "").lower(): u["id"] for u in list_users()}
    except AdminError as e:
        print(f"Supabase 관리자 API를 부르지 못했습니다: {e.kind} {e.code or ''}")
        return 1
    with connect() as conn:
        apply_migrations(conn)
        for email, name, phone, address in TEST_USERS:
            user_id = existing.get(email)
            if not user_id:
                user_id = create_user(email, name, {"test": True}).get("id")
                if not user_id:
                    print(f"{ops.mask_email(email)} 계정을 만들지 못했습니다")
                    return 1
                state = "계정 생성"
            else:
                state = "계정 있음"
            profile_svc.save(conn, user_id, profile_svc.clean(name, phone, address, consent=True))
            print(f"{name}: {state}, 회원 정보 저장 ({ops.mask_email(email)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
