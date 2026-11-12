"""ShipFinder 조회: 배 후보 검색, 배 한 척의 지금 위치, 국적 (계획 8a, 설계 7.2 vessel_position).

실제 API와 재생 데이터가 같은 파싱 길을 지난다. 기본은 재생이고 MARVIA_SHIPFINDER_MODE=live에 키가 있을 때만
실제로 부른다. 값은 원본 그대로 돌려주고 판정은 하지 않는다. API의 무효 표시값만 None으로 바꾼다.
하지 않는 일: 어느 배가 내 화물의 배인지 고르기(tools/vessel_match.py), 신호(tools/signals.py).
[주의] 요청 주소에 키(key)가 들어간다. 주소·예외 글·바깥 응답 글을 로그·오류 글·LLM에 넣지 않는다.
[주의] 응답의 배 이름과 목적지 글(dest)은 바깥에서 온 자유 글이다. 목적지 글은 코드 밖으로 내보내지 않는다.
[주의] 실제 응답으로 확인하지 않았다(키와 실제 호출은 직접 할 일). 응답 모양은 v1 코드와 가공 fixture다.
[주의] 아직 그래프의 어느 노드도 이 모듈을 부르지 않는다. 연결은 다음 계획이다.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
from pydantic import BaseModel, ValidationError

from marvia.config import Settings
from marvia.identify.models import ToolError
from marvia.tools.rules import load_rules
from marvia.tools.vessel import KST, Position

for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)  # [왜] httpx는 INFO로 요청 주소(키 포함)를 찍는다
CFG = load_rules("shipfinder")
# src/marvia/tools/shipfinder.py에서 세 단계 올라가면 저장소 루트다 → 루트의 fixtures/shipfinder/
FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "shipfinder"

# 응답 값의 모양이 달라 읽다가 나는 예외. [왜] 그대로 올리면 부르는 쪽이 죽고 예외 글에 바깥 값이 실린다.
#      그 조회를 bad_response로 돌려준다 (시각이 너무 크면 OverflowError·OSError, 글자면 ValidationError)
SHAPE_ERRORS = (ValidationError, OverflowError, OSError, ValueError, TypeError, KeyError)

_lock = threading.Lock()
# 하루 한도 소진을 받은 한국 날짜. 같은 날에는 바깥을 부르지 않고 바로 quota_exhausted로 돌려준다.
# shortcut: 프로세스 메모리라 프로세스마다 한 번씩은 한도 소진 응답을 받는다,
#           프로세스가 여럿이 되면 DB로 옮긴다
_quota_day: date | None = None
# 배 번호 → 마지막으로 받은 위치.
# shortcut: 프로세스 메모리라 다시 띄우면 비고 프로세스끼리 나누지 않는다,
#           위치 이력을 저장하는 계획에서 DB로 옮긴다
_last_good: dict[int, Position] = {}


class VesselHit(BaseModel):
    """검색 결과 한 척. 검색 응답에는 위치와 목적지가 없다."""

    mmsi: int
    imo: int | None = None
    call_sign: str | None = None
    ship_name: str = ""
    last_time: datetime | None = None


def reset_state() -> None:
    """한도 막음과 캐시를 비운다. 시험이 쓴다."""
    global _quota_day
    with _lock:
        _quota_day = None
        _last_good.clear()


def _error(code: str) -> ToolError:
    """rules/shipfinder.yaml의 정한 글로만 오류를 만든다."""
    return ToolError(code=code, message=CFG["messages"][code], retryable=code in CFG["retryable"])


def _valid(data: dict, name: str):
    """칸의 값. 무효 표시값이거나 빈 글이면 None."""
    value = data.get(name)
    if value is None or value == CFG["invalid"].get(name) or (isinstance(value, str) and not value.strip()):
        return None
    return value.strip() if isinstance(value, str) else value


def _number(value) -> bool:
    """수인가. [왜] 참·거짓 글자는 파이썬에서 정수로도 읽혀 1이나 0으로 지나간다. 수로 치지 않는다"""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _epoch(data: dict, name: str) -> datetime | None:
    """초 단위 시각. 값이 없으면 None. 수가 아니면 TypeError를 낸다(부르는 쪽이 bad_response로 바꾼다)."""
    value = _valid(data, name)
    if value is None:
        return None
    if not _number(value):
        raise TypeError(name)
    return datetime.fromtimestamp(float(value), UTC)


def _call(
    client: httpx.Client,
    endpoint: str,
    params: dict,
    *,
    key: str,
    now: datetime,
    sleep: Callable[[float], None],
) -> dict | list | ToolError:
    """엔드포인트 하나를 부르고 data 칸을 돌려준다. 시간 초과·연결 오류·5xx는 retries번까지 다시 부른다."""
    global _quota_day
    today = now.astimezone(KST).date()
    if _quota_day == today:
        return _error("quota_exhausted")  # 오늘은 다시 불러도 같은 답이다. 헛호출을 쌓지 않는다
    last = "unavailable"
    for attempt in range(CFG["retries"] + 1):
        if attempt:
            sleep(CFG["backoff_s"] * attempt)
        try:
            response = client.get(endpoint, params={"key": key, **params})
        except httpx.TimeoutException:
            last = "timeout"
            continue
        except httpx.TransportError:  # [주의] 예외 글에 주소(키)가 있다. 종류만 본다
            last = "unavailable"
            continue
        except httpx.HTTPError:
            return _error("bad_response")
        if response.status_code >= 500:
            last = "unavailable"
            continue
        if response.status_code >= 400:
            return _error("bad_response")
        try:
            body = response.json()
        except ValueError:
            return _error("bad_response")
        status = body.get("status") if isinstance(body, dict) else None
        if not isinstance(status, int) or isinstance(status, bool):
            return _error("bad_response")  # [왜] 거짓 글자는 0과 같다고 읽혀 정상으로 지나간다
        if status != 0:
            # [왜] msg는 바깥에서 온 글이다. 옮기지 않고 정한 글로 바꾼다
            code = CFG["status_codes"].get(status, "api_error")
            if code == "quota_exhausted":
                with _lock:
                    _quota_day = today
            return _error(code)
        data = body.get("data")
        return data if isinstance(data, (dict, list)) else _error("bad_response")
    return _error(last)


def _speed(value) -> float | None:
    """속도 칸. 정수로 와도 소수로 담는다. 수가 아니면 TypeError를 낸다."""
    if value is None:
        return None
    if not _number(value):
        raise TypeError("sog")
    return float(value)


def search(
    keywords: str,
    *,
    key: str,
    client: httpx.Client,
    now: datetime | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[VesselHit] | ToolError:
    """배 이름이나 호출부호로 후보를 찾는다. 같은 이름의 배가 흔해서 좁히지 않고 그대로 돌려준다."""
    params = {"keywords": keywords, "max": CFG["max_hits"]}
    data = _call(client, "VesselSearch", params, key=key, now=now or datetime.now(UTC), sleep=sleep)
    if isinstance(data, ToolError):
        return data
    if not isinstance(data, list):
        return _error("bad_response")
    try:
        return [
            VesselHit.model_validate(
                {
                    "mmsi": row["mmsi"],
                    "imo": _valid(row, "imo"),
                    "call_sign": _valid(row, "call_sign"),
                    "ship_name": row.get("ship_name") or "",
                    "last_time": _epoch(row, "last_time"),
                },
                strict=True,
            )
            for row in data
            if isinstance(row, dict) and _number(row.get("mmsi"))
        ]
    except SHAPE_ERRORS:
        return _error("bad_response")  # [주의] 예외 글에는 바깥 값이 있다. 옮기지 않는다


def _cached(mmsi: int, code: str, now: datetime) -> Position | None:
    """실패 대신 쓸 마지막 위치. 빈도 초과는 정한 시간 안의 값만, 시간 초과와 한도 소진은 오래된 값도 쓴다."""
    kept = _last_good.get(mmsi)
    if kept is None or code not in CFG["cache_fallback"]:
        return None
    fresh = now - kept.fetched_at <= timedelta(hours=CFG["cache_ttl_hours"])
    return kept if fresh or code in CFG["cache_ignore_ttl"] else None


def fetch_position(
    mmsi: int,
    *,
    key: str,
    client: httpx.Client,
    now: datetime | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Position | ToolError:
    """배 한 척의 지금 위치. 못 받았고 마지막으로 받은 값이 있으면 그 값을 돌려준다(fetched_at이 옛 시각)."""
    moment = now or datetime.now(UTC)
    data = _call(client, "VesselPositionSingle", {"mmsi": str(mmsi)}, key=key, now=moment, sleep=sleep)
    if isinstance(data, ToolError):
        return _cached(mmsi, data.code, moment) or data
    if not isinstance(data, dict) or not all(_number(data.get(n)) for n in ("lat", "lng")):
        return _error("bad_response")
    try:
        found = Position.model_validate(
            {
                "mmsi": mmsi,
                "lat": float(data["lat"]),
                "lng": float(data["lng"]),
                "sog": _speed(_valid(data, "sog")),
                "navstat": _valid(data, "navistat"),
                "dest": _valid(data, "dest"),
                "dest_code": _valid(data, "destcode"),
                "ais_eta": _epoch(data, "eta"),
                "last_time": _epoch(data, "last_time"),
                "fetched_at": moment,
            },
            strict=True,
        )
    except SHAPE_ERRORS:
        return _error("bad_response")  # [주의] 예외 글에는 바깥 값이 있다. 옮기지 않는다
    with _lock:
        _last_good[mmsi] = found
    return found


def fetch_flag(
    mmsi: int,
    *,
    key: str,
    client: httpx.Client,
    now: datetime | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> str | None | ToolError:
    """배의 국적(등록지) 글. 없으면 None."""
    data = _call(
        client, "VesselFlagInfo", {"mmsi": str(mmsi)}, key=key, now=now or datetime.now(UTC), sleep=sleep
    )
    if isinstance(data, ToolError):
        return data
    registry = _valid(data, "registry") if isinstance(data, dict) else None
    # [왜] 국적은 글이다. 수나 목록이 오면 모양이 다른 응답이다
    return registry if registry is None or isinstance(registry, str) else _error("bad_response")


def _replay(request: httpx.Request) -> httpx.Response:
    """재생: fixtures/shipfinder/<엔드포인트>/<열쇠>.json. 없으면 검색은 0건, 나머지는 대상 없음이다."""
    endpoint = request.url.path.rstrip("/").rsplit("/", 1)[-1]
    params = request.url.params
    raw = params.get("keywords", "") if endpoint == "VesselSearch" else params.get("mmsi", "")
    name = re.sub(r"[^0-9A-Z]+", "_", raw.strip().upper()).strip("_") or "_"
    path = FIXTURES / re.sub(r"[^A-Za-z]", "", endpoint) / f"{name}.json"
    if path.exists():
        return httpx.Response(200, text=path.read_text(encoding="utf-8"))
    empty = {"status": 0, "data": []} if endpoint == "VesselSearch" else {"status": 3}
    return httpx.Response(200, text=json.dumps(empty))


def _session() -> tuple[httpx.Client, str] | ToolError:
    """설정대로 클라이언트와 키를 만든다. 재생이면 바깥 연결 없이 fixture를 읽는 클라이언트다."""
    settings = Settings()
    if settings.shipfinder_mode != "live":
        return httpx.Client(transport=httpx.MockTransport(_replay), base_url=CFG["base_url"]), "replay"
    key = settings.shipfinder_key.get_secret_value()
    if not key:
        return _error("no_key")
    # [왜] follow_redirects=False: 넘겨 주는 주소를 따라가면 키가 다른 호스트로 갈 수 있다
    return httpx.Client(base_url=CFG["base_url"], timeout=CFG["timeout_s"], follow_redirects=False), key


def vessel_position(mmsi: int) -> Position | ToolError:
    """배 한 척의 지금 위치. 기본은 재생 데이터, MARVIA_SHIPFINDER_MODE=live에 키가 있을 때만 실제 API."""
    session = _session()
    if isinstance(session, ToolError):
        return session
    client, key = session
    with client:
        return fetch_position(mmsi, key=key, client=client)


def vessel_candidates(keywords: str) -> list[VesselHit] | ToolError:
    """배 이름이나 호출부호로 찾은 후보 목록. 고르지 않는다."""
    session = _session()
    if isinstance(session, ToolError):
        return session
    client, key = session
    with client:
        return search(keywords, key=key, client=client)
