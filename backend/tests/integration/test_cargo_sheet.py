"""내 화물 현황 표 테스트 (services/watch/cargo_sheet.py, routers/cargo_sheet.py, cargo.stage_date, 019 마이그레이션).

DB 없이 돈다. FakeConn이 user_cargo·user_lc 두 표를 메모리에 두고, 서비스가 보내는 SQL을 문장 앞부분으로 가려 흉내 낸다
(test_watch.FakeConn과 같은 방식). 진짜 Postgres에서의 SQL 동작은 따로 손으로 확인했다(작업 보고 참고). B/L은 모의값이다.
"""
import io
from datetime import date, datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from backend.app import crypto
from backend.app.main import app
from backend.app.services.watch import cargo
from backend.app.services.watch import cargo_sheet
from backend.app.services.account import operators as ops
from backend.tests.integration.test_admin import _login

USER, OTHER = "user-123", "someone-else"  # USER는 test_admin._login이 만드는 출입증의 사용자 ID
T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("BL_ENCRYPTION_KEY", Fernet.generate_key().decode())


class _Cur:
    def __init__(self, rows=(), rowcount=0):
        self.rows, self.rowcount = list(rows), rowcount

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class FakeConn:
    """user_cargo(cargo)와 user_lc(lcs)를 리스트로 둔다. 서비스가 보내는 문장 다섯 가지만 안다."""

    def __init__(self):
        self.cargo: list[dict] = []
        self.lcs: list[dict] = []
        self._n = 0

    def add(self, bl="MOCKBL20261001", user=USER, lc=None, **over) -> dict:
        """화물 줄 하나. lc는 add_lc가 돌려준 줄. created는 만든 순서를 가른다."""
        self._n += 1
        row = {"user_id": user, "cargo_key": cargo.cargo_key(bl), "bl_masked": "MOC*******" + bl[-4:],
               "bl_encrypted": crypto.encrypt(bl), "label": None, "status": "active", "departed_on": None,
               "departed_source": None, "arrived_on": None, "last_eta": None, "warehoused_on": None,
               "last_stage": None, "forwarder_name": None, "carrier_name": None, "container_no": None,
               "goods_name": None, "vessel_name": None, "vessel_flag": None, "created_at": T0 + timedelta(minutes=self._n), "lc_id": lc["id"] if lc else None, **over}
        self.cargo.append(row)
        return row

    def add_lc(self, lc_no, opened_on=None, user=USER) -> dict:
        lc = {"id": len(self.lcs) + 1, "user_id": user, "lc_no": lc_no, "opened_on": opened_on,
              "created_at": T0 + timedelta(minutes=len(self.lcs))}
        self.lcs.append(lc)
        return lc

    def row(self, bl="MOCKBL20261001", user=USER) -> dict:
        key = cargo.cargo_key(bl)
        return next(r for r in self.cargo if r["user_id"] == user and r["cargo_key"] == key)

    def execute(self, sql, params=()):
        q = " ".join(sql.split())
        params = list(params)
        if q.startswith("SELECT c.cargo_key"):
            mine = sorted((r for r in self.cargo if r["user_id"] == params[0]), key=lambda r: r["created_at"])
            out = []
            for r in mine[:params[1]]:
                lc = next((x for x in self.lcs if x["id"] == r["lc_id"]), None)
                out.append((r["cargo_key"], r["bl_masked"], r["bl_encrypted"], r["label"], r["status"],
                            r["departed_on"], r["departed_source"], r["arrived_on"], r["last_eta"],
                            r["warehoused_on"], r["last_stage"], r["forwarder_name"], r["carrier_name"],
                            r["container_no"], r["goods_name"], r["created_at"],
                            r["vessel_name"], r["vessel_flag"],
                            lc and lc["id"], lc and lc["lc_no"], lc and lc["opened_on"], lc and lc["created_at"]))
            return _Cur(out)
        if q.startswith("SELECT 1 FROM user_cargo"):
            found = [r for r in self.cargo if (r["user_id"], r["cargo_key"]) == tuple(params)]
            return _Cur([(1,)] if found else [])
        if q.startswith("INSERT INTO user_lc"):
            user, lc_no, opened_on, clear = params
            lc = next((x for x in self.lcs if (x["user_id"], x["lc_no"]) == (user, lc_no)), None)
            if lc is None:
                lc = self.add_lc(lc_no, opened_on, user)
            elif clear:  # CASE WHEN 비움 표시 THEN NULL
                lc["opened_on"] = None
            elif opened_on is not None:  # ELSE COALESCE(EXCLUDED.opened_on, 기존)
                lc["opened_on"] = opened_on
            return _Cur([(lc["id"],)])
        if q.startswith("UPDATE user_cargo SET lc_id"):
            lc_id, user, key = params
            for r in self.cargo:
                if (r["user_id"], r["cargo_key"]) == (user, key):
                    r["lc_id"] = lc_id
            return _Cur(rowcount=1)
        if q.startswith("DELETE FROM user_lc WHERE user_id = %s AND NOT EXISTS"):
            used = {r["lc_id"] for r in self.cargo}
            gone = [x for x in self.lcs if x["user_id"] == params[0] and x["id"] not in used]
            self.lcs = [x for x in self.lcs if x not in gone]
            return _Cur(rowcount=len(gone))
        if q.startswith("UPDATE user_cargo SET departed_on"):
            day, source, user, key = params
            for r in self.cargo:
                if (r["user_id"], r["cargo_key"]) == (user, key):
                    r["departed_on"], r["departed_source"] = day, source
            return _Cur(rowcount=1)
        raise AssertionError(f"모르는 SQL: {q[:60]}")


