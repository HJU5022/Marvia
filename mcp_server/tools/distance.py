"""도구 estimate_distance (작업 B7). 부산항까지 남은 해상 거리.

searoute 해상 항로망으로 계산합니다. 키 불필요, 외부 호출 없음.
기준점은 rules.md busan_ref가 원본이다 (C6, SDD 3.6).

searoute 항로망은 노드가 성겨서 부산 기준점에 가장 가까운 노드가 약 9.6해리 앞바다에 있다.
그래서 (1) 그 노드보다 안쪽 배는 기준점까지 대권거리, (2) 바깥 배는 배에서 노드까지 항로 + 노드에서 기준점까지
대권거리로 계산한다. append_orig_dest로 양 끝 구간을 붙이면 항만 근처 배가 19.8해리처럼 부풀려진다.
"""
import math
from datetime import datetime, timezone
from functools import cache

import searoute

from mcp_server.rules import rule

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


def estimate_distance(lat: float, lng: float, sog: float | None = None) -> dict:
    """선박 좌표에서 부산항까지 남은 해상 거리(해리)를 계산할 때 쓴다.

    Args:
        lat: 선박 위도 (WGS84, -90~90)
        lng: 선박 경도 (WGS84, -180~180)
        sog: 선박 대지속력(노트). 주면 그 속력으로 걸리는 시간(calc_hours_at_sog)도 계산한다
    """
    fetched_at = datetime.now(timezone.utc).isoformat()
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return {"error": {"code": "bad_input", "message": f"좌표 범위 밖: {lat}, {lng}", "retryable": False}}

    try:
        ref = _busan_ref()
        node = _busan_node()
        last_leg = _great_circle_nm(node, ref)
        direct = _great_circle_nm((lat, lng), ref)
        if direct <= last_leg:
            distance, method = direct, "great_circle"
        else:
            # searoute 좌표 순서는 [경도, 위도]
            route = searoute.searoute([lng, lat], [node[1], node[0]], units="naut", append_orig_dest=True)
            distance, method = float(route["properties"]["length"]) + last_leg, "searoute"
    except Exception as e:  # searoute는 좌표·항로망 문제를 다양한 예외로 던진다
        return {"error": {"code": "route_failed", "message": f"{type(e).__name__}: {e}", "retryable": False}}

    distance_nm = round(distance, 1)
    return {
        "distance_nm": distance_nm,
        "calc_hours_at_sog": round(distance_nm / sog, 1) if sog and sog > 0 else None,
        "method": method,
        "busan_ref": {"lat": ref[0], "lng": ref[1]},
        "source": "searoute",
        "fetched_at": fetched_at,
    }
