"""수집 워커 실행 진입점 (작업 D1, SDD 5.10). compose의 worker 서비스가 이걸 띄운다.

    python -m worker.run --once                      # 한 번만 돈다. 개발 중 확인용
    python -m worker.run --once --shipfinder-calls 0 # 해수부만 받고 ShipFinder는 안 부른다
    python -m worker.run                             # WORKER_SCHEDULE=on일 때만 주기 실행

스케줄러는 기본 꺼져 있다 (09-23 결정). ShipFinder 스타터 키가 하루 50회라서 개발 중에 계속 돌면
테스트할 몫이 남지 않는다. 켜면 WORKER_INTERVAL_HOURS마다 돈다.
한 번 실행에 쓰는 ShipFinder 호출 수 기본값 6은 3시간 주기 하루 8회 x 6 = 48회로 한도 50 안에 들게 잡은 값이다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

from backend.app.clients.mof import MofClient, MofError
from backend.app.clients.shipfinder import ShipFinderClient, ShipFinderError
from backend.app.db import apply_migrations, connect
from worker.collector import Budget, collect_port, collect_positions, select_targets

DEFAULT_INTERVAL_HOURS = 3.0  # SDD 5.10 "주기 3시간"
DEFAULT_SHIPFINDER_CALLS = 6  # 위 설명 참고. 하루 한도 50회


def _log(event: str, **fields) -> None:
    """한 줄 JSON 로그. docker compose logs worker로 본다."""
    print(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "event": event, **fields},
                     ensure_ascii=False, default=str), flush=True)


def run_once(shipfinder_calls: int) -> dict:
    """한 번 수집한다. 한 API가 실패해도 나머지는 계속 받는다 (SDD 8절: 실패하면 받을 수 있는 것만)."""
    conn = connect()
    applied = apply_migrations(conn)
    if applied:
        _log("migrations_applied", files=applied)

    summary: dict = {}
    reports = []
    try:
        port = collect_port(conn, MofClient())
        reports = port.pop("reports")
        summary["port"] = port
    except MofError as e:
        summary["port"] = {"error": e.to_dict()}

    budget = Budget(shipfinder_calls)
    if shipfinder_calls > 0:
        try:
            sf = ShipFinderClient()
            # 위치를 먼저 받고, 남은 예산으로 대상을 늘린다. 이미 고른 배의 기록이 끊기지 않게 하려는 순서다
            summary["positions"] = collect_positions(conn, sf, budget)
            summary["targets"] = select_targets(conn, reports, sf, budget)
        except ShipFinderError as e:
            summary["shipfinder"] = {"error": e.to_dict()}
    summary["shipfinder_calls_used"] = shipfinder_calls - budget.remaining
    conn.close()
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Marvia 수집 워커")
    parser.add_argument("--once", action="store_true", help="한 번만 수집하고 끝낸다")
    parser.add_argument("--shipfinder-calls", type=int,
                        default=int(os.environ.get("WORKER_SHIPFINDER_CALLS_PER_RUN", DEFAULT_SHIPFINDER_CALLS)),
                        help="이번 실행에 쓸 ShipFinder 호출 수 (하루 한도 50회)")
    args = parser.parse_args(argv)

    if args.once:
        _log("run_done", **run_once(args.shipfinder_calls))
        return 0

    if os.environ.get("WORKER_SCHEDULE", "off").lower() != "on":
        _log("schedule_off", message="WORKER_SCHEDULE=on일 때만 주기 실행한다. 한 번 돌리려면 --once")
        return 0

    interval = float(os.environ.get("WORKER_INTERVAL_HOURS", DEFAULT_INTERVAL_HOURS)) * 3600
    _log("schedule_on", interval_hours=interval / 3600, shipfinder_calls=args.shipfinder_calls)
    while True:
        try:
            _log("run_done", **run_once(args.shipfinder_calls))
        except Exception as e:  # 한 번 실패해도 다음 주기는 돈다. DB가 잠깐 끊긴 경우 등
            _log("run_failed", error=f"{type(e).__name__}: {e}")
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