# ── stage_date: UNI-PASS 이력에서 입항·입고 날짜 뽑기 ──

def test_stage_date_naive_kst_time_keeps_its_date():
    """시간대 없는 처리일시는 한국 시각이다. 새벽 00:30을 UTC로 보면 전날로 밀리는데, 그대로 그 날짜여야 한다."""
    hist = [{"name": "입항보고 수리", "at": "2026-10-03T00:30:00"}]
    assert cargo.stage_date(hist, cargo.ARRIVED_STAGE) == date(2026, 10, 3)


def test_stage_date_aware_time_converts_to_kst():
    """시간대가 있는 시각은 한국 날짜로 바꾼다. UTC 10-02 16:00은 한국 10-03 01:00이다."""
    hist = [{"name": "반입신고", "at": "2026-10-02T16:00:00+00:00"}]
    assert cargo.stage_date(hist, cargo.WAREHOUSED_STAGE) == date(2026, 10, 3)


def test_stage_date_missing_stage_or_empty():
    hist = [{"name": "하선신고", "at": "2026-10-03T09:00:00"}]
    assert cargo.stage_date(hist, cargo.ARRIVED_STAGE) is None
    assert cargo.stage_date([], cargo.ARRIVED_STAGE) is None
    assert cargo.stage_date(None, cargo.ARRIVED_STAGE) is None


def test_stage_date_earliest_wins_and_ignores_spacing():
    """같은 단계가 여러 번 찍히면 가장 이른 날, 띄어쓰기가 달라도 같은 단계로 본다."""
    hist = [{"name": "입항보고수리", "at": "2026-10-05T09:00:00"}, {"name": "입항보고 수리", "at": "2026-10-04T09:00:00"}]
    assert cargo.stage_date(hist, cargo.ARRIVED_STAGE) == date(2026, 10, 4)


def test_stage_date_skips_bad_times():
    """시각이 없거나 읽을 수 없는 줄은 건너뛴다. 하나라도 읽히면 그 날짜를 쓴다."""
    hist = [{"name": "입항보고 수리", "at": None}, {"name": "입항보고 수리", "at": "어제"},
            {"name": "입항보고 수리", "at": "2026-10-04T09:00:00"}]
    assert cargo.stage_date(hist, cargo.ARRIVED_STAGE) == date(2026, 10, 4)
    assert cargo.stage_date(hist[:2], cargo.ARRIVED_STAGE) is None


