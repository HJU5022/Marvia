"""화물 표 서비스 테스트 (services/cargo.py, docs/specs/memory.md "화물 표 컬럼").

DB 없이 돈다. conn은 보낸 SQL과 값을 적어 두는 가짜다. B/L은 모의값이다(실제 번호 아님).
"""
from datetime import date, datetime, timezone

import pytest
from cryptography.fernet import Fernet

from backend.app.schemas.agent import AgentRequest
from backend.app.services import cargo
from backend.app.services.verdict import VERDICT_LABEL

NOW = datetime(2026, 10, 2, 3, tzinfo=timezone.utc)  # 한국 시각 10-02 12:00
BL = "MOCKBL20261002"  # 모의 B/L


@pytest.fixture
def bl_key(monkeypatch):
    monkeypatch.setenv("BL_ENCRYPTION_KEY", Fernet.generate_key().decode())


class FakeConn:
    """execute에 들어온 SQL과 값을 적어 둔다. fetchone/fetchall은 정해 둔 값을 돌려준다."""

    def __init__(self, one=None, rows=None, rowcount=1):
        self.calls, self.one, self.rows, self.rowcount = [], one, rows or [], rowcount

    def execute(self, sql, params=()):
        self.calls.append((sql, list(params)))
        conn = self

        class Cur:
            rowcount = conn.rowcount

            def fetchone(self):
                return conn.one

            def fetchall(self):
                return conn.rows
        return Cur()


def _request(**over) -> AgentRequest:
    return AgentRequest(**{"bl_no": BL, "bl_type": "HOUSE", "sale_due_date": None, "session_id": "s1", **over})


def _response(**over):
    from backend.app.routers.agent import _response as make

    return make(**over)


def test_cargo_key_comes_from_bl_key_and_separates_same_mask(bl_key):
    """같은 가린 번호가 나오는 두 B/L도 지문은 다르다 (Spec EC-05)."""
    from backend.app.schemas.customs import mask_bl

    other = "MOCKXX20261002"
    assert mask_bl(BL) == mask_bl(other)
    assert cargo.cargo_key(BL) != cargo.cargo_key(other)
    assert cargo.cargo_key(BL) == cargo.cargo_key(BL.lower())  # 대문자로 맞춰 같은 화물


def test_without_bl_key_nothing_is_written(monkeypatch):
    """열쇠가 없으면 지문을 못 만들어 화물 표를 쓰지 않는다 (채점용 환경과 같은 길)."""
    monkeypatch.delenv("BL_ENCRYPTION_KEY", raising=False)
    conn = FakeConn()
    assert cargo.upsert_assessment(conn, "u1", _request(), _response(status="ok", verdict="fine"), released=False) is False
    assert conn.calls == []


def test_upsert_stores_masked_and_encrypted_only(bl_key):
    """원본 B/L은 잠근 값으로만 간다. 가린 번호와 지문 말고 원문은 SQL 값에 없다 (SDD 3.5)."""
    conn = FakeConn()
    resp = _response(status="ok", verdict="watch", days_margin=3)
    assert cargo.upsert_assessment(conn, "u1", _request(sale_due_date="2026-10-05"), resp, released=False, now=NOW)
    sql, params = conn.calls[0]
    assert "ON CONFLICT (user_id, cargo_key)" in sql
    assert BL not in params
    assert "MOC*******1002" in params and "active" in params and "watch" in params and 3 in params
    assert date(2026, 10, 5) in params
    assert ["sale_due_date"] in params  # 이번에 넣은 칸의 확인 대기는 지운다 (사용자가 직접 넣은 값이 확인)


def test_released_cargo_is_done(bl_key):
    """통관 단계가 반출이면 done, 완료 시각을 남긴다 (Spec "끝난 건 스스로 정리")."""
    conn = FakeConn()
    cargo.upsert_assessment(conn, "u1", _request(), _response(status="ok", verdict="fine"), released=True, now=NOW)
    params = conn.calls[0][1]
    assert "done" in params and NOW in params


@pytest.mark.parametrize("over", [
    {"status": "failed"},                                          # 통관 조회 실패
    {"status": "unsupported"},                                     # 부산 밖
    {"status": "insufficient", "missing_inputs": ["bl_type"]},     # 세관에 없는 번호(오타일 수 있다)
])
def test_no_row_for_unfound_cargo(bl_key, over):
    conn = FakeConn()
    assert cargo.upsert_assessment(conn, "u1", _request(), _response(**over), released=False) is False
    assert conn.calls == []


