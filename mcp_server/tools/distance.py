"""도구 estimate_distance (작업 B7). 부산항까지 남은 해상 거리.

searoute 해상 항로망으로 계산한다. 키 불필요, 외부 호출 없음.
기준점은 rules.md busan_ref가 원본이다 (C6, SDD 3.6).
python:3.12-slim(linux/amd64) 컨테이너에서 빌드 도구 없이 설치되는 것을 확인했다 (2026-09-23).

searoute 항로망은 노드가 성겨서 부산 기준점에 가장 가까운 노드가 약 9.6해리 앞바다에 있다.
그래서 (1) 그 노드보다 안쪽 배는 기준점까지 대권거리, (2) 바깥 배는 배에서 노드까지 항로 + 노드에서 기준점까지
대권거리로 계산한다. append_orig_dest로 양 끝 구간을 붙이면 항만 근처 배가 19.8해리처럼 부풀려진다.

MCP 등록: 이 함수는 mcp_server/server.py create_mcp()가 도구로 등록한다 (데코레이터 없음).
"""
import math
from datetime import datetime, timezone
from functools import cache
from typing import Annotated

import searoute
from pydantic import Field

from backend.app.services.judge.rules import rule
from mcp_server.schemas import DistanceResult, ToolError

_EARTH_RADIUS_NM = 3440.065


def _busan_ref() -> tuple[float, float]:
    """부산 기준점 (lat, lng). 값은 rules.md busan_ref가 원본이다 (C6)."""
    ref = rule("busan_ref")
    return (ref["lat"], ref["lng"])


def _great_circle_nm(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * _EARTH_RADIUS_NM * math.asin(math.sqrt(h))


@cache
def _busan_node() -> tuple[float, float]:
    """항로망에서 부산 기준점이 붙는 노드 (lat, lng). searoute 1.6.0 기준 35.0N 129.2E."""
    ref_lat, ref_lng = _busan_ref()
    lng, lat = searoute.searoute([ref_lng, ref_lat], [ref_lng, ref_lat])["geometry"]["coordinates"][0]
    return (lat, lng)


def estimate_distance(
    lat: Annotated[float, Field(description="선박 위도. WGS84, -90~90. 예: 34.5", ge=-90, le=90)],
    lng: Annotated[float, Field(description="선박 경도. WGS84, -180~180. 예: 128.8", ge=-180, le=180)],
    sog: Annotated[float | None, Field(description="선박 대지속력(노트). 예: 12. 주면 그 속력으로 걸리는 시간도 함께 계산한다")] = None,
) -> dict:
    """배의 좌표에서 부산항까지 바닷길로 얼마나 남았는지 알고 싶을 때 쓴다.

    get_live_position으로 받은 lat·lng·sog를 그대로 넣는다. searoute 해상 항로망으로 계산하며 외부 호출과 키가 없다.
    돌려주는 값: distance_nm(해리), calc_hours_at_sog(속력을 준 경우), source, fetched_at.
    근사값이다. 항로망이 성겨서 30~60해리 구간은 실제보다 크게 나온다.
    calc_hours_at_sog는 지금 속력이 끝까지 간다고 친 계산일 뿐 도착 예정 시각이 아니다.
    """
    fetched_at = datetime.now(timezone.utc)
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return {"error": ToolError(code="bad_input", message=f"좌표 범위 밖: {lat}, {lng}", retryable=False).model_dump()}

    try:
        ref = _busan_ref()
        node = _busan_node()
        last_leg = _great_circle_nm(node, ref)
        direct = _great_circle_nm((lat, lng), ref)
        if direct <= last_leg:
            distance = direct  # 노드 안쪽. 항만 접근 구간이라 직선으로 본다
        else:
            # searoute 좌표 순서는 [경도, 위도]
            route = searoute.searoute([lng, lat], [node[1], node[0]], units="naut", append_orig_dest=True)
            distance = float(route["properties"]["length"]) + last_leg
    except Exception as e:  # searoute는 좌표·항로망 문제를 다양한 예외로 던진다
        return {"error": ToolError(code="route_failed", message=f"{type(e).__name__}: {e}", retryable=False).model_dump()}

    distance_nm = round(distance, 1)
    return DistanceResult(
        distance_nm=distance_nm,
        calc_hours_at_sog=round(distance_nm / sog, 1) if sog and sog > 0 else None,
        fetched_at=fetched_at,
    ).model_dump(mode="json")


ROUTE_MAX_POINTS = 150  # 화면에 그릴 경로 점 상한. searoute 경로는 수백 점이라 균등하게 솎는다


def route_points(lat: float, lng: float) -> list[list[float]]:
    """배 위치에서 부산 기준점까지 남은 예상 바닷길을 [위도, 경도] 점 목록으로 돌려준다 (선박 자세히 보기 지도).

    estimate_distance와 같은 계산(searoute 항로망 + 마지막 노드에서 기준점까지 직선)이라 거리와 선이 맞는다.
    MCP 도구가 아니다. 도구 응답 모양(DistanceResult)을 바꾸지 않으려고 따로 둔다. 실제 항적이 아니라 예상 경로다.
    계산에 실패하면 빈 목록 (지도는 선 없이 그린다).
    """
    try:
        ref = _busan_ref()
        node = _busan_node()
        if _great_circle_nm((lat, lng), ref) <= _great_circle_nm(node, ref):
            return [[lat, lng], [ref[0], ref[1]]]
        coords = searoute.searoute([lng, lat], [node[1], node[0]], units="naut", append_orig_dest=True)["geometry"]["coordinates"]
    except Exception:
        return []
    points = [[c[1], c[0]] for c in coords] + [[ref[0], ref[1]]]
    if len(points) > ROUTE_MAX_POINTS:
        step = len(points) / ROUTE_MAX_POINTS
        points = [points[int(i * step)] for i in range(ROUTE_MAX_POINTS - 1)] + [points[-1]]
    return points
