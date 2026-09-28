"""도구 get_vessel_candidates (작업 B3). 선명으로 선박 후보를 찾는다.

UNI-PASS는 선명과 국적만 주고 IMO·호출부호를 주지 않는다 (PRD 6.6). 그래서 선명으로 검색한 뒤
어느 배인지는 받는 쪽이 정한다. 동명 선박이 흔해서 후보를 좁히지 않고 그대로 넘기는 것이 이 도구의 일이다.

호출 비용: VesselSearch는 1회지만 후보의 목적지·선종·국적은 검색 응답에 없어서
후보마다 VesselPositionSingle과 VesselFlagInfo를 한 번씩 더 불러야 한다. 스타터 키의 빈도 제한
(status 23·29)을 생각해 상세 조회는 상위 MAX_LOOKUPS명까지만 하고, 그 안에서는 동시에 부른다.
순서대로 부르면 5척에 3초가 넘어 p95 목표(15초)를 갉아먹는다.

호출부호(call_sign)는 검색 응답에 있는 값을 그대로 넘긴다. 해수부 조회의 키가 되는데,
선명은 해수부가 한글이고 ShipFinder가 영문이라 서로 맞추기 어렵다.

출력 계약은 mcp_server/schemas.py의 VesselCandidatesResult다 (C4, SDD 3.4).
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Annotated

from pydantic import Field

from backend.app.clients.shipfinder import ShipFinderClient, ShipFinderError, VesselHit
from mcp_server.schemas import ToolError, VesselCandidate, VesselCandidatesResult

MAX_LOOKUPS = 5  # 상세 조회(위치·국적)를 붙일 후보 수 상한
IMO_RANGE = range(1000000, 10000000)  # 실제 응답에 7자리가 아닌 IMO가 섞여 온다

make_client = ShipFinderClient  # 테스트가 fixture 클라이언트로 바꿔 끼우는 자리


def _similarity(query: str, name: str) -> float:
    return round(SequenceMatcher(None, query.upper().strip(), name.upper().strip()).ratio(), 2)


def _newest_per_imo(hits: list[VesselHit]) -> list[VesselHit]:
    """같은 IMO면 last_time이 가장 최신인 1건만 남긴다 (C4).

    IMO가 없거나 7자리가 아닌 값은 서로 다른 배로 본다. 실제 응답에 9자리 같은
    값이 섞여 와서, 이런 값으로 묶으면 남의 배를 한 척으로 합쳐 버린다.
    """
    newest: dict[int, VesselHit] = {}
    kept: list[VesselHit] = []
    for hit in hits:
        if hit.imo not in IMO_RANGE:
            kept.append(hit)
            continue
        seen = newest.get(hit.imo)
        if seen is None or (hit.last_time or datetime.min.replace(tzinfo=timezone.utc)) > (
            seen.last_time or datetime.min.replace(tzinfo=timezone.utc)
        ):
            newest[hit.imo] = hit
    return kept + list(newest.values())


def _fetch_details(client: ShipFinderClient, mmsis: list[int]) -> dict[int, tuple]:
    """후보들의 목적지·선종·국적을 동시에 받아 온다. 실패한 후보는 빈 값으로 둔다."""

    def one(mmsi: int) -> tuple[int, tuple]:
        try:
            pos = client.position(mmsi)
            return mmsi, (pos.dest, pos.ship_type, client.flag(mmsi))
        except ShipFinderError:
            return mmsi, (None, None, None)  # 상세가 없어도 후보 자체는 남긴다

    if not mmsis:
        return {}
    with ThreadPoolExecutor(max_workers=len(mmsis)) as pool:
        return dict(pool.map(one, mmsis))


def get_vessel_candidates(
    ship_name: Annotated[str, Field(description="찾을 선명. UNI-PASS 화물통관진행정보의 선명을 그대로 넣는다. 예: TEST STAR")],
    nationality: Annotated[str | None, Field(description="아는 국적의 영문 표기(예: Panama, Korea). 주면 국적이 다른 후보를 뺀다")] = None,
    eta_window_days: Annotated[int, Field(description="최근 며칠 안에 신호를 보낸 배만 볼지. 예: 7(기본값)", ge=1, le=90)] = 7,
) -> dict:
    """선명만 알고 그 배의 MMSI를 아직 모를 때 쓴다.

    선박 식별의 첫 단계다. 선명으로 ShipFinder를 검색해 그 이름을 쓰는 배를 후보로 모두 돌려준다.
    같은 이름의 배가 흔해서 여러 척이 나올 수 있고, 어느 배가 맞는지는 이 도구가 정하지 않는다.
    같은 IMO는 가장 최근에 신호를 보낸 MMSI 한 건만 남긴다.
    돌려주는 값: 후보마다 mmsi, imo, name, call_sign, flag, dest, ship_type, last_time, similarity.
    그리고 source, fetched_at, cached_at(호출 한도에 걸려 담아둔 값을 줬을 때 그 시각).
    similarity는 선명이 얼마나 비슷한지일 뿐 내 화물 배라는 뜻이 아니다.
    """
    try:
        client = make_client()
        hits = client.search(ship_name, max=10).hits
    except ShipFinderError as e:
        return {"error": ToolError(**e.to_dict()).model_dump()}

    cutoff = datetime.now(timezone.utc) - timedelta(days=eta_window_days)
    fresh = [h for h in _newest_per_imo(hits) if h.last_time and h.last_time >= cutoff]
    fresh.sort(key=lambda h: (_similarity(ship_name, h.ship_name), h.last_time), reverse=True)

    # 상세 조회는 상위 후보까지만 하고, 그 안에서는 동시에 부른다 (호출 한도와 지연 둘 다 고려)
    details = _fetch_details(client, [h.mmsi for h in fresh[:MAX_LOOKUPS]])

    candidates = []
    for hit in fresh:
        dest, ship_type, flag = details.get(hit.mmsi, (None, None, None))
        # 국적을 모르는 후보는 남긴다. 다르다는 근거가 없는데 빼면 진짜 그 배를 놓친다
        if nationality and flag and nationality.lower() not in flag.lower():
            continue
        candidates.append(
            VesselCandidate(
                mmsi=hit.mmsi,
                imo=hit.imo,
                name=hit.ship_name,
                call_sign=hit.call_sign,
                flag=flag,
                dest=dest,
                last_time=hit.last_time,
                ship_type=ship_type,
                similarity=_similarity(ship_name, hit.ship_name),
            )
        )

    return VesselCandidatesResult(
        candidates=candidates,
        fetched_at=datetime.now(timezone.utc),
        cached_at=client.last_cached_at,  # 검색이 캐시로 답했으면 그 시각
    ).model_dump(mode="json")
