"""경로와 소요시간. (SDD 5절 4단계, 6절 route_car·route_transit)

바깥 호출은 이 파일과 geo.py 에만 둔다 (BACKEND_GUIDE).

MCP 로 가는 길:
  SDD 1절은 이 파일이 MCP 클라이언트를 거치게 돼 있다. MCP 도구(route_car, route_transit)는 아직
  없어서 지금은 같은 API 를 직접 부른다. 부르는 자리는 _car 와 _transit 둘뿐이라, 도구가 생기면
  그 안만 MCP 호출로 바꾸면 된다. 키는 어느 쪽이든 서버 환경변수라 배포는 그대로다.

실패는 사람 단위로 삼킨다. 한 명 조회가 실패해도 나머지로 계산을 이어 간다 (SDD 5절 4단계 "실패 시").
"""
from __future__ import annotations

import asyncio
import hashlib
import os
from typing import Any

import httpx

from backend.app.domain import rules as domain_rules

KAKAO_CAR_URL = "https://apis-navi.kakaomobility.com/v1/directions"
TMAP_TRANSIT_URL = "https://apis.openapi.sk.com/transit/routes"
TIMEOUT_SEC = 12.0
# TMAP 대중교통은 초당 호출 제한이 있다. 연속으로 부르면 429 THROTTLED 가 온다 (SDD 6절).
# 한 줄로 세우는 것만으로는 부족해서, 429 면 잠깐 쉬었다 다시 부른다.
TRANSIT_GAP_SEC = 1.2
TRANSIT_RETRY_WAITS_SEC = (2, 4)
MAX_POLYLINE_POINTS = 300  # 화면에 그리기만 하면 되므로 점을 줄여 응답을 가볍게 한다

LngLat = tuple[float, float]


def _cache_key(plan: dict[str, Any]) -> str:
    """같은 구간·같은 이동수단이면 같은 키. 좌표는 소수점 5자리(약 1m)까지만 본다.

    좌표를 그대로 키에 쓰지 않고 해시로 만드는 이유: route_cache 는 평문 컬럼이라 출발지 좌표가
    그대로 남으면 안 된다 (테이블정의서 7절 "좌표는 해시나 암호화로만").
    """
    parts = [plan["transport"]]
    for point in (plan["origin"], plan["dest"], plan.get("waypoint")):
        parts.append(f"{point[0]:.5f},{point[1]:.5f}" if point else "-")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


async def _cached(plan: dict[str, Any]) -> dict[str, Any] | None:
    """캐시 적중이면 저장해 둔 결과. DB 가 없으면 그냥 None (캐시는 있으면 좋은 것이다)."""
    try:
        from backend.app.services import store

        hit = await store.cache_get(_cache_key(plan))
    except Exception:  # noqa: BLE001
        return None
    return hit["response"] if hit else None


async def _remember(plan: dict[str, Any], out: dict[str, Any]) -> None:
    """다음에 같은 구간을 물으면 API 를 부르지 않게 남겨 둔다."""
    try:
        from backend.app.services import store

        ttl = int(domain_rules.load_rule("transport")["route_cache_ttl_hours"])
        await store.cache_put(
            cache_key=_cache_key(plan),
            provider="kakao_car" if plan["transport"] == "car" else "tmap_transit",
            response=out,
            summary={"duration_sec": out["duration_sec"], "transfer_count": out.get("transfer_count")},
            ttl_hours=ttl,
        )
    except Exception:  # noqa: BLE001
        return


class RouteFailed(RuntimeError):
    """경로를 구하지 못했다. 그 사람만 빠지고 나머지는 계속 간다."""


def _thin(points: list[list[float]]) -> list[list[float]]:
    if len(points) <= MAX_POLYLINE_POINTS:
        return points
    step = len(points) / (MAX_POLYLINE_POINTS - 1)
    out = [points[int(i * step)] for i in range(MAX_POLYLINE_POINTS - 1)]
    out.append(points[-1])
    return out


async def _car(
    client: httpx.AsyncClient, origin: LngLat, dest: LngLat, waypoint: LngLat | None
) -> dict[str, Any]:
    """카카오모빌리티 길찾기. waypoint 는 픽업 지점 (transport.md pickup_counts_from_board)."""
    key = os.environ.get("KAKAO_REST_KEY")
    if not key:
        raise RouteFailed("KAKAO_REST_KEY 가 없습니다")
    params: dict[str, Any] = {
        "origin": f"{origin[0]},{origin[1]}",
        "destination": f"{dest[0]},{dest[1]}",
        "priority": "RECOMMEND",
    }
    if waypoint:
        params["waypoints"] = f"{waypoint[0]},{waypoint[1]}"
    res = await client.get(KAKAO_CAR_URL, params=params, headers={"Authorization": f"KakaoAK {key}"})
    res.raise_for_status()
    route = res.json()["routes"][0]
    if route.get("result_code") != 0:
        raise RouteFailed(f"경로 없음: {route.get('result_msg')}")

    points: list[list[float]] = []
    for section in route["sections"]:
        for road in section["roads"]:
            v = road["vertexes"]
            points.extend([round(v[i], 6), round(v[i + 1], 6)] for i in range(0, len(v), 2))
    return {
        "duration_sec": int(route["summary"]["duration"]),
        "polyline": _thin(points),
        "transfer_count": None,
    }


