"""지켜보는 화물 재판정 실행기 테스트 (worker/watch.py, worker/run.py의 WATCH_ENABLED, G5 10-05 결정).

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
    return conn


def test_watch_off_by_default_is_not_called(collect_stubs, monkeypatch):
    monkeypatch.delenv("WATCH_ENABLED", raising=False)
    monkeypatch.setattr(run, "run_watch", lambda conn: pytest.fail("꺼져 있으면 부르지 않는다"))
    summary = run.run_once(0)
    assert "watch" not in summary and collect_stubs.closed


@pytest.mark.parametrize("value", ["", "off", "false", "0"])
def test_watch_off_values_are_not_called(collect_stubs, monkeypatch, value):
    monkeypatch.setenv("WATCH_ENABLED", value)
    monkeypatch.setattr(run, "run_watch", lambda conn: pytest.fail("꺼져 있으면 부르지 않는다"))
    assert "watch" not in run.run_once(0)


@pytest.mark.parametrize("value", ["on", "ON", "true", "1"])
def test_watch_on_runs_after_collection(collect_stubs, monkeypatch, value):
    monkeypatch.setenv("WATCH_ENABLED", value)
    monkeypatch.setattr(run, "run_watch", lambda conn: {"checked": 2})
    summary = run.run_once(0)
    assert summary["watch"] == {"checked": 2} and "port" in summary  # 수집 결과도 그대로


def test_watch_failure_does_not_break_collection(collect_stubs, monkeypatch):
    monkeypatch.setenv("WATCH_ENABLED", "on")

    def boom(conn):
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
