"""MCP 도구: search_places — 좌표 둘레에서 집결 후보(위병소·정문·역)를 찾는다. (SDD 6절, MCP_GUIDE)

실제 카카오 로컬 호출은 backend/app/services/geo.py 의 _nearby 가 하고, 결과 정리는 _as_candidate 가 한다.
이 파일은 kind 를 검색어로 바꿔 그 둘을 부르기만 한다. 대응은 geo.build_candidates 와 같다
(GATE_QUERIES, STATION_SUFFIX).

SDD 6절과 다른 점 (문서 현행화 대기, 09-18 팀 결정 "문서는 참고만"):
  - radius_m 을 받지 않는다. 형 함수가 3km → 8km 로 고정해 넓혀 본다 (CANDIDATE_RADIUS_M)
  - kind 는 gate·landmark 만. lobby 는 형 코드가 검색하지 않고 목적지 자체를 쓰며, cafe 는 형 코드에 없다
"""
from __future__ import annotations

from typing import Literal

import httpx
from pydantic import BaseModel, Field

from backend.app.services.geo import GATE_QUERIES, STATION_SUFFIX, TIMEOUT_SEC, _as_candidate, _nearby
from mcp_server.server import mcp

# kind → 카카오에 넣을 검색어. 형이 build_candidates 에서 쓰는 값 그대로다.
KIND_QUERIES: dict[str, list[str]] = {
    "gate": [q for q, _ in GATE_QUERIES],  # ["위병소", "정문"]
    "landmark": [STATION_SUFFIX],  # ["역"]
}


class Place(BaseModel):
    """후보 한 곳. geo._as_candidate 가 만드는 dict 와 같은 모양 (SDD 4절 Candidate 의 부분집합)."""

    name: str = Field(description="장소 이름")
    kind: str = Field(description="gate(위병소·정문) 또는 landmark(역)")
    address: str = Field(description="도로명 주소. 없으면 지번 주소")
    lng: float = Field(description="경도")
    lat: float = Field(description="위도")


class SearchPlacesResult(BaseModel):
    """출력 계약. 리스트를 바로 돌려주지 않고 모델로 한 번 감싼다. 도구 목록에 출력 스키마가 실리게 하려면
    반환 타입이 BaseModel 이어야 한다 (departure_calc 09-18 실측)."""

    places: list[Place] = Field(description="가까운 순. 못 찾으면 빈 목록")


@mcp.tool()
async def search_places(
    lng: float, lat: float, kind: Literal["gate", "landmark"], limit: int = 5
) -> SearchPlacesResult:
    """목적지 좌표 둘레에서 집결 후보를 찾을 때 쓴다. geocode 로 목적지 좌표를 구한 뒤 부른다.

    gate 는 절차 시작점(위병소·정문), landmark 는 절차 밖에서 만날 역이다. 3km 안에서 찾고 없으면 8km 로 넓힌다.

    Args:
        lng: 목적지 경도
        lat: 목적지 위도
        kind: "gate" 또는 "landmark"
        limit: 검색어 하나당 최대 몇 곳 (기본 5)

    Returns:
        places: [{name, kind, address, lng, lat}], 가까운 순
    """
    center = (lng, lat)  # 형 함수는 좌표를 (lng, lat) 한 묶음으로 받는다
    found: list[Place] = []
    seen: set[str] = set()  # 같은 곳이 두 검색어("위병소"·"정문")에 다 걸리면 한 번만

    async with httpx.AsyncClient(timeout=TIMEOUT_SEC) as client:
        for query in KIND_QUERIES[kind]:
            docs = await _nearby(client, query, center, limit=limit)
            for doc in docs:
                cand = _as_candidate(doc, kind)
                if cand["name"] not in seen:
                    seen.add(cand["name"])
                    found.append(Place(**cand))
    return SearchPlacesResult(places=found)
