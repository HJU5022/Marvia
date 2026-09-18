"""MCP 도구: route_car — 자동차 경로·소요시간. (SDD 6절, MCP_GUIDE)

실제 카카오모빌리티(카카오내비) 호출은 backend/app/services/routes.py 의 _car 가 한다. 이 파일은 감싸기만.
인증은 developers.kakao.com 의 REST 키(KAKAO_REST_KEY) 그대로. 별도 키가 필요하다는 기록이 있었으나
같은 키로 200 확인 (09-18 실측).

SDD 6절과 다른 점 (문서 현행화 대기, 09-18 팀 결정 "문서는 참고만"):
  - departure_time(미래 운행) 을 받지 않는다. 형 함수가 현재 기준 길찾기만 부른다
  - distance_m·toll·fare_taxi 를 주지 않는다. 형 함수가 duration_sec·polyline 만 뽑는다
  - 좌표는 [lng, lat] 배열이 아니라 숫자로 받는다 (route_transit 과 같은 이유)

waypoint 는 픽업 지점이다. 차로 오는 사람이 다른 참석자를 태워 갈 때, 태우는 자리를 거쳐 가는 경로가 된다
(skills/converge/rules/transport.md pickup_counts_from_board).
"""
from __future__ import annotations

import httpx
from pydantic import BaseModel, Field

from backend.app.services.routes import TIMEOUT_SEC, _car
from mcp_server.server import mcp


class CarRoute(BaseModel):
    """출력 계약. routes._car 가 돌려주는 dict 와 같은 모양. route_transit 의 TransitRoute 와 필드가 같아
    파이프라인이 교통수단 구분 없이 다룬다."""

    duration_sec: int = Field(description="총 소요(초). departure_calc 의 duration_sec 에 그대로 넣는다")
    transfer_count: None = Field(default=None, description="자동차는 환승이 없어 항상 None")
    polyline: list[list[float]] = Field(description="경로선 [[lng, lat], ...]. 화면에 그리는 용도, 300점 이하로 줄여져 있다")


@mcp.tool()
async def route_car(
    origin_lng: float,
    origin_lat: float,
    dest_lng: float,
    dest_lat: float,
    waypoint_lng: float | None = None,
    waypoint_lat: float | None = None,
) -> CarRoute:
    """자동차로 출발지에서 집결 후보까지 소요시간을 구할 때 쓴다. 픽업 지점이 있으면 waypoint 로 준다.

    Args:
        origin_lng: 출발지 경도 (geocode 결과)
        origin_lat: 출발지 위도
        dest_lng: 집결 후보 경도 (search_places 결과)
        dest_lat: 집결 후보 위도
        waypoint_lng: 픽업 지점 경도. 둘 다 없으면 경유 없음
        waypoint_lat: 픽업 지점 위도

    Returns:
        duration_sec, transfer_count(항상 None), polyline. 경로가 없으면 에러
    """
    # 형 함수는 좌표를 (lng, lat) 한 묶음씩 받는다. 경유지는 둘 다 있을 때만 묶어 넘긴다 (geocode 의 bias 와 같은 방식).
    waypoint = (waypoint_lng, waypoint_lat) if waypoint_lng is not None and waypoint_lat is not None else None
    async with httpx.AsyncClient(timeout=TIMEOUT_SEC) as client:
        out = await _car(client, (origin_lng, origin_lat), (dest_lng, dest_lat), waypoint)
    return CarRoute(**out)
