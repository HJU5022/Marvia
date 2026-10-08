"""서류 사진 출항일(etd) -> 내 화물 현황 표 출항 칸. 서버 쪽 저장 규칙 테스트.

DB 없이 돈다. 값은 모두 모의값이다(B/L도 실제 번호 아님).
- 저장 규칙의 핵심(manual은 안 덮고, 서류 값끼리는 새 값이 이긴다)은 cargo.DEPARTED_UPSERT_SQL을 그대로 SQLite에 돌려 확인한다.
  운영 DB는 PostgreSQL이지만 ON CONFLICT ... EXCLUDED, CASE, COALESCE는 SQLite도 같은 뜻이다.
- upsert_assessment가 그 조각을 쓰고 값(departed_on, 'document')을 넘기는지는 SQL을 적어 두는 가짜 conn으로 본다.
- 채팅 창구(routers/chat._agent_runner)가 같은 B/L 조회에만 날짜를 싣는지 본다.
- 출항일이 LLM 입력과 화물 기억 블록에 가지 않는지 본다 (판정에 안 쓴다).
"""
import sqlite3
from datetime import date, datetime, timezone

import pytest
from cryptography.fernet import Fernet

from backend.app.schemas.agent import AgentRequest
from backend.app.services.watch import cargo

NOW = datetime(2026, 10, 6, 3, tzinfo=timezone.utc)
BL = "MOCKBL20261006"  # 모의 B/L


@pytest.fixture
def bl_key(monkeypatch):
    monkeypatch.setenv("BL_ENCRYPTION_KEY", Fernet.generate_key().decode())


class FakeConn:
    """execute에 들어온 SQL과 값을 적어 둔다."""

    def __init__(self):
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((sql, list(params)))
        return None


def _request(**over) -> AgentRequest:
    return AgentRequest(**{"bl_no": BL, "bl_type": "HOUSE", "session_id": "s1", **over})


def _response():
    from backend.app.routers.agent import _response as make

    return make(status="ok", verdict="fine")


# ── 저장 규칙: 조각을 SQLite에 그대로 돌린다 ──

def _table(row: tuple[str | None, str | None] | None):
    """user_cargo 흉내 표. row가 있으면 (departed_on, departed_source)를 가진 기존 줄을 하나 넣는다."""
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE user_cargo (user_id TEXT, cargo_key TEXT, departed_on TEXT, departed_source TEXT, "
               "PRIMARY KEY (user_id, cargo_key))")
    if row:
        db.execute("INSERT INTO user_cargo VALUES ('u1', 'k1', ?, ?)", row)
    return db


def _write(db, departed_on: str | None, source: str | None):
    """조회 한 번이 이 칸에 하는 일: 이번 값을 넣고, 이미 줄이 있으면 DEPARTED_UPSERT_SQL로 합친다."""
    db.execute(
        f"INSERT INTO user_cargo (user_id, cargo_key, departed_on, departed_source) VALUES ('u1', 'k1', ?, ?) "
        f"ON CONFLICT (user_id, cargo_key) DO UPDATE SET {cargo.DEPARTED_UPSERT_SQL}",
        [departed_on, source])
    return db.execute("SELECT departed_on, departed_source FROM user_cargo").fetchall()


def test_document_etd_is_saved_with_source_document():
    db = _table(None)
    assert _write(db, "2026-09-20", "document") == [("2026-09-20", "document")]


def test_document_etd_fills_an_empty_existing_row():
    """조회로 이미 만들어진 줄(출항일 없음)에 서류 값이 들어간다."""
    db = _table((None, None))
    assert _write(db, "2026-09-20", "document") == [("2026-09-20", "document")]


def test_manual_date_is_never_overwritten():
    """사용자가 직접 적은 날짜는 서류 값이 와도 날짜도 출처도 그대로다."""
    db = _table(("2026-09-01", "manual"))
    assert _write(db, "2026-09-20", "document") == [("2026-09-01", "manual")]


def test_newer_document_value_replaces_older_document_value():
    db = _table(("2026-09-18", "document"))
    assert _write(db, "2026-09-20", "document") == [("2026-09-20", "document")]


