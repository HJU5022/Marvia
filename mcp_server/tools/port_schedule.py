"""도구 get_port_schedule (작업 B6). 부산항 입항 일정과 접안 시설을 가져온다.

해수부 관제정보(B5 MofClient)를 부른다. UNI-PASS에는 MMSI가 없고 ShipFinder에는 접안 시설이 없어서,
둘을 잇는 값은 호출부호(call_sign)와 선명이다.

주의: 관제정보는 이미 일어난 실적이다. planned_arrival(입항 예정)은 이 API에서 나오지 않아
지금은 항상 None이다. 선박운항정보 활용신청이 끝나면 그 값을 채운다.

조회 기간은 오늘 기준 앞뒤로 잡는다. 화물 추적에서 궁금한 것은 "이미 들어왔는가"라서
지난 며칠과 오늘까지만 보면 된다.

출력 계약은 mcp_server/schemas.py의 PortScheduleResult다 (C4, SDD 3.4).
"""
from datetime import date, datetime, timedelta, timezone

from backend.app.clients.mof import MofClient, MofError, VesselCall
from mcp_server.schemas import ControlEvent, PortScheduleResult, ToolError

LOOKBACK_DAYS = 3  # 조회 시작일을 오늘에서 며칠 전으로 잡을지

make_client = MofClient  # 테스트가 fixture 클라이언트로 바꿔 끼우는 자리


def _pick(calls: list[VesselCall], ship_name: str | None) -> VesselCall | None:
    """선명으로 한 척을 고른다. 호출부호로 조회했으면 보통 1건이다."""
    if not calls:
        return None
    if ship_name:
        target = ship_name.replace(" ", "").upper()
        matched = [c for c in calls if target in c.ship_name.replace(" ", "").upper()]
        if matched:
            calls = matched
    # 같은 배가 여러 번 들어왔으면 가장 최근 입항을 쓴다
    return max(calls, key=lambda c: c.actual_arrival or c.reported_arrival or datetime.min.replace(tzinfo=timezone.utc))


def get_port_schedule(call_sign: str | None = None, ship_name: str | None = None, lookback_days: int = LOOKBACK_DAYS) -> dict:
    """부산항에 그 배가 들어왔는지, 어느 부두에 붙었는지 확인할 때 쓴다.

    호출부호를 알면 그것으로 조회하는 편이 정확하다. 선명만 알면 최근 기간 전체를 받아 이름으로 고른다.
    AIS 위치와 어긋날 때 어느 쪽을 믿을지 가르는 근거가 된다.

    Args:
        call_sign: 선박 호출부호. UNI-PASS나 관제정보에서 얻는다
        ship_name: 선명. 호출부호를 모를 때 쓴다
        lookback_days: 오늘부터 며칠 전까지 볼지. 기본 3일
    """
    if not call_sign and not ship_name:
        return {"error": ToolError(code="bad_input", message="call_sign이나 ship_name 중 하나는 필요하다", retryable=False).model_dump()}

    today = date.today()
    try:
        calls = make_client().control_records(today - timedelta(days=lookback_days), today, call_sign=call_sign)
    except MofError as e:
        return {"error": ToolError(**e.to_dict()).model_dump()}

    fetched_at = datetime.now(timezone.utc)
    chosen = _pick(calls, ship_name)
    if chosen is None:
        # 기록이 없는 것은 실패가 아니다. 아직 안 들어왔다는 뜻일 수 있다
        return PortScheduleResult(planned_arrival=None, actual_arrival=None, fetched_at=fetched_at).model_dump(mode="json")

    return PortScheduleResult(
        planned_arrival=None,  # 관제정보는 실적만 준다. 선박운항정보 연동 후 채운다
        actual_arrival=chosen.actual_arrival,
        facility=chosen.facility,
        control_events=[ControlEvent(kind=e.kind, at=e.at, facility=e.facility) for e in chosen.events],
        fetched_at=fetched_at,
    ).model_dump(mode="json")
