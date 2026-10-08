"""화물 지켜보기 서비스 테스트 (services/watch/watch.py, G5).

DB·카카오·LLM·ShipFinder는 부르지 않는다. user_cargo 표를 흉내 내는 가짜 연결, 판정 함수(assess) 가짜,
카카오 보내기 가짜, 테스트용 열쇠를 쓴다. B/L은 모의값이다(실제 번호 아님).
"""
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from backend.app import crypto
from backend.app.clients.kakao import KakaoError
from backend.app.services.watch import cargo
from backend.app.services.watch import watch as svc
from backend.app.services.watch.kakao import KakaoLinkError

NOW = datetime(2026, 10, 5, 3, tzinfo=timezone.utc)
USER = "user-123"
BL = "MOCKBL20261005"  # 모의 B/L


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("BL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://web.example.com/, http://localhost:3000")


class _Cur:
    def __init__(self, rows=None, rowcount=0):
        self._rows, self.rowcount = rows or [], rowcount

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class FakeConn:
    """user_cargo 한 표를 메모리에 둔다. 문장 앞부분으로 어떤 SQL인지 가른다 (test_kakao_service.FakeConn과 같은 방식)."""

    def __init__(self):
        self.rows: list[dict] = []

    def add(self, bl=BL, user=USER, **over) -> dict:
        row = {"user_id": user, "cargo_key": cargo.cargo_key(bl), "bl_encrypted": crypto.encrypt(bl),
               "bl_masked": "MOC*******1005", "label": None, "bl_type": "HOUSE", "sale_due_date": date(2026, 10, 20),
               "forwarder_eta": None, "voyage_no": None, "vessel_mmsi": 440123456, "last_verdict": "watch",
               "last_checked_at": datetime(2026, 10, 4, tzinfo=timezone.utc), "status": "active", "watch": False,
               "changed_from": None, "changed_at": None, "change_seen": True, **over}
        self.rows.append(row)
        return row

    def row(self, bl=BL, user=USER) -> dict:
        return next(r for r in self.rows if r["user_id"] == user and r["cargo_key"] == cargo.cargo_key(bl))

    def execute(self, sql, params=()):
        q = " ".join(sql.split())
        if q.startswith("SELECT status, watch FROM user_cargo"):
            found = [r for r in self.rows if (r["user_id"], r["cargo_key"]) == tuple(params)]
            return _Cur([(r["status"], r["watch"]) for r in found])
        if q.startswith("SELECT count(*) FROM user_cargo WHERE user_id = %s AND watch AND status = 'active'"):
            return _Cur([(sum(1 for r in self.rows if r["user_id"] == params[0] and r["watch"]
                              and r["status"] == "active"),)])
        if q.startswith("UPDATE user_cargo SET watch = "):
            on = "watch = true" in q
            for r in self.rows:
                if (r["user_id"], r["cargo_key"]) == tuple(params):
                    r["watch"] = on
            return _Cur(rowcount=1)
        if q.startswith("SELECT bl_masked, label, changed_from, last_verdict, changed_at"):
            found = [r for r in self.rows if r["user_id"] == params[0] and not r["change_seen"]]
            found.sort(key=lambda r: r["changed_at"], reverse=True)
            return _Cur([(r["bl_masked"], r["label"], r["changed_from"], r["last_verdict"], r["changed_at"],
                          r.get("last_days_margin"), r.get("last_stage")) for r in found])
        if q.startswith("UPDATE user_cargo SET change_seen = true"):
            found = [r for r in self.rows if r["user_id"] == params[0] and not r["change_seen"]]
            for r in found:
                r["change_seen"] = True
            return _Cur(rowcount=len(found))
        if q.startswith("SELECT count(*) FROM user_cargo WHERE watch AND status = 'active' AND vessel_mmsi IS"):
            want_null = q.endswith("IS NULL")
            return _Cur([(sum(1 for r in self.rows if r["watch"] and r["status"] == "active"
                              and (r["vessel_mmsi"] is None) == want_null),)])
        if q.startswith("SELECT user_id, cargo_key, bl_encrypted"):
            found = [r for r in self.rows if r["watch"] and r["status"] == "active"
                     and ("vessel_mmsi IS NOT NULL" not in q or r["vessel_mmsi"] is not None)]
            found.sort(key=lambda r: (r["last_checked_at"] is not None, r["last_checked_at"] or NOW))
            cols = ("user_id", "cargo_key", "bl_encrypted", "bl_masked", "label", "bl_type", "sale_due_date",
                    "forwarder_eta", "voyage_no", "vessel_mmsi", "last_verdict")
            return _Cur([tuple(r[c] for c in cols) for r in found[:params[0]]])
        if q.startswith("UPDATE user_cargo SET changed_from = %s"):
            old, at, user, key = params
            for r in self.rows:
                if (r["user_id"], r["cargo_key"]) == (user, key):
                    r.update(changed_from=old, changed_at=at, change_seen=False)
            return _Cur(rowcount=1)
        raise AssertionError(f"예상하지 못한 SQL: {q}")