# ── lc_no 검사 ──

def test_clean_lc_no_trims_and_accepts_limit():
    assert cargo_sheet.clean_lc_no("  LC-2026-001 ") == "LC-2026-001"
    assert cargo_sheet.clean_lc_no("A" * 35) == "A" * 35


@pytest.mark.parametrize("bad", ["", "   ", "A" * 36, "LC\n001", "LC\t001", "LC\x00001", "LC‮001"])
def test_clean_lc_no_rejects(bad):
    with pytest.raises(ValueError):
        cargo_sheet.clean_lc_no(bad)


# ── 묶기와 순서 ──

def test_grouping_and_order():
    """신용장 묶음은 개설일 순(없는 것은 뒤), 같으면 만든 순. 묶음 안은 화물 만든 순. 신용장 없는 줄은 맨 끝 한 묶음."""
    db = FakeConn()
    lc_late = db.add_lc("LC-LATE", date(2026, 9, 20))
    lc_early = db.add_lc("LC-EARLY", date(2026, 8, 1))
    lc_none = db.add_lc("LC-NODATE", None)
    db.add("MOCKBL000000A1", lc=lc_late)
    db.add("MOCKBL000000B1", lc=None)
    db.add("MOCKBL000000C1", lc=lc_early)
    db.add("MOCKBL000000D1", lc=lc_none)
    db.add("MOCKBL000000E1", lc=lc_late)
    db.add("MOCKBL000000F1", lc=lc_early)
    db.add("MOCKBL000000G1", user=OTHER)  # 다른 사람의 줄은 안 보인다
    groups = cargo_sheet.load_sheet(db, USER)["groups"]
    assert [g["lc"] and g["lc"]["lc_no"] for g in groups] == ["LC-EARLY", "LC-LATE", "LC-NODATE", None]
    assert [[r["bl_masked"][-4:] for r in g["rows"]] for g in groups] == [["00C1", "00F1"], ["00A1", "00E1"], ["00D1"], ["00B1"]]
    assert groups[0]["lc"] == {"id": lc_early["id"], "lc_no": "LC-EARLY", "opened_on": date(2026, 8, 1)}


def test_load_sheet_row_shape_hides_inner_values():
    """행에는 계약의 칸만 있다. 잠근 B/L(bl_encrypted)이나 만든 시각은 나가지 않는다. 예정일(eta)은 last_eta다."""
    db = FakeConn()
    db.add(last_eta=date(2026, 10, 9), label="고추")
    row = cargo_sheet.load_sheet(db, USER)["groups"][0]["rows"][0]
    assert set(row) == {"cargo_key", "bl_masked", "label", "status", "departed_on", "departed_source", "arrived_on",
                        "eta", "warehoused_on", "last_stage", "forwarder_name", "carrier_name", "container_no",
                        "goods_name", "vessel_name", "vessel_flag"}
    assert row["eta"] == date(2026, 10, 9) and row["label"] == "고추"
    assert cargo_sheet.load_sheet(FakeConn(), USER) == {"groups": [], "truncated": False}


def test_load_sheet_truncated_flag(monkeypatch):
    """SHEET_MAX줄까지는 잘림 없음, 한 줄 넘으면 truncated=True이고 SHEET_MAX줄만 담는다 (S5)."""
    monkeypatch.setattr(cargo_sheet, "SHEET_MAX", 3)
    db = FakeConn()
    for i in range(3):
        db.add(f"MOCKBL00000{i}A1")
    sheet = cargo_sheet.load_sheet(db, USER)
    assert sheet["truncated"] is False and len(sheet["groups"][0]["rows"]) == 3
    db.add("MOCKBL000009A1")
    sheet = cargo_sheet.load_sheet(db, USER)
    assert sheet["truncated"] is True and len(sheet["groups"][0]["rows"]) == 3


