"""MCP 도구: route_transit — 대중교통 경로·소요시간. (SDD 6절, MCP_GUIDE)

실제 TMAP 호출은 backend/app/services/routes.py 의 _transit 이 한다. 이 파일은 그 함수를 감싸기만 한다.
도보도 이 도구로 대신한다. 짧은 거리는 TMAP 응답에 걷기 구간이 나온다 (routes.route_one).

SDD 6절과 다른 점 (문서 현행화 대기, 09-18 팀 결정 "문서는 참고만"):
  - walk_m·fare 를 주지 않는다. legs 는 09-18 결정으로 형 함수에 추가함(호선 판단용)
  - origin·destination 을 [lng, lat] 배열이 아니라 숫자 넷으로 받는다. 모델이 채우기 쉽다 (geocode 의 bias 와 같은 이유)

TMAP 은 초당 호출 제한이 있어 연속으로 부르면 429 가 온다. 형 함수가 RouteFailed 로 바꿔 올리고,
이 도구는 그걸 그대로 흘린다 (SDK 가 에러 응답으로 만든다). 여러 사람을 한꺼번에 계산할 때는
이 도구가 아니라 routes.compute_all 을 쓴다 (대중교통을 한 줄로 세운다).
"""
from __future__ import annotations

import httpx
from pydantic import BaseModel, Field

from backend.app.services.routes import TIMEOUT_SEC, _transit
from mcp_server.server import mcp


class Leg(BaseModel):
    """구간 하나. 어느 호선·버스를 타는지 여기서 읽어 first_last_train 의 line 을 고른다 (09-18 결정)."""

    mode: str = Field(description="WALK / SUBWAY / BUS")
    route: str | None = Field(description='노선. 지하철 "수도권4호선", 버스 "간선:401", 걷기는 None')
    from_: str = Field(alias="from", description="구간 시작 정류장·역")
    to: str = Field(description="구간 끝 정류장·역")
    sec: int = Field(description="구간 소요(초)")

    model_config = {"populate_by_name": True}


class TransitRoute(BaseModel):
    """출력 계약. routes._transit 이 돌려주는 dict 와 같은 모양."""

    duration_sec: int = Field(description="총 소요(초). departure_calc 의 duration_sec 에 그대로 넣는다")
    transfer_count: int | None = Field(description="환승 횟수. TMAP 이 안 주면 None")
    polyline: list[list[float]] = Field(description="경로선 [[lng, lat], ...]. 화면에 그리는 용도, 300점 이하로 줄여져 있다")
    legs: list[Leg] = Field(description="구간 목록. 호선 판단은 이걸 보고 AI 가 한다. 호선을 못 고르면 목적지를 되묻는다")


@mcp.tool()
async def route_transit(
    origin_lng: float, origin_lat: float, dest_lng: float, dest_lat: float
) -> TransitRoute:
    """대중교통(또는 도보)으로 출발지에서 집결 후보까지 소요시간을 구할 때 쓴다. 참석자 한 명, 후보 한 곳씩 부른다.

    Args:
        origin_lng: 출발지 경도 (geocode 결과)
        origin_lat: 출발지 위도
        dest_lng: 집결 후보 경도 (search_places 결과)
        dest_lat: 집결 후보 위도

    Returns:
        duration_sec, transfer_count, polyline. 경로가 없거나 TMAP 한도(429)면 에러
    """
    # 형 함수는 좌표를 (lng, lat) 한 묶음씩 받는다. 타임아웃은 routes.py 의 값(12초)을 그대로 쓴다.
    async with httpx.AsyncClient(timeout=TIMEOUT_SEC) as client:
        out = await _transit(client, (origin_lng, origin_lat), (dest_lng, dest_lat))
    return TransitRoute(**out)
