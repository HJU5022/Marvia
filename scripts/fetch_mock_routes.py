"""프론트 mock 용 실제 경로를 한 번 받아 frontend/lib/mock-data.json 의 routes 에 저장한다.

손으로 돌리는 스크립트다. 서비스 코드는 이 파일을 쓰지 않는다.
  자동차: 카카오모빌리티 길찾기 (KAKAO_REST_KEY)
  대중교통: TMAP 대중교통 (TMAP_APP_KEY)
키는 루트 .env 에서 읽는다. 이미 받은 경로는 건너뛴다 (--force 로 다시 받기).

    python scripts/fetch_mock_routes.py [--force] [--only ship|si]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "frontend" / "lib" / "mock-data.json"
MAX_POINTS = 400
TMAP_GAP_SEC = 1.2  # TMAP 은 초당 호출 제한이 있어 429(THROTTLED)가 난다
RANKS = (1, 2)


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.split(" #")[0].strip().strip('"').strip("'")
    return env


def thin(points: list[list[float]]) -> list[list[float]]:
    if len(points) <= MAX_POINTS:
        return points
    step = len(points) / (MAX_POINTS - 1)
    out = [points[int(i * step)] for i in range(MAX_POINTS - 1)]
    out.append(points[-1])
    return out


def request_json(req: urllib.request.Request, retry_429: bool = True) -> dict:
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 429 and retry_429:
            time.sleep(3)
            return request_json(req, retry_429=False)
        body = e.read().decode("utf-8", "replace")[:200]
        raise RuntimeError(f"HTTP {e.code}: {body}") from e


def route_car(key: str, origin: list[float], dest: list[float], waypoint: list[float] | None) -> dict:
    params = {
        "origin": f"{origin[0]},{origin[1]}",
        "destination": f"{dest[0]},{dest[1]}",
        "priority": "RECOMMEND",
    }
    if waypoint:
        params["waypoints"] = f"{waypoint[0]},{waypoint[1]}"
    url = "https://apis-navi.kakaomobility.com/v1/directions?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"KakaoAK {key}"})
    route = request_json(req)["routes"][0]
    if route.get("result_code") != 0:
        raise RuntimeError(f"카카오 경로 없음: {route.get('result_msg')}")
    points: list[list[float]] = []
    for section in route["sections"]:
        for road in section["roads"]:
            v = road["vertexes"]
            points.extend([round(v[i], 6), round(v[i + 1], 6)] for i in range(0, len(v), 2))
    return {
        "polyline": thin(points),
        "raw_duration_min": round(route["summary"]["duration"] / 60),
        "transfer_count": None,
        "source": "kakao_mobility",
    }


def route_transit(key: str, origin: list[float], dest: list[float]) -> dict:
    body = json.dumps(
        {
            "startX": str(origin[0]),
            "startY": str(origin[1]),
            "endX": str(dest[0]),
            "endY": str(dest[1]),
            "count": 1,
            "lang": 0,
            "format": "json",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://apis.openapi.sk.com/transit/routes",
        data=body,
        headers={"appKey": key, "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    time.sleep(TMAP_GAP_SEC)
    data = request_json(req)
    if "metaData" not in data:
        raise RuntimeError(f"TMAP 경로 없음: {json.dumps(data, ensure_ascii=False)[:200]}")
    it = data["metaData"]["plan"]["itineraries"][0]
    points: list[list[float]] = []
    for leg in it["legs"]:
        shapes = []
        if leg.get("passShape"):
            shapes.append(leg["passShape"]["linestring"])
        for step in leg.get("steps", []):
            if step.get("linestring"):
                shapes.append(step["linestring"])
        for shape in shapes:
            for pair in shape.split():
                x, y = pair.split(",")
                points.append([round(float(x), 6), round(float(y), 6)])
    return {
        "polyline": thin(points),
        "raw_duration_min": round(it["totalTime"] / 60),
        "transfer_count": it.get("transferCount"),
        "source": "tmap_transit",
    }


def save(data: dict) -> None:
    """시나리오는 사람이 읽게 들여쓰고, 경로는 한 건을 한 줄로 쓴다."""
    head = json.dumps({k: v for k, v in data.items() if k != "routes"}, ensure_ascii=False, indent=2)
    for r in data.get("routes", {}).values():
        r["polyline"] = [[round(x, 6), round(y, 6)] for x, y in r["polyline"]]
    lines = [
        f"    {json.dumps(k, ensure_ascii=False)}:{json.dumps(v, ensure_ascii=False, separators=(',', ':'))}"
        for k, v in sorted(data.get("routes", {}).items())
    ]
    text = head.rstrip()[:-1].rstrip() + ',\n  "routes": {\n' + ",\n".join(lines) + "\n  }\n}\n"
    DATA.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--only", choices=["ship", "si"])
    args = parser.parse_args()

    env = load_env()
    kakao, tmap = env.get("KAKAO_REST_KEY"), env.get("TMAP_APP_KEY")
    data = json.loads(DATA.read_text(encoding="utf-8"))
    routes: dict = data.setdefault("routes", {})
    failed = 0

    for sid, sc in data["scenarios"].items():
        if args.only and sid != args.only:
            continue
        people = sc["people"]
        for rank in RANKS:
            cand = next(c for c in sc["candidates"] if c["rank"] == rank)
            dest = [cand["lng"], cand["lat"]]
            for p in people:
                key = f"{sid}:{p['name']}:{rank}"
                if key in routes and not args.force:
                    continue
                try:
                    if p["transport"] == "transit":
                        if not tmap:
                            raise RuntimeError("TMAP_APP_KEY 없음")
                        routes[key] = route_transit(tmap, [p["lng"], p["lat"]], dest)
                    else:
                        if not kakao:
                            raise RuntimeError("KAKAO_REST_KEY 없음")
                        if p.get("pickup"):
                            # 태워지는 사람은 탑승 이후 구간만 (transport.md pickup_counts_from_board)
                            origin, waypoint = [p["pickup_lng"], p["pickup_lat"]], None
                        else:
                            origin = [p["lng"], p["lat"]]
                            rider = next((q for q in people if q.get("pickup") == p["name"]), None)
                            waypoint = [rider["pickup_lng"], rider["pickup_lat"]] if rider else None
                        routes[key] = route_car(kakao, origin, dest, waypoint)
                    r = routes[key]
                    print(f"ok   {key}: {r['raw_duration_min']}분, 점 {len(r['polyline'])}개")
                except Exception as e:  # noqa: BLE001  한 건 실패해도 나머지는 받는다
                    failed += 1
                    print(f"fail {key}: {e}", file=sys.stderr)
                save(data)

    save(data)
    print(f"끝. 실패 {failed}건. 저장: {DATA.relative_to(ROOT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
