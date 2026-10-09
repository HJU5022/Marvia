"""대화 목록 저장·읽기·삭제와 제목 짓기 (ChatGPT·Claude식 대화 목록, migrations/018).

책임: 로그인 사용자의 채팅 대화를 DB에 잠가 두고(crypto.encrypt_pii) 목록·다시 열기·삭제를 돕는다.
  ready()          저장할 수 있는 환경인가 (DATABASE_URL과 PII 열쇠)
  save_later()     답을 만든 뒤 뒤에서 저장 + 첫 답이면 제목 짓기. 실패는 로그 종류만, 채팅 답에는 영향이 없다
  save_turn()      사용자 말 + 답 한 쌍을 저장한다 (동기)
  make_title()     첫 사용자 말(B/L 가림)로 LLM 제목, 검증 실패·LLM 실패면 첫 말 앞 20자
  list_for_user() / get_one() / delete_one() / delete_all()   창구(routers/conversations.py)와 탈퇴(services/account/account.py)가 쓴다

대화 번호는 채팅 요청의 session_id다. 사용자 말에는 B/L 원본·전화번호가 섞이므로 글과 JSON은 모두 잠근 글자만 DB에 둔다.
잠그지 못하면(열쇠 없음) 저장하지 않는다. 로그에는 오류 종류만 남긴다 (CLAUDE.md, SDD 3.5).
LLM에는 코드가 B/L을 [BL1]로 가린 첫 문장만 간다. 제목 LLM 호출은 services/llm.py 한 곳이다.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime

from backend.app import crypto
from backend.app.db import atomic, connect
from backend.app.observability.logging import log_failure
from backend.app.services.judge import guard
from backend.app.services import llm
from backend.app.services.account import memory
from backend.app.services.chat.chat import GREETING_REPLY, USAGE_GUIDE, mask_bls

# ── 숫자. 바꿀 곳은 여기 한 곳이다 ──
KEEP_MESSAGES = 200      # 대화당 말풍선 상한. 넘으면 오래된 줄부터 지운다
LIST_MAX = 50            # 목록에 돌려주는 대화 수
FALLBACK_CHARS = 20      # 제목이 없을 때 첫 사용자 말에서 가져오는 글자 수
TITLE_MAX = 30           # LLM 제목 상한. 프롬프트는 20자를 부탁하고, 코드는 30자까지 받는다
NO_TITLE = "새 대화"      # 첫 말이 비어 있을 때만

# 답 말풍선을 다시 그리는 데 필요한 화면 자료 칸. reply는 말풍선 글이라 text로 따로 저장하고,
# agent·request(큰 판정 덩어리)는 대화의 마지막 값만 conversations.context·result에 둔다.
# 단, cargos 줄은 눌렀을 때 오른쪽 칸을 바꾸려고 줄마다 agent·request를 들고 있어 그대로 둔다
# evidence_items·citations: 다시 연 대화에서도 근거 표시·칩이 그대로 나오게 extra_enc(잠긴 JSON)에 같이 둔다. 마이그레이션 없음
EXTRA_FIELDS = ("kind", "vessels", "place", "ports", "days", "map", "cargos", "watch_offer", "watch_set", "watch_vessel_set", "evidence_items", "citations")


def ready() -> bool:
    """저장할 수 있는 환경인가. DB 주소와 PII 열쇠가 둘 다 있어야 한다. 없으면 조용히 건너뛴다 (로그인 꺼진 채점 환경 포함)."""
    return bool(os.environ.get("DATABASE_URL") and os.environ.get(crypto.PII_KEY_ENV, "").strip())


# ── 제목 ──

def fallback_title(first_user_text: str) -> str:
    """LLM 제목을 못 얻었을 때 쓰는 제목: 첫 사용자 말 앞 20자. DB에는 잠겨 저장되고 같은 사용자에게만 보이므로 원문 그대로 쓴다."""
    flat = " ".join((first_user_text or "").split())  # 줄바꿈·겹공백을 한 칸으로
    return flat[:FALLBACK_CHARS] or NO_TITLE


def valid_title(raw: str | None) -> str | None:
    """LLM이 낸 제목이 써도 되는 모양이면 다듬어 돌려주고, 아니면 None. 한 줄, 30자 이하, 주입 모양 없음, [BL 토큰 없음."""
    title = (raw or "").strip().strip("\"'“”‘’").strip()
    if not title or len(title) > TITLE_MAX or "\n" in title or "\r" in title:
        return None
    if "[BL" in title.upper() or guard.looks_like_injection(title):
        return None
    return title


# 제목으로 삼기엔 내용이 없는 첫 말 (화면: "안녕"으로 시작한 대화 둘이 모두 "인사"로 고정됐다)
SMALL_TALK = re.compile(r"^\s*(?:안녕|안뇽|하이|헬로|hi|hello|hey|반가|ㅎㅇ|ㅎㅇㅎㅇ|좋은\s*(?:아침|하루|저녁))\S*[\s!?.~]*$", re.IGNORECASE)
# 인사 때문에 이미 붙은 제목 (화면: 고치기 전에 만든 대화가 LLM이 지은 "인사"로 남았다). 이런 제목은 자리표시자로 보고 진짜 질문에서 다시 짓는다
PLACEHOLDER_TITLES = {"인사", "인사말", "안부 인사", "안부", "감사 인사", NO_TITLE}


def is_placeholder_title(title: str | None) -> bool:
    """저장된 제목이 아직 임시인가: 비었거나, 새 대화이거나, 인사말 같은 제목. 진짜 제목이 정해지면 False라 다시 바꾸지 않는다.
    제목을 못 읽은 경우(None, 열쇠가 바뀜)는 임시로 보지 않는다: 읽지 못한 진짜 제목을 덮어쓰지 않으려고."""
    if title is None:
        return False
    t = title.strip()
    return not t or t in PLACEHOLDER_TITLES or bool(SMALL_TALK.match(t))


def is_small_talk(user_text: str, reply: dict) -> bool:
    """제목감이 없는 한 턴인가: 인사·사용법 답(코드가 쓴 고정 문장)이거나 짧은 인사말.
    이런 턴으로 대화가 시작되면 제목을 "새 대화"로 두고, 다음에 오는 진짜 질문으로 짓는다."""
    return reply.get("reply") in (GREETING_REPLY, USAGE_GUIDE) or bool(SMALL_TALK.match(user_text or ""))


def make_title(first_user_text: str) -> str:
    """제목 하나. B/L을 가린 첫 문장만 LLM에 보내고, 실패·검증 탈락이면 첫 말 앞 20자로 대신한다."""
    masked, _ = mask_bls(first_user_text or "")
    try:
        title = valid_title(llm.make_chat_title(masked).output.title)
    except Exception as e:  # noqa: BLE001 - 제목은 부가 기능이다. 오류 종류만 남기고 대체 제목으로 간다
        log_failure("conversation_title", getattr(e, "kind", None) or type(e).__name__)
        title = None
    return title or fallback_title(first_user_text)


# ── 저장 ──

def _lock(value: object) -> str | None:
    """글이나 JSON 값을 PII 열쇠로 잠근다. 열쇠가 없으면 None (부르는 쪽은 저장하지 않는다)."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return crypto.encrypt_pii(text)


def _extra_of(reply: dict) -> dict | None:
    """답 말풍선의 화면 자료. 비어 있는(None·빈 목록) 칸은 빼서 작게 둔다. kind가 message이고 다른 자료가 없으면 None."""
    extra = {k: reply[k] for k in EXTRA_FIELDS if reply.get(k) not in (None, [], "")}
    return extra if set(extra) - {"kind"} else None


def save_turn(conn, user_id: str, conv_id: str, user_text: str, reply: dict) -> bool:
    """사용자 말 + 답 한 쌍을 저장한다. 새 대화면 True. 잠그지 못하면 아무것도 저장하지 않고 False.

    reply는 ChatResponse를 model_dump(mode="json")한 dict다. 마지막 판정 덩어리(agent·request)는 이번 답에 있을 때만
    conversations.context·result를 바꾼다. 선박 검색 답처럼 없으면 앞의 값을 그대로 둔다 (오른쪽 칸을 마지막 화물로 복원).
    한 트랜잭션으로 묶어 말풍선이 반쪽만 남지 않게 한다 (atomic).
    """
    extra = _extra_of(reply)
    user_enc, reply_enc = _lock(user_text), _lock(reply.get("reply") or "")
    extra_enc = _lock(extra) if extra else None
    context_enc = _lock(reply["request"]) if reply.get("request") else None
    result_enc = _lock(reply["agent"]) if reply.get("agent") else None
    # 첫 턴이 인사면 제목은 일단 "새 대화". 진짜 질문이 오면 _save_job이 다시 짓는다
    title_enc = _lock(NO_TITLE if is_small_talk(user_text, reply) else fallback_title(user_text))
    if None in (user_enc, reply_enc, title_enc) or (extra and extra_enc is None) \
            or (reply.get("request") and context_enc is None) or (reply.get("agent") and result_enc is None):
        log_failure("conversation_save", "encrypt_failed")
        return False

    with atomic(conn):
        is_new = conn.execute("SELECT 1 FROM conversations WHERE user_id = %s AND id = %s",
                              [user_id, conv_id]).fetchone() is None
        # 대화 줄: 없으면 만들고(제목은 일단 첫 말 앞 20자), 있으면 마지막 판정과 시각만 바꾼다
        conn.execute(
            "INSERT INTO conversations (id, user_id, title_enc, context_enc, result_enc) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (user_id, id) DO UPDATE SET updated_at = now(), "
            "context_enc = COALESCE(EXCLUDED.context_enc, conversations.context_enc), "
            "result_enc = COALESCE(EXCLUDED.result_enc, conversations.result_enc)",
            [conv_id, user_id, title_enc, context_enc, result_enc])
        last = conn.execute("SELECT COALESCE(MAX(seq), 0) FROM conversation_messages "
                            "WHERE user_id = %s AND conversation_id = %s", [user_id, conv_id]).fetchone()[0]
        for seq, role, text_enc, e_enc in ((last + 1, "user", user_enc, None), (last + 2, "assistant", reply_enc, extra_enc)):
            conn.execute("INSERT INTO conversation_messages (user_id, conversation_id, seq, role, text_enc, extra_enc) "
                         "VALUES (%s, %s, %s, %s, %s, %s)", [user_id, conv_id, seq, role, text_enc, e_enc])
        # 대화당 마지막 200줄만 둔다. seq가 KEEP_MESSAGES 이하로 밀려난 줄을 지운다
        conn.execute("DELETE FROM conversation_messages WHERE user_id = %s AND conversation_id = %s AND seq <= %s",
                     [user_id, conv_id, last + 2 - KEEP_MESSAGES])
    return is_new


def set_title(conn, user_id: str, conv_id: str, title: str) -> None:
    """제목을 바꾼다. 잠그지 못하면 그대로 둔다 (앞의 제목이 남는다)."""
    title_enc = _lock(title)
    if title_enc is None:
        return
    conn.execute("UPDATE conversations SET title_enc = %s WHERE user_id = %s AND id = %s", [title_enc, user_id, conv_id])


def _save_job(user_id: str, conv_id: str, user_text: str, reply: dict) -> None:
    """뒤 작업 본체: 저장하고, 새 대화면 제목을 지어 바꾼다. 예외는 memory._guarded가 로그로 받는다.
    제목 LLM이 느려도 저장은 이미 끝났고, 채팅 답은 벌써 나갔다."""
    with connect() as conn:
        is_new = save_turn(conn, user_id, conv_id, user_text, reply)
        if is_small_talk(user_text, reply):
            return  # 인사·사용법 턴으로는 제목을 짓지 않는다
        if is_new or is_placeholder_title(current_title(conn, user_id, conv_id)):
            # 새 대화이거나, 인사로 시작해 아직 임시 제목("새 대화"·"인사" 등)인 대화의 첫 진짜 질문
            set_title(conn, user_id, conv_id, make_title(user_text))


def current_title(conn, user_id: str, conv_id: str) -> str | None:
    """지금 저장된 제목(잠금을 푼 글). 없으면 None."""
    row = conn.execute("SELECT title_enc FROM conversations WHERE user_id = %s AND id = %s", [user_id, conv_id]).fetchone()
    return _open(row[0]) if row else None


def save_later(user_id: str | None, conv_id: str | None, user_text: str, reply: dict) -> None:
    """답을 만든 뒤에 부른다. 로그인하지 않았거나 저장 환경이 아니면 아무것도 하지 않는다 (종류만 로그).
    저장은 기억 쓰기와 같은 뒤 일꾼(memory.run_later)에서 돈다. 요청의 문맥을 복사해 넘기고, 대기가 가득 차면 버린다."""
    if not user_id or not conv_id:
        return
    if not ready():
        log_failure("conversation_save", "not_configured")
        return
    memory.run_later(_save_job, user_id, conv_id, user_text, reply)


# ── 읽기·삭제 ──

def _iso(value: datetime | None) -> str:
    return value.isoformat() if value else ""


def _open(token: str | None) -> str | None:
    return crypto.decrypt_pii(token) if token else None


def _open_json(token: str | None) -> dict | None:
    text = _open(token)
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None


def list_for_user(conn, user_id: str) -> list[dict]:
    """최근 대화순 최대 50건. 제목을 못 열면(열쇠 바뀜) NO_TITLE."""
    rows = conn.execute("SELECT id, title_enc, updated_at FROM conversations WHERE user_id = %s "
                        "ORDER BY updated_at DESC LIMIT %s", [user_id, LIST_MAX]).fetchall()
    return [{"id": r[0], "title": _open(r[1]) or NO_TITLE, "updated_at": _iso(r[2])} for r in rows]


def get_one(conn, user_id: str, conv_id: str) -> dict | None:
    """대화 하나. 이 사용자 것이 아니거나 없으면 None (창구가 404). 열지 못한 말풍선은 건너뛴다."""
    head = conn.execute("SELECT title_enc, context_enc, result_enc FROM conversations "
                        "WHERE user_id = %s AND id = %s", [user_id, conv_id]).fetchone()
    if head is None:
        return None
    rows = conn.execute("SELECT role, text_enc, extra_enc, created_at FROM conversation_messages "
                        "WHERE user_id = %s AND conversation_id = %s ORDER BY seq", [user_id, conv_id]).fetchall()
    messages = []
    for role, text_enc, extra_enc, created_at in rows:
        text = _open(text_enc)
        if text is not None:
            messages.append({"role": role, "text": text, "created_at": _iso(created_at), "extra": _open_json(extra_enc)})
    return {"id": conv_id, "title": _open(head[0]) or NO_TITLE, "messages": messages,
            "context": _open_json(head[1]), "result": _open_json(head[2])}


def delete_one(conn, user_id: str, conv_id: str) -> bool:
    """대화 하나를 지운다(말풍선은 ON DELETE CASCADE). 없었으면 False."""
    return conn.execute("DELETE FROM conversations WHERE user_id = %s AND id = %s", [user_id, conv_id]).rowcount > 0


def delete_all(conn, user_id: str) -> int:
    """그 사용자의 대화를 모두 지운다 (탈퇴, services/account/account.py). 지운 대화 수."""
    return conn.execute("DELETE FROM conversations WHERE user_id = %s", [user_id]).rowcount
