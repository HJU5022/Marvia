"""도구 get_live_position (작업 B4). MMSI로 선박의 실시간 위치를 가져온다.

ShipFinder VesselPositionSingle을 그대로 옮긴다. 값은 원본이고, freshness 판정은 하지 않는다.
last_time(선박이 보고한 시각)과 fetched_at(우리가 조회한 시각)을 같이 돌려주면
services/signals.py가 position_stale을 계산한다 (C-4 경계, 작업 리스트 "경계 정리").

출력 계약은 mcp_server/schemas.py의 LivePositionResult, 실패는 ToolError다 (C4, SDD 3.4).
"""
from datetime import datetime, timezone

from backend.app.clients.shipfinder import ShipFinderClient, ShipFinderError
from mcp_server.schemas import LivePositionResult, ToolError

# 클라이언트를 만드는 자리. 테스트가 fixture 클라이언트로 바꿔 끼운다.
# FastMCP는 밑줄로 시작하는 인자를 막기 때문에 인자 대신 모듈 변수로 둔다.
make_client = ShipFinderClient


def get_live_position(mmsi: int) -> dict:
    """MMSI를 아는 선박의 지금 위치·속도·목적지·AIS ETA를 확인할 때 쓴다.

    선박이 마지막으로 보고한 시각(last_time)을 함께 돌려주므로, 값이 오래됐는지는
    받는 쪽이 판단한다.

    Args:
        mmsi: 9자리 해상이동업무식별번호. 선명만 아는 경우 get_vessel_candidates로 먼저 찾는다
    """
    try:
        pos = make_client().position(mmsi)
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
    ).model_dump(mode="json")