# ── 신용장 잇기·풀기, 출항 ──

def test_set_lc_creates_links_and_shares_by_number():
    db = FakeConn()
    a, b = db.add("MOCKBL000000A1"), db.add("MOCKBL000000B1")
    cargo_sheet.set_lc(db, USER, a["cargo_key"], "LC-1", date(2026, 9, 1))
    cargo_sheet.set_lc(db, USER, b["cargo_key"], "LC-1", None)  # 같은 번호: 개설일을 또 적지 않아도 된다
    assert len(db.lcs) == 1 and db.lcs[0]["opened_on"] == date(2026, 9, 1)
    assert a["lc_id"] == b["lc_id"] == db.lcs[0]["id"]


def test_set_lc_clear_opened_date():
    """clear_opened=True면 개설일을 비운다. 기본(False)이나 날짜를 안 넘긴 경우는 기존 값을 둔다 (S3)."""
    db = FakeConn()
    a = db.add("MOCKBL000000A1")
    cargo_sheet.set_lc(db, USER, a["cargo_key"], "LC-1", date(2026, 9, 1))
    cargo_sheet.set_lc(db, USER, a["cargo_key"], "LC-1", None)
    assert db.lcs[0]["opened_on"] == date(2026, 9, 1)
    cargo_sheet.set_lc(db, USER, a["cargo_key"], "LC-1", None, clear_opened=True)
    assert db.lcs[0]["opened_on"] is None


def test_set_lc_unlink_removes_empty_lc_only():
    db = FakeConn()
    a, b = db.add("MOCKBL000000A1"), db.add("MOCKBL000000B1")
    cargo_sheet.set_lc(db, USER, a["cargo_key"], "LC-1", None)
    cargo_sheet.set_lc(db, USER, b["cargo_key"], "LC-1", None)
    cargo_sheet.set_lc(db, USER, a["cargo_key"], None, None)
    assert a["lc_id"] is None and len(db.lcs) == 1  # b가 아직 쓴다
    cargo_sheet.set_lc(db, USER, b["cargo_key"], "LC-2", None)  # 옮기면 비게 된 LC-1은 지워진다
    assert [x["lc_no"] for x in db.lcs] == ["LC-2"]


def test_lc_numbers_are_per_user():
    db = FakeConn()
    mine, theirs = db.add("MOCKBL000000A1"), db.add("MOCKBL000000A1", user=OTHER)
    cargo_sheet.set_lc(db, USER, mine["cargo_key"], "LC-1", None)
    cargo_sheet.set_lc(db, OTHER, theirs["cargo_key"], "LC-1", None)
    assert len(db.lcs) == 2 and mine["lc_id"] != theirs["lc_id"]


def test_other_users_cargo_is_not_found():
    db = FakeConn()
    theirs = db.add(user=OTHER)
    with pytest.raises(cargo_sheet.CargoNotFound):
        cargo_sheet.set_lc(db, USER, theirs["cargo_key"], "LC-1", None)
    with pytest.raises(cargo_sheet.CargoNotFound):
        cargo_sheet.set_departed(db, USER, theirs["cargo_key"], date(2026, 9, 1))
    assert db.lcs == [] and theirs["departed_on"] is None


def test_set_departed_sets_and_clears_source():
    db = FakeConn()
    a = db.add()
    cargo_sheet.set_departed(db, USER, a["cargo_key"], date(2026, 9, 12), "document")
    assert (a["departed_on"], a["departed_source"]) == (date(2026, 9, 12), "document")
    cargo_sheet.set_departed(db, USER, a["cargo_key"], None, "manual")
    assert (a["departed_on"], a["departed_source"]) == (None, None)  # 날짜를 비우면 출처도 비운다
    with pytest.raises(ValueError):
        cargo_sheet.set_departed(db, USER, a["cargo_key"], date(2026, 9, 12), "guess")


# ── 엑셀 ──