def _resp(verdict, stage="통관진행"):
    """AgentResponse처럼 verdict와 customs.stage_name만 가진 가짜 응답."""
    return SimpleNamespace(verdict=verdict, customs=SimpleNamespace(stage_name=stage))


@pytest.fixture
def upserts(monkeypatch):
    """cargo.upsert_assessment를 가짜로 바꾼다. 마지막 판정을 덮고 반출이면 done으로 옮기는 것만 흉내 낸다."""
    calls = []

    def fake(conn, user_id, request, response, *, released, now=None):
        calls.append({"user_id": user_id, "request": request, "response": response, "released": released, "now": now})
        row = conn.row(request.bl_no, user_id)
        row.update(last_verdict=response.verdict, last_checked_at=now, status="done" if released else "active")
        return True

    monkeypatch.setattr(svc.cargo, "upsert_assessment", fake)
    return calls


@pytest.fixture
def sent(monkeypatch):
    """kakao.send_to_user를 가짜로 바꾼다. 보낸 (user_id, text, link)를 모은다."""
    log = []
    monkeypatch.setattr(svc.kakao, "send_to_user", lambda conn, user_id, text, link: log.append((user_id, text, link)))
    return log


# ── set_watch ──

def test_set_watch_on_and_off():
    conn = FakeConn()
    conn.add()
    assert svc.set_watch(conn, USER, BL, True) is True and conn.row()["watch"] is True
    assert svc.set_watch(conn, USER, BL.lower(), False) is False and conn.row()["watch"] is False  # 소문자도 같은 화물


def test_set_watch_not_saved_when_row_missing():
    with pytest.raises(svc.WatchError) as e:
        svc.set_watch(FakeConn(), USER, BL, True)
    assert e.value.kind == "not_saved"


def test_set_watch_done_cargo_cannot_be_watched():
    conn = FakeConn()
    conn.add(status="done")
    with pytest.raises(svc.WatchError) as e:
        svc.set_watch(conn, USER, BL, True)
    assert e.value.kind == "done" and conn.row()["watch"] is False


def test_set_watch_limit_is_five_per_user():
    conn = FakeConn()
    for i in range(5):
        conn.add(bl=f"MOCKBL2026100{i}", watch=True)
    conn.add()
    conn.add(user="other", watch=True)  # 다른 사용자의 감시는 세지 않는다
    with pytest.raises(svc.WatchError) as e:
        svc.set_watch(conn, USER, BL, True)
    assert e.value.kind == "limit" and conn.row()["watch"] is False
    assert svc.set_watch(conn, USER, "MOCKBL20261000", True) is True  # 이미 켠 것을 다시 켜는 것은 한도에 걸리지 않는다
    svc.set_watch(conn, USER, "MOCKBL20261000", False)
    assert svc.set_watch(conn, USER, BL, True) is True  # 하나 끄면 다시 켤 수 있다


