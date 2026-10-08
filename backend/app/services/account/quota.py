"""1명당 하루 LLM 토큰 한도 (docs/specs/token-quota.md).

하는 일
- LLM을 한 번 부를 때마다 쓴 토큰(입력+출력)을 그 사람의 오늘 사용량에 더한다 (llm.chat이 add()를 부른다)
- 요청이 들어올 때 오늘 사용량이 한도 이상이면 429로 막는다 (라우터가 ensure_allowed()를 부른다)
- 요청을 처리하는 도중에 한도를 넘으면 그 요청은 끝까지 답한다. 다음 요청부터 막는다 (대화가 중간에 끊기지 않게)

사람 구분: 로그인했으면 user_id, 아니면 session_id. 하루는 한국 시각 자정에 바뀐다.
운영자는 막지 않는다. 사용량은 똑같이 쌓아 두되 확인에서 뺀다. 운영자 판단은 로그인 이메일로 한다.
한도는 환경변수 DAILY_TOKENS_PER_USER. 비어 있거나 0이면 막지 않는다 (키 없는 테스트·채점 환경).
저장: DATABASE_URL이 있으면 token_usage 표(016), 없으면 이 프로세스 메모리. 메모리는 서버를 다시 켜면 0으로 돌아간다.
"""
from __future__ import annotations

import os
import threading
from contextvars import ContextVar
from datetime import date, datetime
from zoneinfo import ZoneInfo

from backend.app.observability.logging import current_request_id, log_failure, request_user_var

KST = ZoneInfo("Asia/Seoul")
LIMIT_ENV = "DAILY_TOKENS_PER_USER"
# 남은 양이 한도의 이 비율 아래로 떨어지면 화면에 "얼마 안 남았다"고 미리 알린다
WARN_RATIO = 0.1

# 지금 요청이 누구 사용량으로 쌓이는지. observability/langfuse.session_scope가 정한다
owner_var: ContextVar[str | None] = ContextVar("quota_owner", default=None)
# 한 요청 안에서 한도 확인을 한 번만 한다. /api/chat이 안에서 run_agent를 또 불러도 두 번째는 건너뛴다.
# 확인한 요청 ID를 적어 둔다. 요청 ID가 없는 호출(스크립트·평가 실행기)이나 다른 요청은 다시 확인한다
checked_var: ContextVar[str] = ContextVar("quota_checked", default="")

_memory: dict[tuple[str, date], int] = {}
_lock = threading.Lock()
# 운영자 여부 캐시 {이메일: (운영자인가, 확인 시각)}. 요청마다 DB를 읽지 않게 잠깐 기억한다.
# 운영자를 해지해도 이 시간 동안은 예외가 남는다 (운영 화면 등록·해지와 같은 이유로 짧게 둔다)
OPERATOR_CACHE_SEC = 300
_operator_cache: dict[str, tuple[bool, float]] = {}


class QuotaExceeded(Exception):
    """오늘 한도를 다 썼다. 라우터가 429 daily_token_limit으로 바꾼다."""


def owner_key(session_id: str | None, user_id: str | None) -> str | None:
    """사용량을 쌓을 이름. 로그인 사용자는 user:, 아니면 session:을 앞에 붙여 둘이 섞이지 않게 한다."""
    if user_id:
        return f"user:{user_id}"
    return f"session:{session_id}" if session_id else None


def limit() -> int:
    """오늘 한도(토큰). 0이면 막지 않는다. 재생 모드도 0이다 (점검: 채점자가 키 없이 데모를 여러 번 돌리는데
    /api/agent 한 번이 약 1만 토큰이라 기본 한도 10만이면 열 번 남짓에 429가 난다)."""
    from backend.app.clients.replay import replay_enabled  # 재생 모드 판단은 한 곳에만 둔다

    if replay_enabled():
        return 0
    try:
        return max(0, int(os.environ.get(LIMIT_ENV, "0") or 0))
    except ValueError:
        return 0


def today() -> date:
    return datetime.now(KST).date()


def _db() -> bool:
    return bool(os.environ.get("DATABASE_URL"))


