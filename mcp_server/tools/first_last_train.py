"""MCP 도구: first_last_train — 역의 첫차·막차. (SDD 6절, MCP_GUIDE)

실제 서울 열린데이터광장 호출은 backend/app/services/transit_schedule.py 의 first_last_seoul 이 한다.
이 파일은 그 함수를 감싸기만 한다. 형 함수가 없어서 주방(services/)까지 새로 만든 첫 도구다 (09-21).

호선은 필수 입력이다 (09-18 결정):
  서울역은 1·4·경의선이 지나서 이름만으로는 답이 안 나온다. 어느 호선인지는 목적지를 보고 AI 가
  route_transit 의 legs(예: "수도권4호선")에서 읽어 넣는다. 호선을 못 고르면 도구를 부르지 말고
  목적지를 되묻는다 (SDD 5절 재질문). 선택 입력으로 두고 첫 호선을 주면 틀린 답이 조용히 나간다.

SDD 6절과 다른 점 (문서 현행화 대기):
  - city 는 지금 "seoul" 만. 부산은 공공데이터포털 활용신청 승인 뒤
  - 출력에 first_to·last_to(행선지) 추가. 막차가 종점까지 안 가는 경우가 있어 현장 판단에 필요
"""
from __future__ import annotations

from typing import Literal

import httpx
from pydantic import BaseModel, Field

from backend.app.services.transit_schedule import TIMEOUT_SEC, first_last_seoul
from mcp_server.server import mcp


class FirstLastResult(BaseModel):
    """출력 계약. transit_schedule.first_last_seoul 이 돌려주는 dict 와 같은 모양."""

    first: str = Field(description='첫차 "HH:MM"')
    last: str = Field(description='막차 "HH:MM". 자정 넘으면 24:48 처럼 24시 이후로 이어 센다')
    line: str = Field(description='호선 "1"~"9"')
    first_to: str = Field(description="첫차 행선지 역")
    last_to: str = Field(description="막차 행선지 역. 종점까지 안 가면 여기서 갈아타거나 다른 수단")


@mcp.tool()
async def first_last_train(
    station_name: str,
    line: str,
    direction: Literal["up", "down"],
    weekday: Literal["weekday", "sat", "holiday"] = "weekday",
    city: Literal["seoul"] = "seoul",
) -> FirstLastResult:
    """지하철역의 첫차·막차 시각을 확인할 때 쓴다. 야간 배포·이른 집결에서 대중교통이 되는지 판단하는 재료.

    호선을 모르면 부르지 말고 목적지를 되묻는다. 호선은 route_transit 결과의 legs 에서 읽는다.

    Args:
        station_name: 역 이름. "서울역", "사당"
        line: 호선 "1"~"9". route_transit legs 의 "수도권4호선" 이면 "4"
        direction: "up" 상행 / "down" 하행. 목적지 방향
        weekday: "weekday" 평일 / "sat" 토요일 / "holiday" 휴일. 약속 날짜로 정한다
        city: 지금은 "seoul" 만

    Returns:
        first, last "HH:MM", line, first_to·last_to(행선지). 역이 없거나 시각표가 없으면 에러
    """
    async with httpx.AsyncClient(timeout=TIMEOUT_SEC) as client:
        out = await first_last_seoul(client, station_name, line, weekday, direction)
    return FirstLastResult(**out)
