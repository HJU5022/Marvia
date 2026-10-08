"""수집 워커 실행 진입점 (작업 D1, SDD 5.10). compose의 worker 서비스가 이걸 띄운다.

    python -m worker.run --once                      # 한 번만 돈다. 개발 중 확인용
    python -m worker.run --once --shipfinder-calls 0 # 해수부만 받고 ShipFinder는 안 부른다
    python -m worker.run                             # WORKER_SCHEDULE=on일 때만 주기 실행
    WATCH_ENABLED=on python -m worker.run --once     # 수집 뒤에 지켜보는 화물도 다시 판정 (python -m worker.watch --once는 그것만)

스케줄러는 기본 꺼져 있다. ShipFinder 스타터 키가 하루 50회라서 개발 중에 계속 돌면
테스트할 몫이 남지 않는다. 켜면 WORKER_INTERVAL_HOURS마다 돈다.
주기 6시간, 한 번 실행에 ShipFinder 12회가 기본이다. 하루 4회 x 12 = 48회로 한도 50 안이고,
추적 대상 12척(collector.MAX_TARGETS)이 매 실행 위치를 한 번씩 받는다.
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
from backend.app.db import (apply_migrations, connect, purge_done_cargo, purge_old_conversations, purge_old_queries,
                            purge_watch_positions)
from backend.app.services.watch.watch import RUN_LIMIT, SHIPFINDER_CALLS_PER_KNOWN_VESSEL, known_vessel_due_count, run_watch
from worker.collector import Budget, collect_port, collect_positions, collect_watch_positions, purge_positions, select_targets

DEFAULT_INTERVAL_HOURS = 6.0  # SDD 5.10의 3시간에서 바꿨다 (위키 "문서와 달라진 점")
DEFAULT_SHIPFINDER_CALLS = 12  # 위 설명 참고. 하루 한도 50회


def _log(event: str, **fields) -> None:
    """한 줄 JSON 로그. docker compose logs worker로 본다."""
    print(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "event": event, **fields},
                     ensure_ascii=False, default=str), flush=True)


def watch_enabled() -> bool:
    """WATCH_ENABLED가 켜졌나. 기본은 꺼짐이다 (G5). 켜면 수집 뒤에 지켜보는 화물을 다시 판정한다.
    다시 판정은 ShipFinder와 LLM을 쓰므로 개발 중에 저절로 돌지 않게 WORKER_SCHEDULE처럼 명시해야 켜진다."""
    return os.environ.get("WATCH_ENABLED", "off").strip().lower() in ("on", "true", "1")


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
    # 지켜보기 재판정(run_watch)도 화물마다 ShipFinder를 부르는데 Budget을 거치지 않는다 (MCP·판정 경로).
    # 그래서 재판정할 화물 몫의 예산을 먼저 떼어 두고, 수집은 남은 예산으로 한다. 안 그러면 한 번 실행이
    # WORKER_SHIPFINDER_CALLS_PER_RUN을 넘어 하루 50회 한도를 깰 수 있다.
    # 재판정은 api 프로세스의 MCP(/mcp)를 거쳐 api 쪽 ShipFinderClient로 부른다. 이 워커의 ShipFinderClient 캐시와는
    # 프로세스가 달라 아래 collect_watch_positions가 받아 둔 위치를 다시 쓰지 못한다. 화물마다 실제로 호출된다고 센다.
    # 배를 아는 화물만 다시 판정한다(known_vessel_only): 그 경로는 화물당 SHIPFINDER_CALLS_PER_KNOWN_VESSEL회(위치 1회)다.
    # 배를 모르는 화물은 후보 검색으로 최대 11회를 써서 예산으로 묶기 어렵다 (services/watch/watch.py 설명)
    watch_limit = 0
    if watch_enabled():
        try:
            due = min(known_vessel_due_count(conn), RUN_LIMIT)
        except Exception:  # 017 칸이 없는 DB 등. 아래 run_watch도 같은 이유로 실패해 결과에 남는다
            due = 0
        watch_limit = min(due, budget.remaining // SHIPFINDER_CALLS_PER_KNOWN_VESSEL)
        budget.remaining -= watch_limit * SHIPFINDER_CALLS_PER_KNOWN_VESSEL
    if shipfinder_calls > 0:
        try:
            sf = ShipFinderClient()
            # 사용자 화물 배(감시·지도)를 먼저 받는다. 사용자가 보는 화면이라 연구용 대상보다 앞선다 (docs/specs/cargo-watch.md)
            # 결과 키는 watch_positions: 아래 run_watch(재판정)가 "watch" 키를 쓰므로 겹치면 한쪽 결과가 사라진다
            summary["watch_positions"] = collect_watch_positions(conn, sf, budget)
            # 위치를 먼저 받고, 남은 예산으로 대상을 늘린다. 이미 고른 배의 기록이 끊기지 않게 하려는 순서다
            summary["positions"] = collect_positions(conn, sf, budget)
            summary["targets"] = select_targets(conn, reports, sf, budget)
        except ShipFinderError as e:
            summary["shipfinder"] = {"error": e.to_dict()}
    summary["shipfinder_calls_used"] = shipfinder_calls - budget.remaining
    summary["positions_purged"] = purge_positions(conn)  # 입항 30일 지난 위치 기록 삭제 (migrations/002)
    summary["queries_purged"] = purge_old_queries(conn)  # 90일 지난 조회 기록 삭제 (migrations/008)
    summary["done_cargo_purged"] = purge_done_cargo(conn)  # 반출 3년 지난 끝난 화물과 그 메모 삭제 (migrations/015)
    summary["conversations_purged"] = purge_old_conversations(conn)  # 90일 지난 대화 목록 삭제 (migrations/018)
    summary["watch_positions_purged"] = purge_watch_positions(conn)  # 안 지켜보는 배의 30일 지난 감시 위치 삭제 (migrations/021)
    if watch_enabled():
        try:
            # 지켜보는 화물 재판정 (services/watch/watch.py). 떼어 둔 예산만큼, 배를 아는 화물만
            summary["watch"] = run_watch(conn, limit=watch_limit, known_vessel_only=True)
        except Exception as e:  # 재판정이 실패해도 위에서 끝낸 수집 결과는 그대로 남긴다
            summary["watch"] = {"error": type(e).__name__}
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