def _sheet(db):
    wb = load_workbook(io.BytesIO(cargo_sheet.build_xlsx(db, USER)))
    return wb.active


def _father_sheet() -> FakeConn:
    """아버지 표 모양: 신용장 두 개, 첫 신용장에 B/L 둘, 둘째에 하나, 신용장 없는 줄 하나."""
    db = FakeConn()
    lc1, lc2 = db.add_lc("LC-0001", date(2026, 7, 21)), db.add_lc("LC-0002", date(2026, 8, 5))
    db.add("MOCKBL000000A1", lc=lc1, departed_on=date(2026, 8, 1), arrived_on=date(2026, 8, 30),
           warehoused_on=date(2026, 9, 2), forwarder_name="모의포워더", carrier_name="모의선사", container_no="MOCU1234567, MOCU7654321",
           goods_name="MOCK GOODS")
    db.add("MOCKBL000000B1", lc=lc1, departed_on=date(2026, 8, 3), last_eta=date(2026, 10, 9))  # 입항 전: 예정
    db.add("MOCKBL000000C1", lc=lc2)
    db.add("MOCKBL000000D1")
    return db


def test_xlsx_headers_layout_and_freeze():
    ws = _sheet(_father_sheet())
    headers = [c.value for c in ws[1]]
    assert headers == ["신용장 개설일", "신용장 번호", "B/L 번호", "출항", "입항", "입고", "포워더", "선사", "컨테이너 번호", "품명", "선명", "국적"]
    assert all(c.font.bold for c in ws[1]) and ws.freeze_panes == "A2"
    assert ws.column_dimensions["B"].width > 10 and ws.column_dimensions["L"].width > 5  # 국적 칸(L)까지 너비가 잡힌다
    assert ws.max_row == 5


def test_xlsx_lc_cells_only_on_first_row_of_group():
    ws = _sheet(_father_sheet())
    assert [(ws.cell(r, 1).value, ws.cell(r, 2).value) for r in range(2, 6)] == [
        (datetime(2026, 7, 21), "LC-0001"), (None, None), (datetime(2026, 8, 5), "LC-0002"), (None, None)]
    assert [ws.cell(r, 3).value[-4:] for r in range(2, 6)] == ["00A1", "00B1", "00C1", "00D1"]


def test_xlsx_dates_are_real_date_cells_with_month_day_format():
    ws = _sheet(_father_sheet())
    for cell in (ws["A2"], ws["D2"], ws["E2"], ws["F2"]):
        assert isinstance(cell.value, datetime) and cell.number_format == "m/d"
    assert ws["D2"].value == datetime(2026, 8, 1) and ws["E2"].value == datetime(2026, 8, 30)


def test_xlsx_expected_arrival_is_text_not_date():
    """입항일이 없고 예정일만 있으면 글자 "예정 10/9". 실제 신고된 날(날짜 칸)과 섞이지 않는다."""
    ws = _sheet(_father_sheet())
    assert ws["E3"].value == "예정 10/9" and ws["E3"].data_type == "s"
    assert ws["E4"].value is None and ws["F3"].value is None  # 예정일도 없으면 빈칸


def test_xlsx_actual_arrival_beats_expected():
    db = FakeConn()
    db.add(arrived_on=date(2026, 9, 3), last_eta=date(2026, 9, 1))
    ws = _sheet(db)
    assert ws["E2"].value == datetime(2026, 9, 3)


def test_xlsx_company_and_container_columns():
    ws = _sheet(_father_sheet())
    assert [ws.cell(2, c).value for c in (7, 8, 9)] == ["모의포워더", "모의선사", "MOCU1234567, MOCU7654321"]
    assert [ws.cell(3, c).value for c in (7, 8, 9)] == [None, None, None]


def test_xlsx_default_bl_is_original():
    """기본값은 원본이다 (SDD 3.5 예외). 수입자가 그 번호로 다른 곳에서 화물을 조회한다."""
    db = FakeConn()
    db.add("MOCKBL20261001")
    assert cargo_sheet.XLSX_BL_SOURCE == "original"
    assert _sheet(db)["C2"].value == "MOCKBL20261001"


