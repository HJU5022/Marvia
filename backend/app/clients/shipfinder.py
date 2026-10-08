"""ShipFinder AIS API 클라이언트 (작업 B2).

VesselSearch(선박 검색)와 VesselPositionSingle(단일 선박 위치) 두 개만 부릅니다.
MCP 도구(B3·B4)와 수집 워커(D1)가 이 클라이언트를 같이 씁니다. 위치는 SDD 1.1·CLAUDE.md의 backend/app/clients/.

- 값은 원본 그대로 돌려주고 판정(freshness 등)은 하지 않습니다. 판정은 services/judge/signals.py 몫입니다.
- API의 "무효" 표시값(sog -1, hdg 511, eta 0 등)만 None으로 바꾸고, 원본은 raw에 남깁니다.
- 빈도 초과(23·29)로 실패하면 마지막 성공 응답을 캐시에서 돌려줍니다 (B8, TTL은 rules.md api_cache_ttl_hours).
  캐시 값은 fetched_at이 과거라서 받는 쪽이 오래된 값임을 알 수 있습니다.
- 하루 호출 한도 소진(38)을 한 번 받으면 그 프로세스는 한국 날짜가 바뀔 때까지 ShipFinder를 더 부르지 않습니다.

명세: https://docs.shipfinder.com/428749512e0 (검색), /428990613e0 (위치), /8401497m0 (상태 코드)
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import httpx

from backend.app.clients.cache import ResponseCache
from backend.app.clients.replay import replay_enabled, shipfinder_transport
from backend.app.clients.retry import with_retry
from backend.app.observability.langfuse import tool_span
from backend.app.observability.logging import log_failure

BASE_URL = "https://api.elaneglobal.com/v1/AIS/"
TIMEOUT_SEC = float(os.environ.get("SHIPFINDER_TIMEOUT_SEC", 10))  # 환경변수로 조정 가능

# SDD 5.2 상태 코드 매핑. 목록에 없는 코드는 "error".
# 13 = Server busy (docs.shipfinder.com/8401497m0). 잠시 뒤 다시 부르면 되므로 retryable.
_STATUS_CODES = {
    3: "not_found",
    # 6 = 키 만료, 7 = 키 잠김 (docs.shipfinder.com/8401497m0). 키를 바꾸기 전에는 다시 불러도 같아 bad_key로 묶는다.
    # 무료 키 기간이 끝나 6이 왔는데, 목록에 없어 "error"로 뭉쳐져 원인이 로그에 안 보였다
    6: "bad_key",
    7: "bad_key",
    9: "bad_key",
    13: "busy",
    21: "no_permission",
    23: "rate_limited",
    29: "rate_limited",
    # 38 = 하루 호출 한도 소진. 공식 코드 표(docs.shipfinder.com/8401497m0)에는 없고 실제로 받은 응답으로 정했다.
    # 전에는 목록에 없어 "error"로 뭉쳐졌다.
    # 오늘은 다시 불러도 같은 답이라 retryable이 아니다
    38: "quota_exhausted",
}
_RETRYABLE = {"busy", "rate_limited", "timeout"}
# 마지막 성공 값으로 대신하는 실패. 빈도 초과(SDD 5.2), 시간 초과(평가셋 F02 "마지막 수신 위치로 판정"),
# 하루 한도 소진. 셋 다 "지금 못 받았을 뿐 배의 정보는 있다"는 뜻이다. 권한 없음·없는 배는 사실이라 캐시로 가리지 않는다
_CACHE_FALLBACK = {"rate_limited", "timeout", "quota_exhausted"}
# 캐시 TTL이 지난 값도 쓰는 실패. 시간 초과(①)와 한도 소진은 오늘 안에 새 값을 받을 길이 없다.
# 빈도 초과는 잠시 뒤 새 값을 받을 수 있어 SDD 5.2대로 TTL 안에서만 쓴다
_IGNORE_TTL = {"timeout", "quota_exhausted"}

# 한도 소진을 받은 한국 날짜. 같은 날에는 호출하지 않고 바로 quota_exhausted로 실패시켜 남은 일(수집 워커의
# 다음 배, 후보 상세 조회 5척 등)이 헛호출을 쌓지 않게 한다. 프로세스 메모리라 api와 worker는 각자 한 번씩은 38을 받는다.
# 날짜 경계는 한국 자정으로 잡았다. ShipFinder 서버가 다른 시간대 자정에 초기화하면 경계 뒤 첫 호출이 38을 다시 받고
# 그날 하루 다시 막힐 뿐이라 한도를 넘기지는 않는다
_KST = ZoneInfo("Asia/Seoul")
_quota_lock = threading.Lock()
_quota_out_on: date | None = None


def _today_kst() -> date:
    return datetime.now(_KST).date()


def quota_blocked() -> bool:
    """오늘(한국 날짜) 한도 소진을 이미 받았나. 라우터가 "내일 다시" 안내를 고르는 데도 쓴다 (routers/agent.py)."""
    return _quota_out_on is not None and _quota_out_on == _today_kst()


def _mark_quota_out() -> None:
    global _quota_out_on
    with _quota_lock:
        _quota_out_on = _today_kst()


def reset_quota_block() -> None:
    """한도 소진 표시를 지운다. 테스트가 서로 영향을 주지 않게 매번 부른다 (conftest.py)."""
    global _quota_out_on
    with _quota_lock:
        _quota_out_on = None


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

    # 마지막 호출이 캐시로 답한 시각. 실시간으로 받았으면 None (SDD 8절 "근거에 캐시 표시")
    last_cached_at: datetime | None

    def __init__(self, key: str | None = None, transport: httpx.BaseTransport | None = None):
        self._key = key or os.environ.get("SHIPFINDER_KEY", "")
        # REPLAY_MODE면 키 없이 evals/fixtures/replay/를 읽는다 (SDD 6.1, clients/replay.py).
        # 테스트가 transport를 직접 주면 그쪽이 먼저다
        if transport is None and replay_enabled():
            transport = shipfinder_transport()
            self._key = self._key or "replay"
        if not self._key:
            raise ShipFinderError("bad_key", "SHIPFINDER_KEY가 비어 있습니다")
        self._http = httpx.Client(base_url=BASE_URL, timeout=TIMEOUT_SEC, transport=transport)
        self.last_cached_at = None

    def _cached(self, key: str, fetch):
        """호출해 보고, 빈도 초과·시간 초과·한도 소진이면 마지막 성공 값을 돌려준다 (SDD 5.2).

        다른 실패(권한 없음, 없는 배 등)는 캐시로 가리지 않는다. 그 실패는 사실이기 때문이다.
        캐시로 대신했으면 last_cached_at이 채워지고, 라우터는 그 판정을 partial로 알린다 (routers/agent.py).
        """
        try:
            value = fetch()
        except ShipFinderError as e:
            if e.code not in _CACHE_FALLBACK:
                raise
            # 시간 초과는 TTL(rules.md api_cache_ttl_hours)이 지난 값도 쓴다 (①, 평가셋 F02: 03:05 캐시로 12:00 판정).
            # 오래된 위치는 signals의 position_stale이 "마지막 수신 위치"로 드러내므로 숨기는 것이 아니다
            # ("오래된 위치는 되묻지 않고 마지막 수신 위치로 판정"). 빈도 초과는 SDD 5.2대로 TTL 안에서만
            # 한도 소진도 같다: 오늘 안에 새 값을 받을 수 없다 (_IGNORE_TTL)
            entry = self.cache.entry(key, ignore_ttl=(e.code in _IGNORE_TTL))
            if entry is None:
                raise
            self.last_cached_at = entry.cached_at
            # 지난 값이 지금 값처럼 나간다. 판정이 이상할 때 추적할 수 있게 어느 호출이 캐시로 대체됐는지 남긴다.
            # key의 앞 두 칸(shipfinder:pos 등)만 쓴다. 뒤에는 검색어·MMSI가 붙는다
            log_failure(":".join(key.split(":")[:2]), f"{e.code} served_from_cache")
            return entry.value
        self.cache.set(key, value)
        self.last_cached_at = None
        return value

    def close(self) -> None:
        self._http.close()

    def _get(self, endpoint: str, params: dict) -> dict:
        """ShipFinder HTTP 호출 한 번을 Langfuse span으로 감싼다.

        전에는 성공한 호출이 어디에도 안 보여서 하루 한도를 누가 썼는지 알 수 없었다. httpx 로거는 키가 URL에 실려 새므로
        일부러 WARNING으로 막아 뒀다. 그래서 키·URL·검색어·응답 원본은 빼고 endpoint, 캐시 여부, 건수, 오류 코드,
        replay 여부만 남긴다. served_from_cache는 이 층에서는 항상 False다(캐시 대체는 _cached가 이 호출이 실패한 뒤에 한다).
        캐시 대체는 resolve_mmsi 등 부른 쪽 span과 log_failure("... served_from_cache")가 남긴다.
        """
        with tool_span(f"shipfinder.{endpoint}", {"endpoint": endpoint}) as span:
            span.metadata.update(endpoint=endpoint, served_from_cache=False, replay_mode=replay_enabled(),
                                 result_count=None)
            # 오늘 한도 소진을 이미 받아 실제로는 부르지 않은 경우를 구분한다 (불렀다가 38을 받은 것과 다르다)
            span.metadata["not_called_quota_blocked"] = quota_blocked()
            try:
                body = self._get_raw(endpoint, params)
            except ShipFinderError as e:
                span.error = e.code
                raise
            data = body.get("data")
            span.metadata["result_count"] = len(data) if isinstance(data, list) else (1 if data else 0)
            return body

    def _get_raw(self, endpoint: str, params: dict) -> dict:
        # 오늘 이미 한도 소진을 받았으면 부르지 않는다. 불러도 38만 돌아오고 호출 수만 쌓인다
        if quota_blocked():
            raise ShipFinderError("quota_exhausted", f"{endpoint} 오늘 호출 한도 소진 (호출하지 않음)", status=38)

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
            if code == "quota_exhausted":
                _mark_quota_out()
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
        return position_from_data(d)


def position_from_data(d: dict) -> VesselPosition:
    """VesselPositionSingle 응답의 data 칸을 VesselPosition으로 옮긴다.

    좌표(lat·lng)가 빠진 응답은 KeyError로 흘리지 않고 ShipFinderError("error")로 바꾼다.
    MCP 도구는 ShipFinderError만 {error}로 바꾸므로, 다른 예외는 도구 밖으로 새어 나갔다.

    클라이언트 안에서만 쓰던 변환을 밖으로 뺐다. 평가 실행기가 평가셋의 "캐시 위치"(F02)를
    실제 응답과 같은 변환으로 캐시에 넣으려고 쓴다 (evals/run_eval.py).
    """
    if d.get("lat") is None or d.get("lng") is None or d.get("mmsi") is None:
        raise ShipFinderError("error", "위치 응답에 mmsi·lat·lng가 없음")
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