def test_set_watch_limit_ignores_finished_cargo():
    conn = FakeConn()
    for i in range(5):
        conn.add(bl=f"MOCKBL2026100{i}", watch=True, status="done")  # 반출 끝난 화물은 자리를 차지하지 않는다
    conn.add()
    assert svc.set_watch(conn, USER, BL, True) is True


def test_set_watch_off_is_always_fine():
    conn = FakeConn()
    assert svc.set_watch(conn, USER, BL, False) is False  # 줄이 없어도
    conn.add(status="done", watch=True)
    assert svc.set_watch(conn, USER, BL, False) is False and conn.row()["watch"] is False  # 끝난 화물도


def test_set_watch_without_key(monkeypatch):
    monkeypatch.delenv("BL_ENCRYPTION_KEY")
    with pytest.raises(svc.WatchError) as e:
        svc.set_watch(FakeConn(), USER, BL, True)
    assert e.value.kind == "no_key"
    assert svc.set_watch(FakeConn(), USER, BL, False) is False  # 끄기는 열쇠가 없어도 오류가 아니다


# ── watch_state ──

def test_watch_state():
    conn = FakeConn()
    assert svc.watch_state(conn, USER, BL) == {"saved": False, "watch": False}
    conn.add()
    assert svc.watch_state(conn, USER, BL) == {"saved": True, "watch": False}
    conn.row()["watch"] = True
    assert svc.watch_state(conn, USER, BL) == {"saved": True, "watch": True}
    conn.row()["status"] = "done"  # 반출이 끝나면 더 지켜보지 않는다
    assert svc.watch_state(conn, USER, BL) == {"saved": True, "watch": False}


def test_watch_state_without_key(monkeypatch):
    monkeypatch.delenv("BL_ENCRYPTION_KEY")
    assert svc.watch_state(FakeConn(), USER, BL) == {"saved": False, "watch": False}


# ── pending_changes / mark_seen ──

def test_pending_changes_and_mark_seen():
    conn = FakeConn()
    conn.add(bl="MOCKBL20261001", label="고추", last_verdict="act", changed_from="watch", change_seen=False,
             changed_at=datetime(2026, 10, 4, tzinfo=timezone.utc))
    conn.add(bl="MOCKBL20261002", last_verdict="fine", changed_from="act", change_seen=False, changed_at=NOW)
    conn.add(bl="MOCKBL20261003")  # 변화 없음
    conn.add(bl="MOCKBL20261004", user="other", change_seen=False, changed_at=NOW)  # 남의 변화
    changes = svc.pending_changes(conn, USER)
    assert [c["from_verdict"] for c in changes] == ["act", "watch"]  # 최근 것부터
    assert changes[1] == {"bl_masked": "MOC*******1005", "label": "고추", "from_verdict": "watch",
                          "to_verdict": "act", "changed_at": "2026-10-04T00:00:00+00:00", "reason": None}  # 저장된 값이 없으면 이유도 없다
    assert svc.mark_seen(conn, USER) == 2
    assert svc.pending_changes(conn, USER) == [] and svc.mark_seen(conn, USER) == 0
    assert conn.row("MOCKBL20261004", "other")["change_seen"] is False  # 남의 줄은 그대로


def test_pending_changes_reason_from_stored_margin_and_stage():
    """이유는 화물 표에 저장된 마지막 여유 일수·통관 단계만으로 코드가 쓴다. 한쪽만 있어도 있는 것만 쓴다."""
    conn = FakeConn()
    conn.add(bl="MOCKBL20261001", change_seen=False, changed_at=NOW, last_days_margin=-2, last_stage="수입신고")
    conn.add(bl="MOCKBL20261002", change_seen=False, changed_at=datetime(2026, 10, 4, tzinfo=timezone.utc), last_days_margin=3)
    reasons = [c["reason"] for c in svc.pending_changes(conn, USER)]
    assert reasons == ["마지막 확인 기준 판매 예정일보다 2일 늦음, 통관 수입신고", "마지막 확인 기준 여유 3일"]


# ── run_watch ──