def test_xlsx_original_falls_back_to_masked_when_decrypt_fails():
    """원본을 열지 못하면(열쇠 없음·잘못된 토큰) 빈 칸이 아니라 가린 값으로 대신한다."""
    db = FakeConn()
    broken = db.add("MOCKBL20261002", bl_encrypted="not-a-token")
    assert _sheet(db)["C2"].value == broken["bl_masked"]


def test_xlsx_masked_switch(monkeypatch):
    """XLSX_BL_SOURCE를 "masked"로 돌리면 가린 값만 적히고 원본은 파일 어디에도 없다."""
    monkeypatch.setattr(cargo_sheet, "XLSX_BL_SOURCE", "masked")
    db = FakeConn()
    db.add("MOCKBL20261001")
    ws = _sheet(db)
    assert ws["C2"].value == "MOC*******1001"
    assert "MOCKBL20261001" not in {c.value for row in ws.iter_rows() for c in row}


def test_xlsx_text_cells_never_become_formulas():
    """신용장 번호나 포워더 이름이 =로 시작해도 수식이 아니라 글자로 저장된다."""
    db = FakeConn()
    lc = db.add_lc("=1+1", date(2026, 7, 1))
    db.add(lc=lc, forwarder_name='=HYPERLINK("http://example.invalid")')
    ws = _sheet(db)
    assert ws["B2"].value == "=1+1" and ws["B2"].data_type == "s"
    assert ws["G2"].data_type == "s"


def test_xlsx_empty_sheet_has_headers_only():
    ws = _sheet(FakeConn())
    assert ws.max_row == 1 and ws["A1"].value == "신용장 개설일"


def test_xlsx_filename_uses_korean_date():
    assert cargo_sheet.xlsx_filename(datetime(2026, 10, 5, 16, 0, tzinfo=timezone.utc)) == "marvia_cargo_20261006.xlsx"


# ── 창구 ──

class _Ctx:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *exc):
        return False


@pytest.fixture
def db(monkeypatch):
    conn = FakeConn()
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    monkeypatch.setattr(ops, "open_conn", lambda: _Ctx(conn))
    return conn


@pytest.fixture
def me(monkeypatch):
    return _login(monkeypatch, "kim@example.com")


def _call(method, path, body=None, headers=None):
    with TestClient(app) as c:
        return getattr(c, method)(path, headers=headers, **({"json": body} if body is not None else {}))


ENDPOINTS = [("get", "/api/cargo/sheet", None), ("get", "/api/cargo/sheet.xlsx", None),
             ("put", "/api/cargo/sheet/abc/lc", {"lc_no": "LC-1"}),
             ("put", "/api/cargo/sheet/abc/departed", {"departed_on": "2026-09-01", "source": "manual"})]


@pytest.mark.parametrize("method,path,body", ENDPOINTS)
def test_login_required(monkeypatch, method, path, body):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    assert _call(method, path, body).status_code == 401  # 로그인 기능이 꺼진 환경
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    assert _call(method, path, body).status_code == 401  # 켜졌는데 출입증 없음


@pytest.mark.parametrize("method,path,body", ENDPOINTS)
def test_no_database_is_503(monkeypatch, me, method, path, body):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert _call(method, path, body, me).status_code == 503


@pytest.mark.parametrize("method,path,body", ENDPOINTS)
def test_db_failure_is_503_without_leaking(monkeypatch, me, method, path, body):
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")

    def down():
        raise RuntimeError("connection to MOCKBL20261001 failed")

    monkeypatch.setattr(ops, "open_conn", down)
    r = _call(method, path, body, me)
    assert r.status_code == 503 and "MOCKBL" not in r.text and "connection" not in r.text


