"""도구 get_port_schedule (작업 B6). 부산항 입항 일정과 접안 시설을 가져온다.

해수부 API 두 개를 합쳐서 돌려준다 (B5 MofClient).

- 관제정보: 이미 일어난 실적. 실제 입항 시각과 접안 시설
- 선박운항정보: 입출항 신고. 아직 안 들어온 배의 입항 예정

UNI-PASS에는 MMSI가 없고 ShipFinder에는 접안 시설이 없어서, 둘을 잇는 값은
호출부호(call_sign)와 선명이다.

조회 기간은 지난 며칠(실적)과 앞으로 며칠(예정)을 함께 본다. 화물 추적에서 궁금한 것은
"이미 들어왔는가"와 "언제 들어오는가" 둘 다이기 때문이다.

출력 계약은 mcp_server/schemas.py의 PortScheduleResult다 (C4, SDD 3.4).
"""
from datetime import date, datetime, timedelta, timezone
from typing import Annotated

from pydantic import Field

from backend.app.clients.mof import MofClient, MofError, SailingPlan, VesselCall
from mcp_server.schemas import ControlEvent, PortScheduleResult, ToolError

LOOKBACK_DAYS = 3  # 실적을 며칠 전까지 볼지
LOOKAHEAD_DAYS = 7  # 입항 예정을 며칠 뒤까지 볼지

make_client = MofClient  # 테스트가 fixture 클라이언트로 바꿔 끼우는 자리


def _by_name(records: list, ship_name: str | None) -> list:
    """선명으로 거른다. 호출부호로 조회했으면 보통 1건이라 그대로 지나간다."""
    if not ship_name:
        return records
    target = ship_name.replace(" ", "").upper()
    matched = [r for r in records if target in r.ship_name.replace(" ", "").upper()]
    return matched or records


def _pick(calls: list[VesselCall], ship_name: str | None) -> VesselCall | None:
    """실적 중 한 건. 같은 배가 여러 번 들어왔으면 가장 최근 입항."""
    calls = _by_name(calls, ship_name)
    if not calls:
        return None
    return max(calls, key=lambda c: c.actual_arrival or c.reported_arrival or datetime.min.replace(tzinfo=timezone.utc))


def _pick_plan(plans: list[SailingPlan], ship_name: str | None) -> SailingPlan | None:
    """예정 중 한 건. 가장 이른 입항 예정을 쓴다. 신고가 여러 번 바뀌어도 시각 기준으로 고른다."""
    plans = [p for p in _by_name(plans, ship_name) if p.planned_arrival]
    if not plans:
        return None
    return min(plans, key=lambda p: p.planned_arrival)


def get_port_schedule(
    call_sign: Annotated[str | None, Field(description="선박 호출부호. 이걸 알면 가장 정확하다")] = None,
    ship_name: Annotated[str | None, Field(description="선명. 호출부호를 모를 때 쓴다")] = None,
    lookback_days: Annotated[int, Field(description="실적을 며칠 전까지 볼지. 기본 3일", ge=1, le=30)] = LOOKBACK_DAYS,
    lookahead_days: Annotated[int, Field(description="입항 예정을 며칠 뒤까지 볼지. 기본 7일", ge=0, le=30)] = LOOKAHEAD_DAYS,
) -> dict:
    """해수부 기록에서 그 배의 부산항 입항 예정과 실제 입항, 접안 부두를 확인한다.

    call_sign이나 ship_name 중 하나는 반드시 준다.
    AIS 위치나 AIS ETA와 어긋날 때는 이 기록을 먼저 믿는다. 관제 실적이 가장 확실하고,
    그다음이 입출항 신고 기반의 입항 예정이다.
    돌려주는 값: planned_arrival(입항 예정), actual_arrival(실제 입항), facility(접안 시설),
    control_events(입항·접안·이안·출항), fetched_at.
    둘 다 비어 있으면 아직 신고도 입항도 없는 것이다.
    """
    if not call_sign and not ship_name:
        return {"error": ToolError(code="bad_input", message="call_sign이나 ship_name 중 하나는 필요하다", retryable=False).model_dump()}

    today = date.today()
    client = make_client()
    try:
        calls = client.control_records(today - timedelta(days=lookback_days), today, call_sign=call_sign)
        plans = (
            client.sailing_plans(today, today + timedelta(days=lookahead_days), call_sign=call_sign)
            if lookahead_days
            else []
        )
    except MofError as e:
        return {"error": ToolError(**e.to_dict()).model_dump()}

    fetched_at = datetime.now(timezone.utc)
    chosen = _pick(calls, ship_name)
    plan = _pick_plan(plans, ship_name)

    return PortScheduleResult(
        planned_arrival=plan.planned_arrival if plan else None,
        actual_arrival=chosen.actual_arrival if chosen else None,
        # 접안 시설은 실적이 있으면 실적 쪽을 쓴다. 예정은 바뀔 수 있다
        facility=(chosen.facility if chosen else None) or (plan.facility if plan else None),
        control_events=[ControlEvent(kind=e.kind, at=e.at, facility=e.facility) for e in (chosen.events if chosen else [])],
        fetched_at=fetched_at,
    ).model_dump(mode="json")
