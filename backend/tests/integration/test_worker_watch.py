"""지켜보는 화물 재판정 실행기 테스트 (worker/watch.py, worker/run.py의 WATCH_ENABLED, G5).

DB·판정·수집은 부르지 않는다. connect와 run_watch를 가짜로 끼운다.
"""
import json

import pytest

import worker.run as run
import worker.watch as watch_cli


class FakeConn:
    def __init__(self):
        self.closed = False

    def execute(self, *a, **k):
        raise AssertionError("수집 단계는 가짜로 바꿨다")

    def close(self):
        self.closed = True


@pytest.fixture
def collect_stubs(monkeypatch):
    """run_once에서 수집·삭제 단계를 모두 가짜로 바꾼다. shipfinder_calls=0으로 부르므로 ShipFinder는 안 쓴다."""
    conn = FakeConn()
    monkeypatch.setattr(run, "connect", lambda: conn)
    monkeypatch.setattr(run, "apply_migrations", lambda c: [])
    monkeypatch.setattr(run, "collect_port", lambda c, mof: {"reports": []})
    monkeypatch.setattr(run, "MofClient", lambda: None)
    monkeypatch.setattr(run, "purge_positions", lambda c: 0)
    monkeypatch.setattr(run, "purge_old_queries", lambda c: 0)
    monkeypatch.setattr(run, "purge_done_cargo", lambda c: 0)
    monkeypatch.setattr(run, "purge_old_conversations", lambda c: 0)
    monkeypatch.setattr(run, "purge_watch_positions", lambda c: 0)
    # 배를 아는 지켜보는 화물 수. 기본은 RUN_LIMIT보다 많다고 둔다 (재판정 몫 예산이 상한까지 잡히게)
    monkeypatch.setattr(run, "known_vessel_due_count", lambda c: 99)
    return conn


def test_watch_off_by_default_is_not_called(collect_stubs, monkeypatch):
    monkeypatch.delenv("WATCH_ENABLED", raising=False)
    monkeypatch.setattr(run, "run_watch", lambda conn, **k: pytest.fail("꺼져 있으면 부르지 않는다"))
    summary = run.run_once(0)
    assert "watch" not in summary and collect_stubs.closed


@pytest.mark.parametrize("value", ["", "off", "false", "0"])
def test_watch_off_values_are_not_called(collect_stubs, monkeypatch, value):
    monkeypatch.setenv("WATCH_ENABLED", value)
    monkeypatch.setattr(run, "run_watch", lambda conn, **k: pytest.fail("꺼져 있으면 부르지 않는다"))
    assert "watch" not in run.run_once(0)


@pytest.mark.parametrize("value", ["on", "ON", "true", "1"])
def test_watch_on_runs_after_collection(collect_stubs, monkeypatch, value):
    monkeypatch.setenv("WATCH_ENABLED", value)
    monkeypatch.setattr(run, "run_watch", lambda conn, **k: {"checked": 2})
    summary = run.run_once(0)
    assert summary["watch"] == {"checked": 2} and "port" in summary  # 수집 결과도 그대로


def _sf_stubs(monkeypatch, seen: dict):
    """ShipFinder 수집 단계를 가짜로 바꾸고, 각 단계가 받은 남은 예산을 적는다."""
    monkeypatch.setattr(run, "ShipFinderClient", lambda: None)
    for name in ("collect_watch_positions", "collect_positions", "select_targets"):
        def stub(*a, _name=name):
            budget = a[-1]
            seen[_name] = budget.remaining
            while budget.take():  # 수집이 남은 예산을 다 쓴다고 본다
                pass
            return {}
        monkeypatch.setattr(run, name, stub)


def test_watch_budget_is_reserved_before_collection(collect_stubs, monkeypatch):
    """재판정은 Budget 밖에서(api의 MCP로) ShipFinder를 부르므로 화물 수 x 화물당 호출 수만큼 먼저 떼어 둔다.
    합이 실행 예산을 넘지 않는다. 워커 재판정은 배를 아는 화물만 고른다."""
    monkeypatch.setenv("WATCH_ENABLED", "on")
    seen: dict = {}
    _sf_stubs(monkeypatch, seen)
    monkeypatch.setattr(run, "run_watch", lambda conn, limit, known_vessel_only: seen.update(
        watch_limit=limit, known=known_vessel_only) or {"checked": limit})
    summary = run.run_once(12)
    cost = run.SHIPFINDER_CALLS_PER_KNOWN_VESSEL
    assert seen["watch_limit"] == run.RUN_LIMIT and seen["known"] is True
    assert seen["collect_watch_positions"] == 12 - run.RUN_LIMIT * cost  # 수집은 남은 예산으로
    assert summary["shipfinder_calls_used"] == 12


