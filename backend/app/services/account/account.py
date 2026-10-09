"""회원 탈퇴 업무 규칙 (삭제 3단계, 개인정보보호법 제37조 동의 철회 → 지체 없이 파기).

라우터(routers/account.py)는 로그인 확인과 HTTP 응답만 하고, 무엇을 어떤 순서로 지우는지는 여기서 정한다
(CLAUDE.md 폴더 책임: 라우터는 요청 검증·서비스 호출·응답, 로직은 services).

순서가 중요하다: 우리 조회 기록과 회원 정보를 먼저 지우고, 그다음 Supabase 계정을 지운다.
두 곳은 창구가 다르다. 기록은 DATABASE_URL로 DB에 바로, 계정은 Supabase 로그인 서버(Auth)에 인터넷 요청으로 지운다.
그래서 한 번에 같이 처리되지 않고, 중간에 한쪽만 실패할 수 있다 (연결 끊김, Auth 점검, 관리자 키 삭제 등).
  - 계정을 먼저 지웠는데 기록 삭제가 실패하면, 그 사람은 로그인을 못 해 다시 탈퇴할 수도 없고 기록만 주인 없이 남는다
  - 기록을 먼저 지우면, 계정 삭제가 실패해도 아직 로그인된 상태라 탈퇴를 다시 누를 수 있다
    (다시 누르면 기록 0건 + 계정 삭제로 끝난다)
기록 삭제는 "내 기록 삭제"(routers/history.py)와 같은 db.delete_user_queries를 쓴다.
화물 비서 기억(화물 표·메모장)과 대화 목록도 같은 단계에서 지운다 (docs/specs/memory.md "개인정보", memory.forget_user, conversations.delete_all).

한계: 탈퇴 직후에도 이미 받은 출입증은 남은 기한(보통 1시간) 동안 우리 확인기(auth.py)를 통과한다.
출입증에 기한이 적혀 있을 뿐 계정이 지워졌는지는 Supabase에 따로 묻지 않기 때문이다. 화면이 탈퇴 직후 로그아웃시킨다.
"""
from __future__ import annotations

import os

from backend.app.clients.supabase_admin import AdminError, delete_account
from backend.app.db import atomic, connect, delete_user_queries
from backend.app.services.account import quota
from backend.app.services.chat.conversations import delete_all as delete_conversations
from backend.app.services.watch.kakao import delete as delete_kakao_link
from backend.app.services.account.memory import forget_user
from backend.app.services.account.profile import delete as delete_profile


class WithdrawError(Exception):
    """탈퇴를 끝내지 못했다. stage: 어느 단계에서(account_records 기록 / account_delete 계정), reason: 오류 종류만."""

    def __init__(self, stage: str, reason: str):
        super().__init__(f"{stage} {reason}")
        self.stage, self.reason = stage, reason


def withdraw(user_id: str) -> int:
    """기록을 지우고 계정을 지운다. 지운 기록 수를 돌려준다. 어느 단계든 실패하면 WithdrawError."""
    # 1) 우리 기록 먼저. 못 지우면 계정은 건드리지 않는다
    if not os.environ.get("DATABASE_URL"):
        raise WithdrawError("account_records", "not_configured")
    try:
        with connect() as conn, atomic(conn):  # 여러 표를 한 트랜잭션으로. 중간에 실패하면 하나도 안 지워진다
            deleted = delete_user_queries(conn, user_id)
            # 회원 정보(이름·전화·주소, 잠긴 글자)도 계정보다 먼저 지운다 (docs/specs/user-profile.md EC-08)
            delete_profile(conn, user_id)
            # 화물 표·메모장(잠긴 B/L 포함)도 계정보다 먼저 지운다 (docs/specs/memory.md "개인정보")
            forget_user(conn, user_id)
            # 대화 목록(잠긴 사용자 말·답)도 계정보다 먼저 지운다. 말풍선은 대화가 지워질 때 같이 지워진다 (migrations/018)
            delete_conversations(conn, user_id)
            # 카카오톡 알림 토큰도 계정보다 먼저 지운다. 줄만 지운다. 카카오 쪽 연결 해제는 부르지 않는다
            # (카카오 서버 실패가 탈퇴를 막으면 안 되고, 토큰이 사라지면 우리는 더 보낼 수 없다)
            delete_kakao_link(conn, user_id)
            # 하루 LLM 토큰 사용량 줄도 지운다 (migrations/016)
            quota.forget_user(conn, user_id)
    except Exception as e:  # 연결·SQL 실패 모두. 오류 종류만 남긴다
        raise WithdrawError("account_records", type(e).__name__) from None

    # 2) 계정. 실패해도 기록은 이미 지워졌다. 다시 부르면 이어서 끝난다
    try:
        delete_account(user_id)
    except AdminError as e:
        raise WithdrawError("account_delete", f"{e.kind} {e.code}" if e.code else e.kind) from None
    return deleted