def test_without_etd_nothing_changes():
    """이번 조회에 서류 출항일이 없으면(NULL) 저장된 날짜와 출처를 건드리지 않는다. manual이든 document든 같다."""
    assert _write(_table(("2026-09-18", "document")), None, None) == [("2026-09-18", "document")]
    assert _write(_table(("2026-09-01", "manual")), None, None) == [("2026-09-01", "manual")]
    assert _write(_table((None, None)), None, None) == [(None, None)]


# ── upsert_assessment가 값과 조각을 쓴다 ──

def test_upsert_passes_document_etd_and_uses_the_rule_sql(bl_key):
    conn = FakeConn()
    assert cargo.upsert_assessment(conn, "u1", _request(departed_on="2026-09-20"), _response(), released=False, now=NOW)
    sql, params = conn.calls[0]
    assert cargo.DEPARTED_UPSERT_SQL in sql
    assert date(2026, 9, 20) in params and "document" in params


def test_upsert_without_etd_passes_none_so_nothing_changes(bl_key):
    conn = FakeConn()
    assert cargo.upsert_assessment(conn, "u1", _request(), _response(), released=False, now=NOW)
    _, params = conn.calls[0]
    assert "document" not in params  # 출처는 날짜가 있을 때만 'document'


# ── 요청 계약: 선택 칸이고 다른 칸의 뜻을 바꾸지 않는다 ──

def test_departed_on_is_optional_and_parsed_as_date():
    assert _request().departed_on is None
    assert _request(departed_on="2026-09-20").departed_on == date(2026, 9, 20)
    with pytest.raises(ValueError):
        _request(departed_on="아무 말")


# ── 채팅 창구: 같은 B/L 조회에만 싣는다 ──

def _body(**over):
    from backend.app.routers.chat import ChatRequest

    return ChatRequest(**{"message": f"{BL} 어때?", "session_id": "s1", **over})


@pytest.fixture
def seen(monkeypatch):
    """routers.chat.run_agent가 받은 요청을 모은다 (실제 조회·LLM 없이)."""
    got = []
    from backend.app.routers import chat

    monkeypatch.setattr(chat, "run_agent", lambda req, user_id: got.append(req) or "응답")
    return got


def test_chat_runner_attaches_etd_to_the_documents_bl_only(seen):
    from backend.app.routers.chat import _agent_runner

    run = _agent_runner(_body(document={"bl_no": f" {BL.lower()} ", "departed_on": "2026-09-20"}), "u1")
    run(_request())
    run(_request(bl_no="OTHERBL20261006"))
    assert seen[0].departed_on == date(2026, 9, 20)  # 서류의 B/L (공백·소문자는 정규화해서 맞춘다)
    assert seen[1].departed_on is None  # 문장에 섞인 다른 B/L에는 가지 않는다


def test_chat_runner_leaves_requests_alone_without_document_or_for_follow_up(seen):
    from backend.app.routers.chat import _agent_runner

    _agent_runner(_body(), "u1")(_request())
    _agent_runner(_body(document={"bl_no": BL, "departed_on": "2026-09-20"}), "u1")(_request(follow_up_question="언제 와?"))
    assert [r.departed_on for r in seen] == [None, None]  # 후속 질문은 화물 표를 쓰지 않으므로 싣지 않는다


# ── 판정·LLM에는 가지 않는다 ──

def test_etd_is_not_in_judge_input_or_memory_block_columns():
    """판정 LLM 입력(_judge_input)은 요청을 받지 않고, 채팅 기억 블록이 읽는 칸 목록(COLUMNS)에도 출항일이 없다."""
    import inspect

    from backend.app.schemas.signals import SignalSet
    from backend.app.services import llm

    assert "request" not in inspect.signature(llm._judge_input).parameters
    signals = SignalSet(signals=[], freshness="fresh", distance_nm=None, calc_eta=None, eta_gap_hours=None, computed_at=NOW)
    text = llm._judge_input(signals, None, 5)
    assert "departed" not in text and "2026-09-20" not in text
    assert "departed_on" not in cargo.COLUMNS and "departed_source" not in cargo.COLUMNS


def test_llm_and_chat_services_never_read_departed_on():
    """LLM을 부르는 서비스(llm.py, chat.py)와 판정 라우터는 요청의 departed_on을 읽지 않는다. 읽는 곳은 화물 표 쓰기뿐이다."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "app"
    for rel in ("services/llm.py", "services/chat/chat.py", "routers/agent.py"):
        assert "departed_on" not in (root / rel).read_text(encoding="utf-8"), rel
