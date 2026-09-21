"""MCP 도구: geocode — 지명을 좌표로. (SDD 6절, MCP_GUIDE)

실제 카카오 로컬 호출은 backend/app/services/geo.py 의 geocode_one 이 한다. 이 파일은 그 함수를
MCP 도구로 감싸기만 한다 (MCP_GUIDE: "실제 API 호출 코드를 여기 다시 쓰지 않는다").

SDD 6절과 다른 점 (문서 현행화 대기, 09-18 팀 결정 "문서는 참고만"):
  - radius_m 을 받지 않는다. 형 함수가 반경 대신 "목적지 근처 우선"(bias)으로 동명 지명을 가른다
  - address·alternatives[] 를 주지 않는다. 형 함수가 핀 하나만 돌려준다
"""
from __future__ import annotations

import httpx
from pydantic import BaseModel, Field

from backend.app.services.geo import TIMEOUT_SEC, geocode_one
from mcp_server.server import mcp


class GeocodeResult(BaseModel):
    """출력 계약. 형 함수의 GeocodedPin 에서 화면용 kind 만 뺀 것.
    반환 타입을 모델로 두면 도구 목록에 출력 스키마가 실린다 (departure_calc 과 같은 이유)."""

    name: str = Field(description="검색한 지명")
    lng: float = Field(description="경도")
    lat: float = Field(description="위도")
    confidence: float = Field(description="확신도 0~1. 0.8 미만이면 사용자에게 핀 확인을 받는다 (SDD 5절 2단계)")


@mcp.tool()
async def geocode(
    query: str, bias_lng: float | None = None, bias_lat: float | None = None
) -> GeocodeResult:
    """지명 텍스트를 좌표로 바꿀 때 쓴다. 목적지를 먼저 찾고, 그 좌표를 bias 로 넘겨 나머지 지명을 찾는다.

    같은 이름이 여러 지역에 있을 때(마산역: 창원·고양) bias 가 없으면 카카오 순위 1등을 그대로 믿는다.
    목적지 좌표를 bias 로 주면 그 근처(약 60km) 것만 남기고 고른다 (geo._pick, SAME_REGION_DEG).

    Args:
        query: 지명. "마산역", "김해시청 앞"
        bias_lng: 목적지 경도. 둘 다 없으면 전국 검색
        bias_lat: 목적지 위도

    Returns:
        name, lng, lat, confidence. 못 찾으면 에러 (geo.GeocodeFailed 를 그대로 올린다)
    """
    # 형 함수는 bias 를 (lng, lat) 한 묶음으로 받는다. MCP 입력은 숫자 둘로 받는 게 모델이 채우기 쉽다.
    bias = (bias_lng, bias_lat) if bias_lng is not None and bias_lat is not None else None
    # geocode_one 은 인터넷을 타는 async 함수라 httpx 클라이언트를 열어 넘겨야 한다.
    # 여는 방식·타임아웃은 geo.geocode_all 과 같다.
    async with httpx.AsyncClient(timeout=TIMEOUT_SEC) as client:
        # kind 는 GeocodedPin 의 필수 항목(화면용 꼬리표)이라 채우기만 한다. 결과에는 싣지 않는다.
        pin = await geocode_one(client, query, kind="destination", bias=bias)
    return GeocodeResult(name=pin.name, lng=pin.lng, lat=pin.lat, confidence=pin.confidence)