def test_get_sheet_json_shape(db, me):
    lc = db.add_lc("LC-1", date(2026, 9, 1))
    db.add(lc=lc, last_eta=date(2026, 10, 9), arrived_on=None)
    r = _call("get", "/api/cargo/sheet", headers=me)
    assert r.status_code == 200
    group = r.json()["groups"][0]
    assert group["lc"] == {"id": lc["id"], "lc_no": "LC-1", "opened_on": "2026-09-01"}
    assert group["rows"][0]["eta"] == "2026-10-09" and group["rows"][0]["arrived_on"] is None
    assert "MOCKBL20261001" not in r.text and "bl_encrypted" not in r.text
    assert r.json()["truncated"] is False


def test_put_lc_links_and_returns_updated_sheet(db, me):
    row = db.add()
    r = _call("put", f"/api/cargo/sheet/{row['cargo_key']}/lc", {"lc_no": " LC-9 ", "opened_on": "2026-09-01"}, me)
    assert r.status_code == 200
    assert r.json()["groups"][0]["lc"]["lc_no"] == "LC-9" and r.json()["groups"][0]["lc"]["opened_on"] == "2026-09-01"
    r = _call("put", f"/api/cargo/sheet/{row['cargo_key']}/lc", {"lc_no": None}, me)
    assert r.status_code == 200 and r.json()["groups"][0]["lc"] is None and db.lcs == []


def test_put_lc_explicit_null_clears_opened_date_but_omitted_keeps(db, me):
    """opened_on 키를 생략하면 개설일 유지, 명시적 null이면 비움 (S3)."""
    row = db.add()
    url = f"/api/cargo/sheet/{row['cargo_key']}/lc"
    _call("put", url, {"lc_no": "LC-1", "opened_on": "2026-09-01"}, me)
    r = _call("put", url, {"lc_no": "LC-1"}, me)
    assert r.json()["groups"][0]["lc"]["opened_on"] == "2026-09-01"
    r = _call("put", url, {"lc_no": "LC-1", "opened_on": None}, me)
    assert r.status_code == 200 and r.json()["groups"][0]["lc"]["opened_on"] is None


@pytest.mark.parametrize("bad", ["", "  ", "A" * 36, "LC\n1"])
def test_put_lc_validates_number(db, me, bad):
    row = db.add()
    r = _call("put", f"/api/cargo/sheet/{row['cargo_key']}/lc", {"lc_no": bad}, me)
    assert r.status_code == 422 and db.lcs == []


def test_put_lc_bad_date_is_422(db, me):
    row = db.add()
    assert _call("put", f"/api/cargo/sheet/{row['cargo_key']}/lc", {"lc_no": "LC-1", "opened_on": "9월 1일"}, me).status_code == 422


def test_other_users_cargo_key_is_404(db, me):
    theirs = db.add(user=OTHER)
    for path, body in ((f"/api/cargo/sheet/{theirs['cargo_key']}/lc", {"lc_no": "LC-1"}),
                       (f"/api/cargo/sheet/{theirs['cargo_key']}/departed", {"departed_on": "2026-09-01"}),
                       ("/api/cargo/sheet/nope/lc", {"lc_no": "LC-1"})):
        assert _call("put", path, body, me).status_code == 404
    assert db.lcs == [] and theirs["departed_on"] is None


def test_put_departed(db, me):
    row = db.add()
    r = _call("put", f"/api/cargo/sheet/{row['cargo_key']}/departed", {"departed_on": "2026-09-12", "source": "document"}, me)
    got = r.json()["groups"][0]["rows"][0]
    assert r.status_code == 200 and (got["departed_on"], got["departed_source"]) == ("2026-09-12", "document")
    r = _call("put", f"/api/cargo/sheet/{row['cargo_key']}/departed", {"departed_on": "2026-09-13"}, me)  # source 생략은 manual
    assert r.json()["groups"][0]["rows"][0]["departed_source"] == "manual"
    r = _call("put", f"/api/cargo/sheet/{row['cargo_key']}/departed", {"departed_on": None, "source": "manual"}, me)
    assert r.json()["groups"][0]["rows"][0]["departed_source"] is None
    assert _call("put", f"/api/cargo/sheet/{row['cargo_key']}/departed", {"departed_on": "2026-09-13", "source": "guess"}, me).status_code == 422


