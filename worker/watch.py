"""지켜보는 화물 재판정 실행 진입점 (G5 등록·감시·알림, docs/Marvia_개발_작업_리스트.md).

    python -m worker.watch --once    # 한 번만 돈다. 결과를 한 줄 JSON으로 찍는다

하는 일은 services/watch/watch.run_watch 한 번 부르기뿐이다. 규칙(5건 상한, 같은 판정 길, 알림)은 거기에 있다.
수집 워커(worker/run.py)와 따로 둔 이유: 시연할 때 수집 없이 이것만 돌리려는 것이다.
api 컨테이너 안에서 `docker compose exec api python -m worker.watch --once`로 부르면
api 이미지의 MCP_URL(127.0.0.1:8000)이 자기 자신을 가리켜 그대로 돈다 (Dockerfile app 스테이지).
주기 실행은 worker/run.py가 WATCH_ENABLED=on일 때 수집 뒤에 같은 함수를 부른다. 여기에는 스케줄러를 두지 않는다.
ShipFinder·LLM을 실제로 쓰므로 --once를 줄 때만 돈다.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from backend.app.db import apply_migrations, connect
from backend.app.services.watch.watch import run_watch


def _log(event: str, **fields) -> None:
    """한 줄 JSON 로그 (worker/run.py와 같은 모양)."""
    print(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "event": event, **fields},
                     ensure_ascii=False, default=str), flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Marvia 지켜보는 화물 재판정")
    parser.add_argument("--once", action="store_true", help="한 번만 재판정하고 끝낸다")
    args = parser.parse_args(argv)
    if not args.once:
        _log("watch_off", message="한 번 돌리려면 --once. 주기 실행은 worker.run의 WATCH_ENABLED=on")
        return 0

    conn = connect()
    try:
        apply_migrations(conn)  # 017 칸이 없는 DB에서도 돌게 한다 (worker/run.py와 같다)
        _log("watch_done", **run_watch(conn))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