def test_watch_budget_smaller_than_run_limit(collect_stubs, monkeypatch):
    """실행 예산이 RUN_LIMIT보다 작으면 그만큼만 재판정한다. 예산 0이면 재판정도 0건이다."""
    monkeypatch.setenv("WATCH_ENABLED", "on")
    seen: dict = {}
    _sf_stubs(monkeypatch, seen)
    monkeypatch.setattr(run, "run_watch", lambda conn, limit, **k: seen.update(watch_limit=limit) or {"checked": limit})
    run.run_once(2)
    assert seen["watch_limit"] == 2 and seen["collect_watch_positions"] == 0
    run.run_once(0)
    assert seen["watch_limit"] == 0


def test_watch_budget_only_for_cargo_with_known_vessel(collect_stubs, monkeypatch):
    """배를 아는 지켜보는 화물이 2건이면 2건 몫만 떼고 나머지는 수집에 쓴다. 0건이면 하나도 떼지 않는다."""
    monkeypatch.setenv("WATCH_ENABLED", "on")
    seen: dict = {}
    _sf_stubs(monkeypatch, seen)
    monkeypatch.setattr(run, "run_watch", lambda conn, limit, **k: seen.update(watch_limit=limit) or {"checked": limit})
    monkeypatch.setattr(run, "known_vessel_due_count", lambda c: 2)
    run.run_once(12)
    assert seen["watch_limit"] == 2 and seen["collect_watch_positions"] == 12 - 2 * run.SHIPFINDER_CALLS_PER_KNOWN_VESSEL
    monkeypatch.setattr(run, "known_vessel_due_count", lambda c: 0)
    run.run_once(12)
    assert seen["watch_limit"] == 0 and seen["collect_watch_positions"] == 12


def test_purges_watch_positions(collect_stubs, monkeypatch):
    """감시 위치(watch_positions)도 실행마다 정리한다 (migrations/021)."""
    monkeypatch.delenv("WATCH_ENABLED", raising=False)
    monkeypatch.setattr(run, "purge_watch_positions", lambda c: 3)
    assert run.run_once(0)["watch_positions_purged"] == 3


def test_watch_off_keeps_whole_budget_for_collection(collect_stubs, monkeypatch):
    monkeypatch.delenv("WATCH_ENABLED", raising=False)
    seen: dict = {}
    _sf_stubs(monkeypatch, seen)
    run.run_once(12)
    assert seen["collect_watch_positions"] == 12


def test_watch_failure_does_not_break_collection(collect_stubs, monkeypatch):
    monkeypatch.setenv("WATCH_ENABLED", "on")

    def boom(conn, **k):
        raise RuntimeError("secret detail")

    monkeypatch.setattr(run, "run_watch", boom)
    summary = run.run_once(0)
    assert summary["watch"] == {"error": "RuntimeError"} and "port" in summary and collect_stubs.closed


# ── python -m worker.watch ──

def test_cli_once_prints_one_json_line(monkeypatch, capsys):
    conn = FakeConn()
    monkeypatch.setattr(watch_cli, "connect", lambda: conn)
    monkeypatch.setattr(watch_cli, "apply_migrations", lambda c: [])
    monkeypatch.setattr(watch_cli, "run_watch", lambda c: {"checked": 1, "changed": 0, "notified": 0, "failed": 0,
                                                           "unjudged": 0})
    assert watch_cli.main(["--once"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1
    out = json.loads(lines[0])
    assert out["event"] == "watch_done" and out["checked"] == 1 and "at" in out and conn.closed


def test_cli_without_once_does_nothing(monkeypatch, capsys):
    monkeypatch.setattr(watch_cli, "connect", lambda: pytest.fail("--once 없이는 연결하지 않는다"))
    assert watch_cli.main([]) == 0
    assert json.loads(capsys.readouterr().out)["event"] == "watch_off"
