"""도구 get_port_schedule (작업 B6). 부산항 입항 일정과 접안 시설을 가져온다.

해수부 API 두 개(B5 MofClient)를 부른다. UNI-PASS에는 MMSI가 없고 ShipFinder에는 접안 시설이 없어서,
둘을 잇는 값은 호출부호(call_sign)와 선명이다.

- actual_arrival·facility·control_events: 관제정보(실적). 지난 며칠과 오늘까지 본다
- planned_arrival: 선박운항정보(입항 신고). 앞으로 며칠까지 본다. 신고 단계가 최초·변경인
  값만 쓴다. 최종 신고는 실제 입항 시각이라 예정이 아니다 (mof.py 선박운항정보 절, 2026-09-23 실측)
- 선박운항정보는 호출부호로만 조회한다. 선명은 해수부가 한글로 적어서 영문 선명으로는 못 찾는다

출력 계약은 mcp_server/schemas.py의 PortScheduleResult다 (C4, SDD 3.4).
"""
from datetime import date, datetime, timedelta, timezone
from typing import Annotated

from pydantic import Field

from backend.app.clients.mof import MofClient, MofError, VesselCall
from mcp_server.schemas import ControlEvent, PortScheduleResult, ToolError

LOOKBACK_DAYS = 3  # 조회 시작일을 오늘에서 며칠 전으로 잡을지
LOOKAHEAD_DAYS = 7  # 입항 예정을 오늘부터 며칠 뒤까지 볼지. 해수부 신고가 1주 앞까지 나온다 (09-24~30 조회 264척, 2026-09-23 실측)

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


def _planned_arrival(client: MofClient, call_sign: str | None, today: date, lookback_days: int) -> datetime | None:
    """입항 예정 시각. 호출부호가 있을 때만 선박운항정보를 부른다.

    예정은 보조 근거라서 이 조회가 실패해도 도구 전체를 실패로 만들지 않는다.
    실적(관제정보)은 따로 돌려주고 planned_arrival만 비운다.
    """
    if not call_sign:
        return None
    try:
        reports = client.arrival_reports(today - timedelta(days=lookback_days), today + timedelta(days=LOOKAHEAD_DAYS), call_sign=call_sign)
    except MofError:
        return None
    planned = [r.planned_arrival for r in reports if r.planned_arrival]
    # 같은 배가 기간 안에 여러 번 신고했으면 가장 늦은(다가오는) 입항을 쓴다
    return max(planned) if planned else None


def get_port_schedule(
    call_sign: Annotated[str | None, Field(description="선박 호출부호. 이걸 알면 가장 정확하다")] = None,
    ship_name: Annotated[str | None, Field(description="선명. 호출부호를 모를 때 쓴다")] = None,
    lookback_days: Annotated[int, Field(description="오늘부터 며칠 전까지 볼지. 기본 3일", ge=1, le=30)] = LOOKBACK_DAYS,
) -> dict:
    """해수부 기록에서 그 배의 부산항 입항 예정과 실제 입항, 접안 부두를 확인한다.

    call_sign이나 ship_name 중 하나는 반드시 준다. 입항 예정은 call_sign이 있어야 나온다.
    AIS 위치나 AIS ETA와 어긋날 때는 이 기록을 먼저 믿는다. 관제 실적이 가장 확실한 근거다.
    돌려주는 값: planned_arrival(입항 신고의 예정 시각), actual_arrival(실제 입항), facility(접안 시설),
    control_events(입항·접안·이안·출항), fetched_at. 실제 입항 기록이 없으면 아직 안 들어온 것일 수 있다.
    """
    if not call_sign and not ship_name:
        return {"error": ToolError(code="bad_input", message="call_sign이나 ship_name 중 하나는 필요하다", retryable=False).model_dump()}

    today = date.today()
    client = make_client()
    try:
        calls = client.control_records(today - timedelta(days=lookback_days), today, call_sign=call_sign)
    except MofError as e:
        return {"error": ToolError(**e.to_dict()).model_dump()}

    planned = _planned_arrival(client, call_sign, today, lookback_days)
    fetched_at = datetime.now(timezone.utc)
    chosen = _pick(calls, ship_name)
    if chosen is None:
        # 실적이 없는 것은 실패가 아니다. 아직 안 들어왔다는 뜻일 수 있다. 예정은 있으면 준다
        return PortScheduleResult(planned_arrival=planned, actual_arrival=None, fetched_at=fetched_at).model_dump(mode="json")

    return PortScheduleResult(
        planned_arrival=planned,
        actual_arrival=chosen.actual_arrival,
        facility=chosen.facility,
        control_events=[ControlEvent(kind=e.kind, at=e.at, facility=e.facility) for e in chosen.events],
        fetched_at=fetched_at,
    ).model_dump(mode="json")
