"""ShipFinder AIS API 클라이언트 (작업 B2).

VesselSearch(선박 검색)와 VesselPositionSingle(단일 선박 위치) 두 개만 부릅니다.
MCP 도구(B3·B4)와 수집 워커(D1)가 이 클라이언트를 같이 씁니다. 위치는 SDD 1.1·CLAUDE.md의 backend/app/clients/.

- 값은 원본 그대로 돌려주고 판정(freshness 등)은 하지 않습니다. 판정은 services/signals.py 몫입니다.
- API의 "무효" 표시값(sog -1, hdg 511, eta 0 등)만 None으로 바꾸고, 원본은 raw에 남깁니다.
- 빈도 초과(23·29)로 실패하면 마지막 성공 응답을 캐시에서 돌려줍니다 (B8, TTL 6시간).
  캐시 값은 fetched_at이 과거라서 받는 쪽이 오래된 값임을 알 수 있습니다.

명세: https://docs.shipfinder.com/428749512e0 (검색), /428990613e0 (위치), /8401497m0 (상태 코드)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from backend.app.clients.cache import ResponseCache
from backend.app.clients.retry import with_retry

BASE_URL = "https://api.elaneglobal.com/v1/AIS/"
TIMEOUT_SEC = float(os.environ.get("SHIPFINDER_TIMEOUT_SEC", 10))  # 환경변수로 조정 가능

# SDD 5.2 상태 코드 매핑. 목록에 없는 코드는 "error".
# 13 = Server busy (docs.shipfinder.com/8401497m0). 잠시 뒤 다시 부르면 되므로 retryable (09-22 확인).
_STATUS_CODES = {
    3: "not_found",
    9: "bad_key",
    13: "busy",
    21: "no_permission",
    23: "rate_limited",
    29: "rate_limited",
}
_RETRYABLE = {"busy", "rate_limited", "timeout"}


class ShipFinderError(Exception):
    """ShipFinder 호출 실패. MCP 도구가 받아서 {error: {code, message, retryable}}로 바꿉니다."""

    def __init__(self, code: str, message: str, status: int | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status
        self.retryable = code in _RETRYABLE

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


@dataclass(frozen=True)
class VesselHit:
    """VesselSearch 결과 1건. 검색 응답에는 목적지·위치가 없습니다."""

    mmsi: int
    imo: int | None
    call_sign: str | None
    ship_name: str
    match_type: int | None
    last_time: datetime | None


@dataclass(frozen=True)
class SearchResult:
    hits: list[VesselHit]
    fetched_at: datetime


@dataclass(frozen=True)
class VesselPosition:
    mmsi: int
    imo: int | None
    call_sign: str | None
    ship_name: str
    ship_type: int | None
    lat: float
    lng: float
    sog: float | None
    cog: float | None
    hdg: int | None
    navistat: int | None
    dest: str | None
    destcode: str | None
    ais_eta: datetime | None
    draught: float | None
    last_time: datetime | None
    fetched_at: datetime
    raw: dict = field(repr=False)


def _ts(value) -> datetime | None:
    """Unix 초 → UTC datetime. 0·빈 값은 None."""
    if not value:
        return None
    return datetime.fromtimestamp(int(value), tz=timezone.utc)


def _none_if(value, *invalid):
    if value is None or value in invalid:
        return None
    return value


def _text(value) -> str | None:
    return (value.strip() or None) if isinstance(value, str) else None


class ShipFinderClient:
    # 클라이언트를 새로 만들어도 캐시는 남아야 해서 클래스 변수로 둔다
    cache = ResponseCache()

    #: 마지막 호출이 캐시로 답한 시각. 실시간으로 받았으면 None (SDD 8절 "근거에 캐시 표시")
    last_cached_at: datetime | None

    def __init__(self, key: str | None = None, transport: httpx.BaseTransport | None = None):
        self._key = key or os.environ.get("SHIPFINDER_KEY", "")
        if not self._key:
            raise ShipFinderError("bad_key", "SHIPFINDER_KEY가 비어 있습니다")
        self._http = httpx.Client(base_url=BASE_URL, timeout=TIMEOUT_SEC, transport=transport)
        self.last_cached_at = None

    def _cached(self, key: str, fetch):
        """호출해 보고, 빈도 초과면 마지막 성공 값을 돌려준다 (SDD 5.2).

        다른 실패(권한 없음, 없는 배 등)는 캐시로 가리지 않는다. 그 실패는 사실이기 때문이다.
        """
        try:
            value = fetch()
        except ShipFinderError as e:
            if e.code != "rate_limited":
                raise
            entry = self.cache.entry(key)
            if entry is None:
                raise
            self.last_cached_at = entry.cached_at
            return entry.value
        self.cache.set(key, value)
        self.last_cached_at = None
        return value

    def close(self) -> None:
        self._http.close()

    def _get(self, endpoint: str, params: dict) -> dict:
        def call() -> httpx.Response:
            resp = self._http.get(endpoint, params={"key": self._key, **params})
            resp.raise_for_status()
            return resp

        try:
            # 타임아웃·5xx는 2회까지 다시 부른다 (A9, SDD 8절)
            body = with_retry(call, name=f"shipfinder:{endpoint}").json()
        except httpx.TimeoutException as e:
            raise ShipFinderError("timeout", f"{endpoint} 응답 시간 초과") from e
        except httpx.HTTPStatusError as e:
            raise ShipFinderError("error", f"{endpoint} HTTP {e.response.status_code}") from e
        except (httpx.HTTPError, ValueError) as e:
            raise ShipFinderError("error", f"{endpoint} 호출 실패: {type(e).__name__}") from e

        status = body.get("status")
        if status != 0:
            code = _STATUS_CODES.get(status, "error")
            raise ShipFinderError(code, body.get("msg") or f"status {status}", status=status)
        return body

    def search(self, keywords: str, max: int = 10) -> SearchResult:
        """선명·호출부호·MMSI·IMO로 검색. max는 API 상한 100."""
        return self._cached(f"shipfinder:search:{keywords}:{max}", lambda: self._search(keywords, max))

    def _search(self, keywords: str, max: int) -> SearchResult:
        body = self._get("VesselSearch", {"keywords": keywords, "max": min(max, 100)})
        hits = [
            VesselHit(
                mmsi=int(d["mmsi"]),
                imo=_none_if(d.get("imo"), 0),
                call_sign=_text(d.get("call_sign")),
                ship_name=d.get("ship_name", ""),
                match_type=d.get("match_type"),
                last_time=_ts(d.get("last_time")),
            )
            for d in body.get("data") or []
        ]
        return SearchResult(hits=hits, fetched_at=datetime.now(timezone.utc))

    def flag(self, mmsi: int | str) -> str | None:
        """선박 등록 국가. MMSI 하나당 한 번 불러야 한다 (VesselFlagInfo)."""
        return self._cached(f"shipfinder:flag:{mmsi}", lambda: self._flag(mmsi))

    def _flag(self, mmsi: int | str) -> str | None:
        body = self._get("VesselFlagInfo", {"mmsi": str(mmsi)})
        return _text((body.get("data") or {}).get("registry"))

    def position(self, mmsi: int | str) -> VesselPosition:
        return self._cached(f"shipfinder:pos:{mmsi}", lambda: self._position(mmsi))

    def _position(self, mmsi: int | str) -> VesselPosition:
        body = self._get("VesselPositionSingle", {"mmsi": str(mmsi)})
        d = body.get("data")
        if not d:
            raise ShipFinderError("not_found", f"MMSI {mmsi} 위치 없음", status=0)
        return VesselPosition(
            mmsi=int(d["mmsi"]),
            imo=_none_if(d.get("imo"), 0),
            call_sign=_text(d.get("call_sign")),
            ship_name=d.get("ship_name", ""),
            ship_type=d.get("ship_type"),
            lat=d["lat"],
            lng=d["lng"],
            sog=_none_if(d.get("sog"), -1),
            cog=_none_if(d.get("cog"), -1),
            hdg=_none_if(d.get("hdg"), 511),
            navistat=_none_if(d.get("navistat"), -1),
            dest=_text(d.get("dest")),
            destcode=_text(d.get("destcode")),
            ais_eta=_ts(d.get("eta")),
            draught=d.get("draught"),
            last_time=_ts(d.get("last_time")),
            fetched_at=datetime.now(timezone.utc),
            raw=d,
        )