def _watched(conn, bl=BL, **over):
    return conn.add(bl=bl, watch=True, **over)


def test_unchanged_records_no_change_but_refreshes(upserts, sent):
    conn = FakeConn()
    _watched(conn, last_verdict="watch")
    out = svc.run_watch(conn, now=NOW, assess=lambda req, mem: _resp("watch"))
    assert out == {"checked": 1, "changed": 0, "notified": 0, "failed": 0, "unjudged": 0}
    row = conn.row()
    assert row["changed_from"] is None and row["change_seen"] is True and sent == []
    assert row["last_checked_at"] == NOW and len(upserts) == 1  # 마지막 판정은 늘 갱신한다


def test_changed_records_change_and_notifies(upserts, sent):
    conn = FakeConn()
    _watched(conn, label="고추", last_verdict="watch")
    out = svc.run_watch(conn, now=NOW, assess=lambda req, mem: _resp("act"))
    assert out == {"checked": 1, "changed": 1, "notified": 1, "failed": 0, "unjudged": 0}
    row = conn.row()
    assert (row["changed_from"], row["changed_at"], row["change_seen"], row["last_verdict"]) == ("watch", NOW, False, "act")
    [(user_id, text, link)] = sent
    assert user_id == USER and link == "https://web.example.com/"
    assert text == ("[Marvia] 고추 화물 판정이 '주의'에서 '긴급'(으)로 바뀌었습니다. "
                    "Marvia에서 이유와 할 일을 확인하세요.")
    assert BL not in text


def test_message_uses_masked_number_without_label(upserts, sent):
    conn = FakeConn()
    _watched(conn, last_verdict="act")
    svc.run_watch(conn, now=NOW, assess=lambda req, mem: _resp("fine"))
    assert "MOC*******1005" in sent[0][1] and BL not in sent[0][1]


def test_request_is_built_like_a_user_lookup(upserts, sent):
    """저장된 값으로 같은 AgentRequest를 만들고, 기억 블록(memory)은 넣지 않는다."""
    conn = FakeConn()
    _watched(conn, bl_type="MASTER", forwarder_eta=date(2026, 10, 9), voyage_no="V12")
    seen = []
    svc.run_watch(conn, now=NOW, assess=lambda req, mem: seen.append((req, mem)) or _resp("watch"))
    [(req, mem)] = seen
    assert (req.bl_no, req.bl_type, req.sale_due_date, req.forwarder_eta, req.voyage_no, req.resolved_mmsi) == \
        (BL, "MASTER", date(2026, 10, 20), date(2026, 10, 9), "V12", 440123456)
    assert req.session_id == "watch-20261005" and mem is None
    assert upserts[0]["request"] is req and upserts[0]["now"] == NOW and upserts[0]["user_id"] == USER


def test_first_judgement_without_previous_verdict_is_not_a_change(upserts, sent):
    conn = FakeConn()
    _watched(conn, last_verdict=None)
    out = svc.run_watch(conn, now=NOW, assess=lambda req, mem: _resp("act"))
    assert out["changed"] == 0 and sent == [] and conn.row()["last_verdict"] == "act"


def test_empty_verdict_keeps_previous_baseline(upserts, sent):
    """판정이 없는 결과(되묻기·일시 실패)는 화물 표를 덮지 않는다. 기준 등급이 지워지면 다음 변화를 못 잡는다."""
    conn = FakeConn()
    _watched(conn, last_verdict="watch")
    out = svc.run_watch(conn, now=NOW, assess=lambda req, mem: _resp(None))
    assert out["unjudged"] == 1 and out["failed"] == 0 and out["changed"] == 0
    assert upserts == [] and conn.row()["last_verdict"] == "watch"


