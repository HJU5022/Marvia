"""MCP 도구: departure_calc — 출발 시각 역산. (SDD 6절)

7개 도구 중 유일하게 외부 API가 없다. 계산은 backend/app/domain/rules.py 의 calc_departure 가 하고,
이 파일은 그 함수를 MCP 도구로 감싸기만 한다 (MCP_GUIDE: "실제 코드는 여기 다시 쓰지 않는다").

description(docstring 첫 문장)은 모델이 도구를 고를 때 읽는 유일한 단서다. "언제 쓰는 도구인지"가
한 문장에 드러나야 한다 (SDD 6절, MCP_GUIDE).
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from backend.app.domain.rules import calc_departure
from mcp_server.server import mcp


class DepartureResult(BaseModel):
    """출력 계약. 반환 타입을 모델로 두면 SDK가 도구 목록에 출력 스키마를 싣고, 결과를 structured_content로도 준다.
    dict로만 두면 텍스트로만 온다 (09-18 실측)."""

    depart_at: str = Field(description='출발 시각 "HH:MM"')
    arrive_by_adjusted: str = Field(description='절차 시작점(위병소·로비)에 도착해야 하는 시각 "HH:MM"')
    day_offset: int = Field(description="출발이 도착 기한의 전날이면 -1, 같은 날이면 0")


@mcp.tool()
def departure_calc(
    arrive_by: str, duration_sec: int, buffer_min: int, access_lead_min: int
) -> DepartureResult:
    """도착 기한·이동 소요·여유·출입 절차 소요로 출발 시각을 역산할 때 쓴다. 경로 조회 뒤 마지막 단계.

    Args:
        arrive_by: 약속 시각 "HH:MM". 점검 시작·배포 시작 시각
        duration_sec: 이동 소요(초). route_car / route_transit 이 준 값
        buffer_min: 여유(분). 규칙 transport.md 의 buffer_client_min / buffer_deploy_min
        access_lead_min: 출입·인솔 절차 소요(분). 규칙 access.md 의 gate_lead_min / lobby_lead_min. 절차 없으면 0

    Returns:
        depart_at "HH:MM", arrive_by_adjusted "HH:MM"(절차 시작점 도착 기한), day_offset(전날이면 -1)
    """
    return DepartureResult(**calc_departure(arrive_by, duration_sec, buffer_min, access_lead_min))