def used(owner: str, day: date | None = None) -> int:
    """그날 쓴 토큰. DB를 못 읽으면 메모리 값으로 대신한다 (막는 쪽보다 서비스가 도는 쪽을 택한다)."""
    day = day or today()
    if _db():
        try:
            from backend.app.db import connect

            with connect() as conn:
                row = conn.execute("SELECT tokens FROM token_usage WHERE owner = %s AND day = %s", [owner, day]).fetchone()
            return int(row[0]) if row else 0
        except Exception as e:  # noqa: BLE001 - 사용량을 못 읽어도 답은 나가야 한다
            log_failure("quota_read", type(e).__name__)
    with _lock:
        return _memory.get((owner, day), 0)


def add(tokens: int | None) -> None:
    """지금 요청의 사람 사용량에 토큰을 더한다. 사람을 모르거나(스크립트) 한도가 없으면 아무것도 안 한다."""
    owner = owner_var.get()
    if not owner or not tokens or not limit():
        return
    day = today()
    if _db():
        try:
            from backend.app.db import connect

            with connect() as conn:
                conn.execute(
                    "INSERT INTO token_usage (owner, day, tokens) VALUES (%s, %s, %s) "
                    "ON CONFLICT (owner, day) DO UPDATE SET tokens = token_usage.tokens + EXCLUDED.tokens, updated_at = now()",
                    [owner, day, int(tokens)])
            return
        except Exception as e:  # noqa: BLE001
            log_failure("quota_write", type(e).__name__)
    with _lock:
        _memory[(owner, day)] = _memory.get((owner, day), 0) + int(tokens)


def is_exempt() -> bool:
    """지금 요청이 운영자의 요청인가. 서명 확인한 로그인 이메일(auth.current_user)로 operators 표를 본다.
    로그인 정보가 없거나(로그인 꺼짐·스크립트) DB를 못 읽으면 운영자가 아니다(닫힌 쪽으로 실패)."""
    holder = request_user_var.get()
    email = holder.get("email") if holder else None
    if not email or not _db():
        return False
    import time

    now = time.monotonic()
    hit = _operator_cache.get(email)
    if hit and now - hit[1] < OPERATOR_CACHE_SEC:
        return hit[0]
    try:
        from backend.app.services.account.operators import is_operator, open_conn

        with open_conn() as conn:
            ok = is_operator(conn, email)
    except Exception as e:  # noqa: BLE001
        log_failure("quota_operator", type(e).__name__)
        return False
    _operator_cache[email] = (ok, now)
    return ok


def status(session_id: str | None, user_id: str | None) -> dict:
    """화면에 보여 줄 오늘 사용량. limit 0이거나 운영자면 한도 없음(limit None)."""
    cap, owner = (0 if is_exempt() else limit()), owner_key(session_id, user_id)
    spent = used(owner) if owner and cap else 0
    remaining = max(0, cap - spent) if cap else None
    return {
        "limit": cap or None,
        "used": spent,
        "remaining": remaining,
        "exhausted": bool(cap) and spent >= cap,
        "near_limit": bool(cap) and spent < cap and remaining <= cap * WARN_RATIO,
    }


def ensure_allowed(session_id: str | None, user_id: str | None) -> None:
    """요청 시작 때 부른다. 오늘 한도를 다 썼으면 QuotaExceeded. 같은 요청 안에서는 한 번만 확인한다."""
    request_id = current_request_id()
    if request_id and checked_var.get() == request_id:
        return
    checked_var.set(request_id)
    cap, owner = limit(), owner_key(session_id, user_id)
    if cap and owner and used(owner) >= cap and not is_exempt():
        raise QuotaExceeded(owner)


def forget_user(conn, user_id: str) -> None:
    """탈퇴할 때 그 사용자의 사용량 줄을 지운다 (services/account/account.py withdraw).
    가명 ID라 위험은 작지만 탈퇴하면 그 사람 몫 기록을 남기지 않는다는 원칙을 따른다. 메모리 사용량도 같이 비운다."""
    owner = owner_key(None, user_id)
    conn.execute("DELETE FROM token_usage WHERE owner = %s", [owner])
    with _lock:
        for key in [k for k in _memory if k[0] == owner]:
            del _memory[key]


def reset_memory() -> None:
    """테스트용. 메모리 사용량과 운영자 캐시를 비운다."""
    with _lock:
        _memory.clear()
    _operator_cache.clear()
