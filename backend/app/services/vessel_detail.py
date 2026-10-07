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

import re
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

from backend.app.services.rules import rule
# MCP 도구 4종은 /mcp를 거쳐 부른다 (10-02, services/mcp_client.py).
# route_points는 지도에 그릴 항로 좌표를 만드는 도우미라 MCP 도구가 아니다. 그래서 직접 부른다
from backend.app.services.mcp_client import (
    estimate_distance, get_live_position, get_port_schedule, get_vessel_candidates,
)
from mcp_server.tools.distance import route_points

CACHE_SEC = 600  # services/chat.py CACHE_SEC와 같다 (입항 예정 캐시와 같은 수명)
# 캐시에 두는 배 수 상한 (10-06 점검). 전에는 상한이 없고 사용자가 친 글자 그대로를 열쇠로 써서,
# 선명을 조금씩 바꿔 부르면 메모리가 끝없이 늘었다. 가장 오래 안 쓴 것부터 버린다(LRU)
CACHE_MAX = 256
_cache: OrderedDict[tuple[str, str], tuple[float, dict]] = OrderedDict()
_cache_lock = threading.Lock()


def _key(call_sign: str | None, ship_name: str | None) -> tuple[str, str]:
    """캐시 열쇠. 앞뒤 공백을 떼고 안쪽 공백을 하나로, 대문자로 맞춘다. 같은 배를 표기만 달리 불러도 한 칸을 쓴다.
    호출부호가 있으면 그것으로만 찾으므로(detail) 선명은 열쇠에서 뺀다."""
    def norm(value: str | None) -> str:
        return re.sub(r"\s+", " ", (value or "").strip()).upper()
    cs = norm(call_sign)
    return (cs, "") if cs else ("", norm(ship_name))


def _cache_get(key: tuple[str, str]) -> dict | None:
    """수명 안의 캐시 값. 쓰면 맨 뒤(최근)로 옮긴다. 수명이 지난 값은 지운다."""
    with _cache_lock:
        hit = _cache.get(key)
        if hit is None:
            return None
        if time.monotonic() - hit[0] >= CACHE_SEC:
            del _cache[key]
            return None
        _cache.move_to_end(key)
        return hit[1]


def _cache_put(key: tuple[str, str], value: dict) -> None:
    with _cache_lock:
        _cache[key] = (time.monotonic(), value)
        _cache.move_to_end(key)
        while len(_cache) > CACHE_MAX:
            _cache.popitem(last=False)


def cached(call_sign: str | None, ship_name: str | None) -> bool:
    """캐시에 있어 외부 호출 없이 답할 수 있나. 라우터가 하루 횟수 상한을 캐시 밖 조회에만 걸 때 쓴다 (routers/chat.py)."""
    return _cache_get(_key(call_sign, ship_name)) is not None


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
    key = _key(call_sign, ship_name)
    hit = _cache_get(key)
    if hit is not None:
        return hit

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
            # 지도에 그릴 남은 예상 바닷길. 실제 항적이 아니다 (화면에도 그렇게 적는다)
            position["route"] = route_points(pos["lat"], pos["lng"])
            if (e := _err("searoute", dist)):
                errors.append(e)
            else:
                distance = dist
                hours = dist.get("calc_hours_at_sog")
                if hours is not None:
                    # 지금 속력을 끝까지 유지한다는 가정의 계산값이다. 판정에 쓰는 trusted_eta와는 다르다
                    distance["calc_eta"] = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()

    result = {"call_sign": call_sign, "ship_name": ship_name, "vessel": vessel, "position": position,
              "distance": distance, "schedule": schedule, "errors": errors,
              # 이 결과를 만든 시각. 10분 캐시에서 다시 나가도 그대로라 화면이 "몇 시 기준"인지 보여 줄 수 있다 (10-06)
              "cached_at": datetime.now(timezone.utc).isoformat()}
    _cache_put(key, result)
    return result