def test_xlsx_download(db, me):
    db.add_lc("LC-1", date(2026, 9, 1))
    db.add(lc=db.lcs[0])
    r = _call("get", "/api/cargo/sheet.xlsx", headers=me)
    assert r.status_code == 200
    assert r.headers["content-type"] == cargo_sheet.XLSX_MIME
    disposition = r.headers["content-disposition"]
    assert disposition.startswith("attachment; filename=\"marvia_cargo_") and disposition.endswith(".xlsx\"")
    assert r.headers["cache-control"] == "no-store"
    assert load_workbook(io.BytesIO(r.content)).active["B2"].value == "LC-1"


# ── 019 마이그레이션 ──

def test_migration_019_shape():
    from backend.app.db import MIGRATIONS_DIR

    sql = (MIGRATIONS_DIR / "019_cargo_sheet.sql").read_text(encoding="utf-8")
    assert "UNIQUE (user_id, lc_no)" in sql and "ENABLE ROW LEVEL SECURITY" in sql
    assert f"BETWEEN 1 AND {cargo_sheet.LC_NO_MAX}" in sql
    assert "CHECK (departed_source IN ('manual', 'document'))" in sql
    for col in ("lc_id", "departed_on", "arrived_on", "warehoused_on", "forwarder_name", "carrier_name", "container_no"):
        assert f"ADD COLUMN IF NOT EXISTS {col}" in sql
    assert "\u2014" not in sql  # em dash 금지 (CLAUDE.md)


def test_delete_all_removes_lc_rows_too():
    from backend.tests.unit.test_cargo import FakeConn as Recorder

    conn = Recorder(rowcount=4)
    assert cargo.delete_all(conn, "u1") == 4  # 알리는 숫자는 화물 줄 수 그대로
    assert [c[0] for c in conn.calls] == ["DELETE FROM user_cargo WHERE user_id = %s", "DELETE FROM user_lc WHERE user_id = %s"]
    assert all(c[1] == ["u1"] for c in conn.calls)


def test_xlsx_goods_name_column():
    """품명은 10번째 칸. UNI-PASS 외부 글자라 다른 회사 칸처럼 글자 형식으로 쓴다"""
    ws = _sheet(_father_sheet())
    assert ws["J2"].value == "MOCK GOODS" and ws["J2"].data_type == "s"
    assert ws["J3"].value is None  # 품명이 없는 줄은 빈칸


def test_xlsx_vessel_columns_are_text_at_the_end():
    """선명·국적은 맨 뒤 11·12번째 칸이다. 외부 글자라 글자 형식으로 쓰고, =로 시작해도 수식이 되지 않는다."""
    db = FakeConn()
    db.add("MOCKBL000000A1", vessel_name="MOCK VESSEL", vessel_flag="PA")
    db.add("MOCKBL000000B1", vessel_name="=1+1", vessel_flag=None)
    db.add("MOCKBL000000C1")
    ws = _sheet(db)
    assert (ws["K2"].value, ws["L2"].value) == ("MOCK VESSEL", "PA")
    assert ws["K2"].data_type == "s" and ws["L2"].data_type == "s"
    assert ws["K3"].value == "=1+1" and ws["K3"].data_type == "s" and ws["L3"].value is None
    assert ws["K4"].value is None and ws["L4"].value is None  # 선명·국적이 없는 줄은 빈칸


def test_migration_020_shape():
    from backend.app.db import MIGRATIONS_DIR

    sql = (MIGRATIONS_DIR / "020_goods_name.sql").read_text(encoding="utf-8")
    assert "ALTER TABLE user_cargo ADD COLUMN IF NOT EXISTS goods_name TEXT" in sql
    assert "\u2014" not in sql  # em dash 금지 (CLAUDE.md)
