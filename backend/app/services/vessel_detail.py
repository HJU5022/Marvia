"""입항 예정 선박 한 척 자세히 보기 (docs/specs/chat-search.md "선박 자세히 보기" 절, 10-01).

선박 표(직전 기항지·입출항 예정)에서 선명을 누르면 부른다. 새 데이터 소스는 없고 기존 MCP 도구 넷을 묶는다.
- 해수부: 입항 예정·실적, 접안 시설, 관제 이벤트 (get_port_schedule, 호출부호 우선)
- ShipFinder: 호출부호로 MMSI를 찾고(get_vessel_candidates) 실시간 AIS (get_live_position)
- searoute: 부산까지 남은 바닷길과 지금 속력으로 걸리는 시간 (estimate_distance)
판정은 하지 않는다. 도구 하나가 실패해도 나머지는 보여 주고, 실패는 errors에 출처별로 남긴다 (SDD 8절 partial 원칙).
위치가 오래됐는지는 rules.md position_stale_hours로 코드가 정한다 (화면이 정하지 않는다).
ShipFinder는 하루 호출 한도가 있어 같은 배는 10분 동안 다시 부르지 않는다.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from backend.app.services.rules import rule
from mcp_server.tools.distance import estimate_distance
from mcp_server.tools.live_position import get_live_position
from mcp_server.tools.port_schedule import get_port_schedule
from mcp_server.tools.vessel_candidates import get_vessel_candidates

CACHE_SEC = 600  # services/chat.py CACHE_SEC와 같다 (입항 예정 캐시와 같은 수명)
_cache: dict[tuple[str, str], tuple[float, dict]] = {}


def _err(source: str, result: dict) -> dict | None:
    """MCP 도구는 예외 대신 {error: {code, message}}를 돌려준다 (SDD 3.4). 그 모양이면 화면용 한 줄로."""
    e = result.get("error") if isinstance(result, dict) else None
    return {"source": source, "code": e.get("code"), "message": e.get("message")} if e else None


def _freshness(last_time: str | None) -> str:
    """fresh / stale / unknown. 기준은 rules.md position_stale_hours (CLAUDE.md: 임계값을 코드에 숫자로 두지 않는다)."""
    if not last_time:
        return "unknown"
    try:
        then = datetime.fromisoformat(str(last_time).replace("Z", "+00:00"))
    except ValueError:
        return "unknown"
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    hours = (datetime.now(timezone.utc) - then).total_seconds() / 3600
    return "stale" if hours > rule("position_stale_hours") else "fresh"


def detail(call_sign: str | None, ship_name: str | None) -> dict:
    """한 척의 자세한 정보. 호출부호가 있으면 그것으로 찾는다(선명은 한글·영문이 달라 매칭이 약하다)."""
    key = ((call_sign or "").upper(), (ship_name or "").upper())
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SEC:
        return hit[1]

    errors: list[dict] = []
    schedule = get_port_schedule(call_sign=call_sign or None, ship_name=None if call_sign else ship_name)
    if (e := _err("mof", schedule)):
        errors.append(e)
        schedule = None

    vessel, position, distance = None, None, None
    found = get_vessel_candidates(ship_name=ship_name or call_sign or "", call_sign=call_sign or None)
    if (e := _err("shipfinder", found)):
        errors.append(e)
    else:
        cands = found.get("candidates") or []
        vessel = cands[0] if cands else None
        if vessel is None:
            errors.append({"source": "shipfinder", "code": "not_found", "message": "AIS에서 이 배를 찾지 못했습니다"})
    if vessel:
        pos = get_live_position(vessel["mmsi"])
        if (e := _err("shipfinder", pos)):
            errors.append(e)
        else:
            position = {**pos, "freshness": _freshness(pos.get("last_time"))}
            dist = estimate_distance(pos["lat"], pos["lng"], pos.get("sog"))
            if (e := _err("searoute", dist)):
                errors.append(e)
            else:
                distance = dist
                hours = dist.get("calc_hours_at_sog")
                if hours is not None:
                    # 지금 속력을 끝까지 유지한다는 가정의 계산값이다. 판정에 쓰는 trusted_eta와는 다르다
                    distance["calc_eta"] = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()

    result = {"call_sign": call_sign, "ship_name": ship_name, "vessel": vessel, "position": position,
              "distance": distance, "schedule": schedule, "errors": errors}
    _cache[key] = (time.monotonic(), result)
    return result
