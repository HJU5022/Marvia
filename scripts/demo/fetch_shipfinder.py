"""ShipFinder 실제 호출 확인 스크립트 (손으로 돌린다).

응답 원본은 레포에 커밋하지 않는다 (CLAUDE.md, ShipFinder 이용 조건).
저장 위치는 .local/ 이며 .gitignore에 있다.

    python scripts/demo/fetch_shipfinder.py <MMSI>             # 위치 조회
    python scripts/demo/fetch_shipfinder.py --search <선명>    # 선박 검색
"""
import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from backend.app.clients.shipfinder import ShipFinderClient, ShipFinderError

OUT_DIR = Path(".local/shipfinder")


def main() -> None:
    parser = argparse.ArgumentParser(description="ShipFinder 실제 호출")
    parser.add_argument("target", help="MMSI 또는 검색어")
    parser.add_argument("--search", action="store_true", help="선박 검색으로 조회")
    parser.add_argument("--save", action="store_true", help="응답을 .local/에 저장")
    args = parser.parse_args()

    load_dotenv(".env")
    if not os.environ.get("SHIPFINDER_KEY"):
        raise SystemExit("SHIPFINDER_KEY가 없습니다. .env를 확인하세요")

    client = ShipFinderClient()
    try:
        result = client.search(args.target) if args.search else client.position(args.target)
    except ShipFinderError as e:
        raise SystemExit(f"실패: {e.to_dict()}")

    print(result)
    if args.save:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUT_DIR / f"{'search' if args.search else 'position'}_{args.target}.json"
        payload = result.hits if args.search else result.raw
        path.write_text(json.dumps(payload, ensure_ascii=False, default=str, indent=1), encoding="utf-8")
        print(f"saved: {path}")


if __name__ == "__main__":
    main()
