"""도구 get_live_position (작업 B4). MMSI로 선박의 실시간 위치를 가져온다.

ShipFinder VesselPositionSingle을 그대로 옮긴다. 값은 원본이고, freshness 판정은 하지 않는다.
last_time(선박이 보고한 시각)과 fetched_at(우리가 조회한 시각)을 같이 돌려주면
services/signals.py가 position_stale을 계산한다 (C-4 경계, 작업 리스트 "경계 정리").

출력 계약은 mcp_server/schemas.py의 LivePositionResult, 실패는 ToolError다 (C4, SDD 3.4).
"""
from datetime import datetime, timezone
from typing import Annotated

from pydantic import Field

from backend.app.clients.shipfinder import ShipFinderClient, ShipFinderError
from mcp_server.schemas import LivePositionResult, ToolError

# 클라이언트를 만드는 자리. 테스트가 fixture 클라이언트로 바꿔 끼운다.
# FastMCP는 밑줄로 시작하는 인자를 막기 때문에 인자 대신 모듈 변수로 둔다.
make_client = ShipFinderClient


def get_live_position(
    mmsi: Annotated[int, Field(description="9자리 해상이동업무식별번호. 선명만 알면 get_vessel_candidates로 먼저 찾는다")],
) -> dict:
    """MMSI로 그 배의 최신 AIS 위치·속도·침로·목적지·AIS ETA를 가져온다.

    선명만 아는 상태에서는 쓸 수 없다. get_vessel_candidates로 MMSI를 먼저 확정한다.
    돌려주는 값: lat, lng, sog, cog, navistat, dest, destcode, ais_eta, last_time, fetched_at.
    last_time은 선박이 보고한 시각이고 fetched_at은 조회한 시각이다. 둘이 많이 벌어지면
    위치가 오래된 것이므로 현재 위치라고 말하지 않는다.
    cached_at이 있으면 호출 한도에 걸려 그 시각에 담아둔 값을 돌려준 것이다.
    """
    client = make_client()
    try:
        pos = client.position(mmsi)
    except ShipFinderError as e:
        return {"error": ToolError(**e.to_dict()).model_dump()}

    return LivePositionResult(
        mmsi=pos.mmsi,
        lat=pos.lat,
        lng=pos.lng,
        sog=pos.sog,
        cog=pos.cog,
        navistat=pos.navistat,
        dest=pos.dest,
        destcode=pos.destcode,
        ais_eta=pos.ais_eta,
        last_time=pos.last_time,
        fetched_at=pos.fetched_at or datetime.now(timezone.utc),
        # 빈도 초과로 캐시 값을 받았으면 언제 담긴 값인지 알린다
        cached_at=client.last_cached_at,
    ).model_dump(mode="json")