def test_not_linked_is_silent(upserts, monkeypatch):
    conn = FakeConn()
    _watched(conn, last_verdict="watch")
    failures = []
    monkeypatch.setattr(svc, "log_failure", lambda stage, error: failures.append((stage, error)))

    def not_linked(*a):
        raise KakaoLinkError("not_linked")

    monkeypatch.setattr(svc.kakao, "send_to_user", not_linked)
    out = svc.run_watch(conn, now=NOW, assess=lambda req, mem: _resp("act"))
    assert (out["changed"], out["notified"], out["failed"]) == (1, 0, 0)
    assert failures == []  # 조용히 넘어간다
    assert conn.row()["change_seen"] is False  # 화면 띠용 기록은 남는다


@pytest.mark.parametrize("error", [KakaoLinkError("relink"), KakaoLinkError("no_key"), KakaoError("no_consent"),
                                   KakaoError("failed")])
def test_other_notify_errors_log_kind_only(upserts, monkeypatch, error):
    conn = FakeConn()
    _watched(conn, last_verdict="watch")
    failures = []
    monkeypatch.setattr(svc, "log_failure", lambda stage, kind: failures.append((stage, kind)))

    def boom(*a):
        raise error

    monkeypatch.setattr(svc.kakao, "send_to_user", boom)
    out = svc.run_watch(conn, now=NOW, assess=lambda req, mem: _resp("act"))
    assert (out["changed"], out["notified"], out["failed"]) == (1, 0, 0)  # 알림 실패는 화물 실패가 아니다
    assert failures == [("watch_notify", error.kind)]


def test_one_cargo_failing_does_not_stop_others(upserts, sent, monkeypatch):
    conn = FakeConn()
    for i, day in enumerate((1, 2, 3)):
        _watched(conn, bl=f"MOCKBL2026100{i}", last_checked_at=datetime(2026, 10, day, tzinfo=timezone.utc))
    failures = []
    monkeypatch.setattr(svc, "log_failure", lambda stage, kind: failures.append((stage, kind)))

    def assess(req, mem):
        if req.bl_no == "MOCKBL20261000":
            raise RuntimeError(f"upstream said {req.bl_no}")  # 예외 글에 B/L이 있어도 로그에는 종류만 간다
        return _resp("act")

    out = svc.run_watch(conn, now=NOW, assess=assess)
    assert (out["checked"], out["failed"], out["changed"]) == (2, 1, 2)
    assert failures == [("watch_cargo", "RuntimeError")]
    assert "MOCKBL" not in str(failures)


def test_cargo_with_unreadable_bl_counts_as_failed(upserts, sent, monkeypatch):
    conn = FakeConn()
    _watched(conn, bl_encrypted=None)
    failures = []
    monkeypatch.setattr(svc, "log_failure", lambda stage, kind: failures.append((stage, kind)))
    out = svc.run_watch(conn, now=NOW, assess=lambda req, mem: pytest.fail("원문 없이 조회하면 안 된다"))
    assert out["failed"] == 1 and failures == [("watch_cargo", "no_bl")]


def test_limit_and_oldest_first(upserts, sent):
    conn = FakeConn()
    for i in range(7):
        _watched(conn, bl=f"MOCKBL2026100{i}", last_checked_at=datetime(2026, 10, 7 - i, tzinfo=timezone.utc))
    _watched(conn, bl="MOCKBL20261009", last_checked_at=None)  # 한 번도 안 본 줄이 가장 먼저
    conn.add(bl="MOCKBL20261008", watch=False, last_checked_at=None)  # 안 지켜보는 줄은 안 본다
    conn.add(bl="MOCKBL20261007", watch=True, status="done", last_checked_at=None)  # 끝난 줄도 안 본다
    seen = []
    out = svc.run_watch(conn, now=NOW, assess=lambda req, mem: seen.append(req.bl_no) or _resp("watch"))
    assert out["checked"] == 5
    assert seen == ["MOCKBL20261009", "MOCKBL20261006", "MOCKBL20261005", "MOCKBL20261004", "MOCKBL20261003"]
    assert svc.run_watch(conn, limit=2, now=NOW, assess=lambda req, mem: _resp("watch"))["checked"] == 2


