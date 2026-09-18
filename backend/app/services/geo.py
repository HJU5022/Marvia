"""지명 → 좌표. 지오코딩과 집결 후보 생성. (SDD 5절 2·3단계, 6절 geocode·search_places)

바깥 호출은 이 파일과 routes.py 에만 둔다 (BACKEND_GUIDE).

MCP 로 가는 길:
  SDD 1절은 이 파일이 MCP 클라이언트를 거치게 돼 있다. MCP 도구(mcp_server/tools/geocode.py)는 아직 없어서
  지금은 같은 카카오 로컬 API 를 직접 부른다. 부르는 자리는 _kakao_keyword 하나뿐이라, 도구가 생기면
  그 함수 속만 MCP 호출로 바꾸면 된다. 키(KAKAO_REST_KEY)는 어느 쪽이든 서버 환경변수라 배포는 그대로다.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from backend.app.schemas.result import GeocodedPin
from backend.app.schemas.slots import Slots

KAKAO_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
TIMEOUT_SEC = 8.0

# 같은 이름이 여러 곳에 있을 때 목적지에 가까운 쪽을 고른다 (SDD 6절 geocode 의 bias_lng·bias_lat).
# "마산역"은 창원에도 고양에도 있다. 목적지가 진해면 창원 쪽이 맞다.
# 카카오의 radius 로 범위를 좁히면 이름이 안 맞는 근처 가게가 잡히므로, 검색은 전국으로 하고
# 이름 점수가 가장 높은 것들 안에서만 거리로 고른다.
SEARCH_SIZE = 10

# 목적지에서 이 정도(위경도 차이, 대략 60km) 안이면 "같은 지역"으로 본다.
# 같은 이름이 여러 지역에 있을 때 지역만 거르는 용도다. 거른 뒤 순서는 검색 순위를 따른다.
SAME_REGION_DEG = 0.6

# 검색이 비면 검색어를 줄여 다시 본다. 사람은 "김해시청 앞", "여의도 고객사"처럼 쓰는데
# 지도에 그런 이름의 장소는 없다. 꼬리말을 떼고 다시 찾는다.
TAIL_WORDS = ("앞", "근처", "쪽", "일대", "부근", "인근")

# 확신도. 지오코딩이 애매하면 사용자에게 핀을 확인받는다 (SDD 5절 2단계, 기준값 0.8)
CONF_EXACT = 0.95  # 검색어의 낱말이 결과 이름·주소에 전부 들어 있다
CONF_STATION = 0.9  # 지하철역 우선 규칙 (SDD 6절 geocode)
CONF_PARTIAL = 0.75  # 낱말이 절반 넘게 맞는다. 확인을 받는 쪽으로
CONF_WEAK = 0.5  # 그 밖에


class GeocodeFailed(RuntimeError):
    """지명을 좌표로 바꾸지 못했다. 파이프라인이 failed 로 답한다."""


def _key() -> str:
    key = os.environ.get("KAKAO_REST_KEY")
    if not key:
        raise GeocodeFailed("KAKAO_REST_KEY 가 없습니다")
    return key


async def _kakao_keyword(client: httpx.AsyncClient, query: str, size: int = SEARCH_SIZE) -> list[dict[str, Any]]:
    """카카오 로컬 키워드 검색. MCP geocode 도구가 생기면 이 함수 속만 바꾼다."""
    params: dict[str, Any] = {"query": query, "size": size}
    res = await client.get(
        KAKAO_KEYWORD_URL,
        params=params,
        headers={"Authorization": f"KakaoAK {_key()}"},
    )
    res.raise_for_status()
    return res.json().get("documents", [])


def _variants(query: str) -> list[str]:
    """검색어와, 결과가 없을 때 대신 써 볼 짧은 말들. 앞에 있는 것부터 쓴다."""
    out = [query]
    words = query.split()
    if words and words[-1] in TAIL_WORDS:  # "김해시청 앞" → "김해시청"
        out.append(" ".join(words[:-1]))
    if len(words) > 1:  # "여의도 고객사" → "여의도"
        out.append(" ".join(words[:-1]))
        out.append(words[0])
    return list(dict.fromkeys(w for w in out if w))


async def _search(client: httpx.AsyncClient, query: str) -> tuple[list[dict[str, Any]], str]:
    """검색어 그대로 → 꼬리말 뗀 말 → 앞말 순으로 찾는다. 결과와 실제로 쓴 검색어를 돌려준다."""
    for variant in _variants(query):
        docs = await _kakao_keyword(client, variant)
        if docs:
            return docs, variant
    return [], query


def _score(query: str, doc: dict[str, Any], index: int) -> float:
    """이 결과를 얼마나 믿을지. 값이 0.8 미만이면 사용자 확인으로 넘어간다.

    사람은 "부산 사상"처럼 지역과 동네를 섞어 쓴다. 그래서 이름만 보지 않고 이름과 주소를 합친 글에
    검색어의 낱말이 몇 개나 들어 있는지 센다. 전부 들어 있으면 그 자리가 맞다고 보고, 절반 아래면
    사용자에게 묻는다. 지어낸 좌표로 계산까지 가는 것보다 한 번 묻는 쪽이 싸다.
    """
    haystack = " ".join(
        [doc.get("place_name", ""), doc.get("road_address_name", ""), doc.get("address_name", "")]
    )
    words = [w for w in query.split() if w]
    hit = sum(1 for w in words if w in haystack)
    if words and hit == len(words):
        return CONF_EXACT
    if doc.get("category_group_code") == "SW8":  # 지하철역
        return CONF_STATION
    if words and hit / len(words) > 0.5:
        return CONF_PARTIAL
    return CONF_PARTIAL if index == 0 else CONF_WEAK


def _distance_key(doc: dict[str, Any], bias: tuple[float, float]) -> float:
    """목적지와 얼마나 떨어져 있는지. 순서를 매기는 용도라 실제 거리(m)일 필요는 없다."""
    return (float(doc["x"]) - bias[0]) ** 2 + (float(doc["y"]) - bias[1]) ** 2


def _pick(
    query: str, docs: list[dict[str, Any]], bias: tuple[float, float] | None = None
) -> tuple[dict[str, Any], float]:
    """이름 점수가 가장 높은 것들 중에서 고른다 (SDD 6절).

    목적지를 알면 거리부터 본다. "마산역"은 창원에도 김포에도 있는데, 목적지가 진해면 창원 쪽이다.
    목적지를 모르면 지하철역을 먼저 본다. 사람이 "OO역에서 보자"고 하면 대개 역이지 그 앞 가게가 아니다.
    그것도 아니면 카카오가 준 순서를 그대로 믿는다.
    """
    scored = [(_score(query, doc, i), doc) for i, doc in enumerate(docs)]
    best = max(score for score, _ in scored)
    top = [doc for score, doc in scored if score == best]

    if bias and len(top) > 1:
        # 지역만 거른다. 거리로 줄세우면 역 대신 역 옆 아파트를 고르게 된다
        near = [d for d in top if _distance_key(d, bias) <= SAME_REGION_DEG**2]
        top = near or top
    stations = [d for d in top if d.get("category_group_code") == "SW8"]
    return (stations or top)[0], best


async def geocode_one(
    client: httpx.AsyncClient,
    query: str,
    kind: str,
    label: str | None = None,
    bias: tuple[float, float] | None = None,
) -> GeocodedPin:
    """지명 하나를 핀 하나로. bias 는 목적지 좌표 (그 둘레를 먼저 본다)."""
    docs, used = await _search(client, query)
    if not docs:
        raise GeocodeFailed(f"'{query}' 위치를 찾지 못했습니다")
    doc, confidence = _pick(used, docs, bias)
    if used != query:
        # 검색어를 줄여 찾은 자리다. 사용자에게 확인을 받는다
        confidence = min(confidence, CONF_PARTIAL)
    return GeocodedPin(
        name=label or query,
        lng=float(doc["x"]),
        lat=float(doc["y"]),
        confidence=confidence,
        kind=kind,  # type: ignore[arg-type]
    )


async def geocode_all(slots: Slots) -> list[GeocodedPin]:
    """참석자 출발지·집결지·목적지·픽업 지점을 한 번에 좌표로 (SDD 5절 2단계).

    참석자 핀의 name 은 참석자 이름이다. 화면이 이름으로 핀과 참석자를 잇고, 확인한 좌표도
    이름으로 돌아온다 (AgentRequest.confirmed_participants).

    한 명이 실패해도 나머지는 살린다. 전부 실패하면 예외를 올린다.
    """
    pins: list[GeocodedPin] = []
    async with httpx.AsyncClient(timeout=TIMEOUT_SEC) as client:
        # 목적지를 먼저 찾는다. 나머지 지명은 그 둘레를 먼저 보게 된다
        bias: tuple[float, float] | None = None
        if slots.destination:
            try:
                dest = await geocode_one(client, slots.destination, "destination")
                pins.append(dest)
                bias = (dest.lng, dest.lat)
            except (GeocodeFailed, httpx.HTTPError):
                pass

        for p in slots.participants:
            if p.origin:
                try:
                    pins.append(await geocode_one(client, p.origin, "participant", label=p.name, bias=bias))
                except (GeocodeFailed, httpx.HTTPError):
                    continue
            if p.pickup_at:
                try:
                    pins.append(await geocode_one(client, p.pickup_at, "pickup", bias=bias))
                except (GeocodeFailed, httpx.HTTPError):
                    continue

        if slots.rendezvous:
            try:
                pins.append(await geocode_one(client, slots.rendezvous.name, "rendezvous", bias=bias))
            except (GeocodeFailed, httpx.HTTPError):
                pass

    if not pins:
        raise GeocodeFailed("좌표를 하나도 찾지 못했습니다")
    return pins


# ─────────────────────────────────────────────────────────────────────────────
# 3단계: 집결 후보 생성 (SDD 5절 3단계, 6절 search_places)
# ─────────────────────────────────────────────────────────────────────────────

# 목적지 둘레에서 찾을 절차 시작점. kind 는 SDD 4절 Candidate.kind 다.
# 검색어는 카카오 로컬에 넣는 말이고, 규칙값(절차 소요·여유)과는 다르다.
GATE_QUERIES: list[tuple[str, str]] = [("위병소", "gate"), ("정문", "gate")]
# 이름에 이 말이 들어간 결과만 쓴다. "진해역 공중화장실" 같은 것이 위병소 후보로 오지 않게.
GATE_NAME_WORDS = ("위병소", "정문", "출입문", "게이트")
STATION_SUFFIX = "역"
SUBWAY_CATEGORY = "SW8"
CANDIDATE_RADIUS_M = 3000
CANDIDATE_RADIUS_WIDE_M = 8000  # 좁게 못 찾으면 한 번 넓혀 본다
MAX_CANDIDATES = 3


async def _nearby(
    client: httpx.AsyncClient, query: str, center: tuple[float, float], limit: int = 5
) -> list[dict[str, Any]]:
    """목적지 둘레만 본다. 후보는 목적지에서 걸어갈 만한 거리여야 한다.

    검색어에 목적지 이름을 붙이지 않는다. "진해 기지 위병소"라는 이름의 장소는 지도에 없고,
    있는 것은 그냥 "위병소"다. 자리는 좌표(x, y)와 radius 로 좁힌다.
    """
    for radius in (CANDIDATE_RADIUS_M, CANDIDATE_RADIUS_WIDE_M):
        res = await client.get(
            KAKAO_KEYWORD_URL,
            params={
                "query": query,
                "x": center[0],
                "y": center[1],
                "radius": radius,
                "sort": "distance",
                "size": limit,
            },
            headers={"Authorization": f"KakaoAK {_key()}"},
        )
        res.raise_for_status()
        docs = res.json().get("documents", [])
        if docs:
            return docs
    return []


def _as_candidate(doc: dict[str, Any], kind: str) -> dict[str, Any]:
    return {
        "name": doc["place_name"],
        "kind": kind,
        "address": doc.get("road_address_name") or doc.get("address_name", ""),
        "lng": float(doc["x"]),
        "lat": float(doc["y"]),
    }


async def build_candidates(slots: Slots, pins: list[GeocodedPin]) -> list[dict[str, Any]]:
    """집결 후보를 찾는다. 순위·이유는 여기서 매기지 않는다 (5·6단계 몫).

    절차가 시작되는 자리를 먼저 둔다 (access.md rendezvous_is_procedure_start).
      함정: 목적지 둘레의 위병소·정문. 이름에 그 말이 들어간 결과만 쓴다
      SI: 목적지 건물 1층. 고객사 로비는 목적지 그 자체라 따로 찾지 않는다
    그 밖에서 만날 때를 위해 가까운 역을 하나 더 둔다 (outside_landmark_kinds).
    한 곳도 못 찾으면 목적지 좌표 자체를 후보로 쓴다 (SDD 5절 3단계 "후보 0곳이면").
    """
    dest = next((p for p in pins if p.kind == "destination"), None)
    if dest is None:
        raise GeocodeFailed("목적지 좌표가 없어 집결 후보를 찾지 못했습니다")
    center = (dest.lng, dest.lat)
    found: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(cand: dict[str, Any]) -> None:
        if cand["name"] not in seen:
            seen.add(cand["name"])
            found.append(cand)

    async with httpx.AsyncClient(timeout=TIMEOUT_SEC) as client:
        if slots.preset == "si_deploy":
            # 인솔이 시작되는 자리는 목적지 건물 1층이다
            add({"name": f"{dest.name} 1층", "kind": "lobby", "address": "", "lng": dest.lng, "lat": dest.lat})
        else:
            for query, kind in GATE_QUERIES:
                if len(found) >= 2:
                    break
                try:
                    docs = await _nearby(client, query, center)
                except httpx.HTTPError:
                    continue
                for doc in docs:
                    if any(w in doc["place_name"] for w in GATE_NAME_WORDS):
                        add(_as_candidate(doc, kind))
                        break

        # 절차 밖 랜드마크: 가까운 역 하나
        try:
            docs = await _nearby(client, STATION_SUFFIX, center)
        except httpx.HTTPError:
            docs = []
        # 지하철역 분류를 먼저 본다. 없으면 "진해역"처럼 한 낱말로 끝나는 이름만 쓴다.
        # "르컬렉티브 부산역"처럼 역 이름을 가게 이름에 붙인 곳을 거르기 위해서다.
        station = next((d for d in docs if d.get("category_group_code") == SUBWAY_CATEGORY), None)
        if station is None:
            station = next(
                (d for d in docs if d["place_name"].endswith(STATION_SUFFIX) and " " not in d["place_name"]),
                None,
            )
        if station is not None:
            add(_as_candidate(station, "landmark"))

    if not found:
        add({"name": dest.name, "kind": "landmark", "address": "", "lng": dest.lng, "lat": dest.lat})
    return found[:MAX_CANDIDATES]