def test_vessel_source_only_for_mrn_or_user():
    """확정 방법은 mrn / user만. 이름만으로 찾은 배는 적지 않는다."""
    from backend.app.schemas.agent import VesselCandidate

    def cand(reason):
        return VesselCandidate(mmsi=1, imo=None, name="X", flag=None, dest=None, last_time=NOW, ship_type=None,
                               match_reasons=[reason])
    resp = lambda reason: _response(vessel_match="confirmed", vessel_candidates=[cand(reason)])  # noqa: E731
    assert cargo._vessel(_request(), resp("MRN 입항 신고의 호출부호 일치")) == (1, "mrn")
    assert cargo._vessel(_request(), resp("선명 유사도 1.0")) == (None, None)
    assert cargo._vessel(_request(voyage_no="0042E"), resp("선명 유사도 1.0")) == (1, "user")
    assert cargo._vessel(_request(resolved_mmsi=7), _response()) == (7, "user")


def test_previous_line_is_code_written():
    """10-02 결정 4: 덮기 전 줄로 한 줄. 날짜는 한국 날짜, 등급은 화면 이름."""
    row = {"last_verdict": "watch", "last_checked_at": datetime(2026, 9, 30, 20, tzinfo=timezone.utc),
           "last_days_margin": 3}
    assert cargo.previous_line(row) == f"지난 조회(10.01)에서는 {VERDICT_LABEL['watch']}, 여유 3일이었어요."
    row["last_days_margin"] = -2
    assert cargo.previous_line(row) == "지난 조회(10.01)에서는 지켜볼 것, 판매 예정일보다 2일 늦음이었어요."
    row["last_days_margin"] = None
    assert cargo.previous_line(row) == "지난 조회(10.01)에서는 지켜볼 것이었어요."
    assert cargo.previous_line({"last_verdict": None, "last_checked_at": NOW}) is None  # 판정 보류였으면 안 붙인다
    assert cargo.previous_line(None) is None


def test_block_line_has_masked_number_and_conditions_but_no_ids():
    row = {"cargo_key": "k", "bl_masked": "MOC*******1002", "bl_type": "HOUSE", "label": "고추", "status": "active",
           "sale_due_date": date(2026, 10, 5), "forwarder_eta": date(2026, 10, 1),
           "forwarder_eta_noted_at": date(2026, 9, 28), "original_bl": "required", "to_order_bank": True,
           "freight_term": "collect", "incoterm": "FOB", "last_verdict": "watch", "last_checked_at": NOW,
           "last_days_margin": 3, "last_eta": date(2026, 10, 2), "last_stage": "반입신고"}
    line = cargo.cargo_line(row)
    assert line.startswith("- 고추 (MOC*******1002)")
    for text in ("받아야 하는 날 2026-10-05", "09.28에 들음", "원본 B/L 필요", "수하인 은행 지시식", "운임 착불 (FOB)",
                 "지난 조회 10.02: 지켜볼 것, 여유 3일", "통관 반입신고"):
        assert text in line
    assert BL not in line and "[" not in line


def test_document_facts_keep_unknown_values(bl_key):
    """서류에서 확인한 조건만 덮고, 모름(None)은 기존 값을 지우지 않는다 (10-02 결정 7)."""
    conn = FakeConn()
    key = cargo.apply_document_facts(conn, "u1", BL, "HOUSE", {"original_bl": "surrendered", "to_order_bank": None,
                                                               "freight_term": "collect", "incoterm": None})
    sql, params = conn.calls[0]
    assert key == cargo.cargo_key(BL)
    assert "original_bl = COALESCE(EXCLUDED.original_bl, user_cargo.original_bl)" in sql
    assert BL not in params and "surrendered" in params and "collect" in params


def test_pending_replaces_same_field():
    conn = FakeConn(one=tuple(None if c != "pending" else [{"field": "label", "value": "옛 이름"}] for c in cargo.COLUMNS))
    assert cargo.add_pending(conn, "u1", "k", [{"field": "label", "value": "고추", "noted_at": "2026-10-02"}]) == 1
    saved = conn.calls[-1][1][0]
    assert "고추" in saved and "옛 이름" not in saved


def test_delete_all_targets_one_user():
    conn = FakeConn(rowcount=4)
    assert cargo.delete_all(conn, "u1") == 4
    assert conn.calls == [("DELETE FROM user_cargo WHERE user_id = %s", ["u1"])]


def test_done_summary_uses_code_values_only():
    row = {"bl_masked": "MOC*******1002", "label": None, "done_at": datetime(2026, 9, 22, 1, tzinfo=timezone.utc)}
    assert cargo.done_summary(row) == "09.22 MOC*******1002 반출 완료"