def test_released_cargo_becomes_done(upserts, sent):
    conn = FakeConn()
    _watched(conn, last_verdict="watch")
    out = svc.run_watch(conn, now=NOW, assess=lambda req, mem: _resp("fine", stage="반출신고"))
    assert upserts[0]["released"] is True and conn.row()["status"] == "done"
    assert out["changed"] == 1  # 주의 → 순항도 등급이 바뀐 것이다
    # 다음 실행부터는 끝난 화물이라 보지 않는다
    assert svc.run_watch(conn, now=NOW, assess=lambda req, mem: pytest.fail("끝난 화물")) ["checked"] == 0


def test_default_assess_is_the_user_lookup_path(upserts, sent, monkeypatch):
    """assess를 안 주면 조회 화면과 같은 routers.agent._assess를 부른다 (판정 길이 하나여야 두 답이 어긋나지 않는다)."""
    from backend.app.routers import agent

    conn = FakeConn()
    _watched(conn)
    seen = []
    monkeypatch.setattr(agent, "_assess", lambda req, mem=None: seen.append((req.bl_no, mem)) or _resp("watch"))
    assert svc.run_watch(conn, now=NOW)["checked"] == 1 and seen == [(BL, None)]


# ── 하루 토큰 한도. 재판정도 그 사용자의 LLM 사용량이다 ──

def test_rejudge_is_scoped_to_the_cargo_owner(upserts, sent, monkeypatch):
    """session_scope에 user_id를 넘겨 토큰이 그 사람 몫으로 쌓인다 (services/account/quota.py owner_var)."""
    from backend.app.services.account import quota
    conn = FakeConn()
    _watched(conn, last_verdict="watch")
    owners = []
    svc.run_watch(conn, now=NOW, assess=lambda req, mem: owners.append(quota.owner_var.get()) or _resp("watch"))
    assert owners == [f"user:{USER}"]


def test_rejudge_skipped_when_owner_is_over_quota(upserts, sent, monkeypatch):
    from backend.app.services.account import quota
    conn = FakeConn()
    _watched(conn, last_verdict="watch")
    failures = []
    monkeypatch.setattr(svc, "log_failure", lambda stage, kind: failures.append((stage, kind)))

    def over(session_id, user_id):
        raise quota.QuotaExceeded(user_id)

    monkeypatch.setattr(quota, "ensure_allowed", over)
    out = svc.run_watch(conn, now=NOW, assess=lambda req, mem: pytest.fail("한도를 다 쓴 사람의 화물은 재판정하지 않는다"))
    assert out["failed"] == 1 and failures == [("watch_cargo", "quota")] and upserts == []


def test_known_vessel_only_skips_cargo_without_vessel(upserts, sent):
    """워커 예산 안에서 돌 때(known_vessel_only)는 배를 모르는 화물을 다시 판정하지 않고 skipped_no_vessel로 센다.
    배를 모르면 후보 검색으로 ShipFinder를 최대 11회 써서 화물당 1회로 떼어 둔 예산을 깬다."""
    conn = FakeConn()
    _watched(conn, bl="MOCKBL20261001", vessel_mmsi=None, last_checked_at=None)
    _watched(conn, bl="MOCKBL20261002", vessel_mmsi=440999001)
    seen = []
    out = svc.run_watch(conn, now=NOW, known_vessel_only=True,
                        assess=lambda req, mem: seen.append((req.bl_no, req.resolved_mmsi)) or _resp("watch"))
    assert seen == [("MOCKBL20261002", 440999001)]
    assert out["checked"] == 1 and out["skipped_no_vessel"] == 1
    assert svc.known_vessel_due_count(conn) == 1


def test_default_run_watch_still_checks_cargo_without_vessel(upserts, sent):
    """python -m worker.watch(예산 없음)는 지금처럼 배를 모르는 화물도 다시 판정한다. 결과 모양도 그대로다."""
    conn = FakeConn()
    _watched(conn, vessel_mmsi=None)
    out = svc.run_watch(conn, now=NOW, assess=lambda req, mem: _resp("watch"))
    assert out == {"checked": 1, "changed": 0, "notified": 0, "failed": 0, "unjudged": 0}