async def _transit(client: httpx.AsyncClient, origin: LngLat, dest: LngLat) -> dict[str, Any]:
    """TMAP 대중교통. 429 면 쉬었다 다시 부른다. 한 명이 통째로 빠지는 것보다 몇 초 느린 편이 낫다."""
    last: Exception | None = None
    for wait in (*TRANSIT_RETRY_WAITS_SEC, None):
        try:
            return await _transit_once(client, origin, dest)
        except RouteFailed as e:
            if "429" not in str(e) or wait is None:
                raise
            last = e
            await asyncio.sleep(wait)
    raise last if last else RouteFailed("대중교통 경로를 구하지 못했습니다")


async def _transit_once(client: httpx.AsyncClient, origin: LngLat, dest: LngLat) -> dict[str, Any]:
    """TMAP 대중교통 한 번 호출."""
    key = os.environ.get("TMAP_APP_KEY")
    if not key:
        raise RouteFailed("TMAP_APP_KEY 가 없습니다")
    res = await client.post(
        TMAP_TRANSIT_URL,
        json={
            "startX": str(origin[0]),
            "startY": str(origin[1]),
            "endX": str(dest[0]),
            "endY": str(dest[1]),
            "count": 1,
            "lang": 0,
            "format": "json",
        },
        headers={"appKey": key},
    )
    if res.status_code == 429:
        raise RouteFailed("TMAP 호출 한도(429)")
    res.raise_for_status()
    data = res.json()
    if "metaData" not in data:
        raise RouteFailed("대중교통 경로 없음")
    itinerary = data["metaData"]["plan"]["itineraries"][0]

    points: list[list[float]] = []
    # 구간(leg) 요약. 어느 호선·버스를 타는지 알아야 first_last_train 에 넘길 호선을 고를 수 있다 (09-18 결정).
    # TMAP 의 route 는 지하철이면 "수도권4호선", 버스면 "간선:401", 걷기면 None 으로 온다 (09-18 실측).
    legs: list[dict[str, Any]] = []
    for leg in itinerary["legs"]:
        legs.append(
            {
                "mode": leg["mode"],  # WALK / SUBWAY / BUS
                "route": leg.get("route"),
                "from": leg["start"]["name"],
                "to": leg["end"]["name"],
                "sec": int(leg["sectionTime"]),
            }
        )
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
        "duration_sec": int(itinerary["totalTime"]),
        "polyline": _thin(points),
        "transfer_count": itinerary.get("transferCount"),
        "legs": legs,
    }


async def route_one(
    client: httpx.AsyncClient,
    transport: str,
    origin: LngLat,
    dest: LngLat,
    waypoint: LngLat | None = None,
) -> dict[str, Any]:
    """한 사람의 한 후보까지 경로. 도보는 대중교통 API 로 대신한다(짧은 거리는 걷기 구간이 나온다)."""
    if transport == "car":
        return await _car(client, origin, dest, waypoint)
    return await _transit(client, origin, dest)


async def compute_all(plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """여러 사람 × 여러 후보를 한 번에. plans 항목은 아래를 담는다.

        {"key": 아무 표식, "transport": "car"|"transit"|"walk",
         "origin": (lng, lat), "dest": (lng, lat), "waypoint": (lng, lat) | None}

    돌려주는 항목에는 plan 의 key 와 duration_sec·polyline·transfer_count 가 들어간다.
    실패한 항목은 "error" 를 담아 돌려준다. 부르는 쪽이 그 사람만 빼면 된다.
    """
    async with httpx.AsyncClient(timeout=TIMEOUT_SEC) as client:

        async def run(plan: dict[str, Any]) -> dict[str, Any]:
            cached = await _cached(plan)
            if cached is not None:
                return {"key": plan["key"], **cached, "cached": True}
            try:
                out = await route_one(
                    client, plan["transport"], plan["origin"], plan["dest"], plan.get("waypoint")
                )
                await _remember(plan, out)
                return {"key": plan["key"], **out}
            except (RouteFailed, httpx.HTTPError, KeyError, IndexError, ValueError) as e:
                return {"key": plan["key"], "error": f"{type(e).__name__}: {e}"}

        # 대중교통은 초당 제한이 있어 한 줄로 세우고 사이를 띄운다. 자동차는 한꺼번에 부른다
        transit_plans = [p for p in plans if p["transport"] != "car"]
        car_plans = [p for p in plans if p["transport"] == "car"]

        results = list(await asyncio.gather(*(run(p) for p in car_plans)))
        for i, plan in enumerate(transit_plans):
            if i:
                await asyncio.sleep(TRANSIT_GAP_SEC)
            results.append(await run(plan))
        return results
