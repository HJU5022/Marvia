"""도구 get_live_position (작업 B4). MMSI로 선박의 실시간 위치를 가져온다.

ShipFinder VesselPositionSingle을 그대로 옮긴다. 값은 원본이고, freshness 판정은 하지 않는다.
last_time(선박이 보고한 시각)과 fetched_at(우리가 조회한 시각)을 같이 돌려주면
services/judge/signals.py가 position_stale을 계산한다 (C-4 경계, 작업 리스트 "경계 정리").

출력 계약은 mcp_server/schemas.py의 LivePositionResult, 실패는 ToolError다 (C4, SDD 3.4).

MCP 등록: 이 함수는 mcp_server/server.py create_mcp()가 도구로 등록한다 (데코레이터 없음).
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
    mmsi: Annotated[int, Field(description="9자리 해상이동업무식별번호. 예: 440999001. 선명만 알면 get_vessel_candidates로 먼저 찾는다")],
) -> dict:
    """MMSI를 알고 그 배가 어디서 어떤 속력으로 어디로 가는지 볼 때 쓴다.

    ShipFinder의 최신 AIS 보고를 원본 그대로 돌려준다. 선명만 알면 get_vessel_candidates로 MMSI부터 찾는다.
    돌려주는 값: mmsi, lat, lng, sog, cog, navistat, dest, destcode, ais_eta, last_time, source, fetched_at, cached_at.
    last_time은 선박이 보고한 시각이고 fetched_at은 조회한 시각이다. 이 도구는 위치가 오래됐는지 판정하지 않는다.
    두 시각이 벌어진 만큼 그 좌표는 과거의 위치다.
    cached_at이 있으면 호출 한도에 걸려 그 시각에 담아둔 값을 돌려준 것이다.
    error.code가 quota_exhausted면 오늘 ShipFinder 호출 한도를 다 쓴 것이다. 오늘은 다시 불러도 같다.
    """
    # 클라이언트 만들기(키 없음 = bad_key)와 응답 변환(좌표 없음, 계약 검사 실패)까지 try 안에 둔다.
    # 전에는 make_client()와 LivePositionResult가 try 밖이라 예외가 도구 밖으로 새어, 계약(C4, SDD 3.4)의
    # {error: {code, message, retryable}} 대신 MCP 오류 문장이 나갔다. ShipFinder가 준 코드(bad_key 등)는 그대로 둔다
    try:
        client = make_client()
        pos = client.position(mmsi)
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
            # 빈도 초과·한도 소진·시간 초과로 캐시 값을 받았으면 언제 담긴 값인지 알린다
            cached_at=client.last_cached_at,
        ).model_dump(mode="json")
    except ShipFinderError as e:
        return {"error": ToolError(**e.to_dict()).model_dump()}
    except Exception as e:  # 응답 모양이 계약과 다름(ValidationError 등). 같은 응답이면 다시 불러도 같다
        return {"error": ToolError(code="bad_response", message=type(e).__name__, retryable=False).model_dump()}
