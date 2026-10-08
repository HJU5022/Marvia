"""해양수산부 공공데이터 클라이언트 (작업 B5).

두 가지를 부른다. 키는 공공데이터포털 하나를 같이 쓴다.

1. 관제정보 CntlVssl2/Info: 관제센터가 남긴 실적. 이미 일어난 일만 준다
2. 선박운항정보 VsslEtrynd5/Info5: 입출항 신고 기반이라 앞으로 들어올 배도 준다

선박 1건 안에 입항·출항 같은 신고가 detail로 여러 개 들어 있다.

확인한 것 (2026-09-23):
- 필수 파라미터는 serviceKey, prtAgCd, sde, ede. 하나라도 빠지면 INVALID_REQUEST_PARAMETER_ERROR
- 부산 항만청 코드는 020 (인천 030, 경인 050)
- 미래 날짜로 부르면 0건이다. 이 API는 실적만 주고 입항 예정은 주지 않는다.
  입항 예정은 해수부 선박운항정보(별도 활용신청)에서 가져와야 한다
- MMSI가 없다. 호출부호(clsgn)와 선명으로 ShipFinder 쪽과 맞춰야 한다

선박운항정보에서 확인한 것 (2026-09-23, 부산 실측):
- 신고 단계(reqstSeNm)는 최초/변경/최종. API는 이력을 주지 않고 현재 단계 값 하나만 준다
- 입항 뒤 '최종' 신고가 되면 etryptDt가 실제 입항 시각과 거의 같아진다
  (9월 20~22일 입항 238척 중 최종 175척, 그중 85%가 관제 입항 시각과 분 단위까지 일치).
  그래서 입항 "예정"으로 믿을 수 있는 것은 최초·변경 단계 값뿐이다 (SailingPlan.expected_arrival)
- 입항 detail의 mrNum은 적하목록 관리번호(MRN). 입항은 끝이 I, 출항은 E로 번호가 다르다.
  UNI-PASS 화물관리번호(cargMtNo) 앞 11자리와 같아서 B/L에서 배를 특정하는 열쇠가 된다
  (실제 B/L 1건으로 호출부호까지 연결 확인). 선명은 UNI-PASS 영문·해수부 한글이라 맞지 않는다

응답은 XML이다. 값은 원본 그대로 돌려주고 판정은 하지 않는다.
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime
from xml.etree import ElementTree

import httpx

from backend.app.clients.replay import mof_transport, replay_enabled
from backend.app.clients.retry import with_retry
from backend.app.observability.logging import log_failure

DEFAULT_BASE_URL = "https://apis.data.go.kr"
CONTROL_PATH = "/1192000/CntlVssl2/Info"
SAILING_PATH = "/1192000/VsslEtrynd5/Info5"
TIMEOUT_SEC = float(os.environ.get("MOF_TIMEOUT_SEC", 15))  # 환경변수로 조정 가능
# 연결 단계만 따로 짧게 둔다. 연결이 안 되는 곳은 15초를 기다려도 안 된다
CONNECT_TIMEOUT_SEC = 3.0
# 연결 실패 뒤 이 시간 동안은 네트워크를 부르지 않고 바로 실패시킨다 (아래 회로 차단기)
# 60초였으나 첫 질문 실패 뒤 1분 동안 모든 질문이 실패해 15초로 줄였다
CIRCUIT_OPEN_SEC = 15.0
BUSAN_PRT_AG_CD = "020"
MAX_ROWS = 50  # API 상한
# 기간 전체를 훑을 때 페이지 상한. 부산 5일치 선박운항정보가 12페이지였다 (2026-09-23 실측).
# 워커(부산 전체 수집)와 MRN 찾기가 쓴다
MAX_PAGES = 20
REVISION_FINAL = "최종"

# 관제구분(cntrlNm) 값. 2026-09-22 부산 하루치에서 확인한 6종
ARRIVAL_KINDS = ("입항", "접안")
DEPARTURE_KINDS = ("출항", "이안")


# 회로 차단기. Railway(싱가포르)에서 apis.data.go.kr는 해외 연결을 끊어
# ConnectTimeout이 난다(한국에서는 0.1초). 요청마다 기다리면 한 질문이 수십 초 걸리므로
# 연결이 두 번 연달아 실패하면 CIRCUIT_OPEN_SEC 동안은 네트워크 없이 같은 오류(timeout)로 바로 실패시킨다.
# 프로세스 안에서만 유효한 단순 변수다. 읽기 타임아웃·5xx에는 적용하지 않는다
_connect_failed_at: float | None = None


def reset_circuit() -> None:
    """차단기를 푼다. 테스트가 쓴다."""
    global _connect_failed_at
    _connect_failed_at = None


def _circuit_open() -> bool:
    return _connect_failed_at is not None and time.monotonic() - _connect_failed_at < CIRCUIT_OPEN_SEC


class _Unreachable(Exception):
    """연결 자체가 안 됐다. 재시도 대상이 아니라서 retry.is_retryable이 False로 본다."""


def _log_page_cap(stage: str, max_pages: int) -> None:
    """페이지 상한까지 다 받았는데 마지막 페이지가 꽉 차 있었다 = 뒤에 더 있는데 못 봤다.
    그 배가 목록에 없으면 "기록 없음"이 아니라 "못 본 것"일 수 있다 (이름 훑기 5페이지에서 잘림).
    한 페이지만 보는 호출(호출부호 조회)은 원래 한 페이지면 되니 남기지 않는다."""
    if max_pages > 1:
        log_failure(stage, f"page_cap_hit {max_pages}")


class MofError(Exception):
    """해수부 API 호출 실패. MCP 도구가 ToolError로 바꿔 돌려준다."""

    def __init__(self, code: str, message: str, result_code: str | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.result_code = result_code
        self.retryable = code in ("timeout", "busy")

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


@dataclass(frozen=True)
class ControlEvent:
    """관제 이벤트 1건. 입항·접안·이안·출항·투묘·양묘 중 하나."""

    kind: str
    at: datetime | None
    facility: str | None


@dataclass(frozen=True)
class SailingPlan:
    """선박운항정보 1건. 신고 기준이라 앞으로 들어올 배의 입항 예정을 담고 있다."""

    call_sign: str | None
    ship_name: str
    nationality: str | None
    ship_kind: str | None
    purpose: str | None  # 입항 목적 (양하·적하·급유 등)
    previous_port: str | None
    next_port: str | None
    planned_arrival: datetime | None  # detail etryndNm=입항의 etryptDt
    planned_departure: datetime | None  # detail etryndNm=출항의 tkoffDt
    facility: str | None  # 접안 예정 시설
    revision: str | None  # reqstSeNm. 최초/변경/최종
    mrn: str | None = None  # 입항 detail의 mrNum, 적하목록 관리번호 (모듈 설명 참고)

    @property
    def expected_arrival(self) -> datetime | None:
        """아직 믿을 수 있는 입항 예정. 최종 신고의 시각은 실제 입항 시각이라 예정으로 쓰지 않는다 (모듈 설명)."""
        return None if self.revision == REVISION_FINAL else self.planned_arrival


@dataclass(frozen=True)
class VesselCall:
    """선박 1척의 입출항 1회분. 관제 이벤트 여러 개를 묶고 있다."""

    call_sign: str | None
    ship_name: str
    nationality: str | None
    gross_tonnage: int | None
    ship_kind: str | None
    reported_arrival: datetime | None  # aprtfEtryptDt, 신고된 입항일시
    events: list[ControlEvent] = field(default_factory=list)

    @property
    def actual_arrival(self) -> datetime | None:
        """실제 입항 시각. 입항·접안 이벤트 중 가장 이른 것."""
        times = [e.at for e in self.events if e.kind in ARRIVAL_KINDS and e.at]
        return min(times) if times else None

    @property
    def facility(self) -> str | None:
        """접안 시설. 접안·입항 이벤트에 붙은 시설명 중 첫 번째."""
        for e in self.events:
            if e.kind in ARRIVAL_KINDS and e.facility:
                return e.facility
        return None


def _text(node, tag: str) -> str | None:
    found = node.findtext(tag)
    return found.strip() or None if found else None


def _dt(value: str | None) -> datetime | None:
    """2026-09-22T22:30:00+09:00 형태를 datetime으로."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _int(value: str | None) -> int | None:
    return int(value) if value and value.isdigit() else None


class MofClient:
    def __init__(self, key: str | None = None, transport: httpx.BaseTransport | None = None):
        self._key = key or os.environ.get("DATA_GO_KR_KEY", "")
        # REPLAY_MODE면 키 없이 evals/fixtures/replay/를 읽는다 (SDD 6.1, clients/replay.py).
        # 테스트가 transport를 직접 주면 그쪽이 먼저다
        if transport is None and replay_enabled():
            transport = mof_transport()
            self._key = self._key or "replay"
        if not self._key:
            raise MofError("bad_key", "DATA_GO_KR_KEY가 비어 있습니다")
        # 주소와 릴레이 토큰은 만들 때 읽는다 (테스트가 환경변수를 바꿀 수 있게).
        # MOF_BASE_URL: 해외 서버에서는 한국(서울) 릴레이 주소를 넣는다. relay/README.md 참고
        base = (os.environ.get("MOF_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")  # 빈 값(.env의 "MOF_BASE_URL=")도 기본 주소로
        self._control_url = base + CONTROL_PATH
        self._sailing_url = base + SAILING_PATH
        headers = {}
        relay_token = os.environ.get("MOF_RELAY_TOKEN")
        if relay_token:
            headers["X-Relay-Token"] = relay_token
        self._http = httpx.Client(
            timeout=httpx.Timeout(TIMEOUT_SEC, connect=CONNECT_TIMEOUT_SEC),
            transport=transport,
            headers=headers,
        )

    def close(self) -> None:
        self._http.close()

    def _fetch(self, url: str, label: str, start: date, end: date, call_sign: str | None, prt_ag_cd: str, rows: int, page: int = 1):
        """두 API가 파라미터와 오류 형식이 같아 호출부를 공유한다."""
        params = {
            "serviceKey": self._key,
            "prtAgCd": prt_ag_cd,
            "sde": start.strftime("%Y%m%d"),
            "ede": end.strftime("%Y%m%d"),
            "numOfRows": min(rows, MAX_ROWS),
            "pageNo": page,
        }
        if call_sign:
            params["clsgn"] = call_sign

        if _circuit_open():
            raise MofError("timeout", f"{label} 응답 시간 초과")  # 네트워크를 부르지 않는다

        def call() -> httpx.Response:
            global _connect_failed_at
            try:
                resp = self._http.get(url, params=params)
            except (httpx.ConnectTimeout, httpx.ConnectError):
                # 잠깐 끊긴 경우를 살리려고 연결 실패는 한 번만 바로 다시 부른다.
                # 그래도 안 되면 막힌 것으로 보고 차단기를 연다. 연결 시간 3초라 최악 6초다
                try:
                    resp = self._http.get(url, params=params)
                except (httpx.ConnectTimeout, httpx.ConnectError) as e:
                    _connect_failed_at = time.monotonic()  # 차단기를 연다
                    raise _Unreachable() from e
            resp.raise_for_status()
            return resp

        try:
            # 타임아웃·5xx는 2회까지 다시 부른다 (A9, SDD 8절)
            root = ElementTree.fromstring(with_retry(call, name=f"mof:{label}").text)
        except _Unreachable as e:
            raise MofError("timeout", f"{label} 응답 시간 초과") from e
        except httpx.TimeoutException as e:
            raise MofError("timeout", f"{label} 응답 시간 초과") from e
        except httpx.HTTPError as e:
            raise MofError("error", f"{label} 호출 실패: {type(e).__name__}") from e
        except ElementTree.ParseError as e:
            raise MofError("error", f"{label} 응답이 XML이 아닙니다") from e

        result_code = root.findtext(".//resultCode")
        if result_code and result_code not in ("00", "0"):
            message = root.findtext(".//resultMsg") or f"resultCode {result_code}"
            code = "bad_key" if result_code in ("30", "31") else "error"
            raise MofError(code, message, result_code=result_code)
        return root

    def control_records(
        self,
        start: date,
        end: date,
        call_sign: str | None = None,
        prt_ag_cd: str = BUSAN_PRT_AG_CD,
        rows: int = MAX_ROWS,
        max_pages: int = 1,
    ) -> list[VesselCall]:
        """기간 안의 관제 실적을 가져온다. call_sign을 주면 그 배만 조회한다.

        부산은 하루 100건이 넘고 한 번에 50건까지만 온다. 호출부호 없이 선명으로 찾을 때는
        max_pages를 올려 뒤 페이지까지 봐야 그 배가 목록에 들어온다.
        """
        records = []
        for page in range(1, max_pages + 1):
            root = self._fetch(self._control_url, "CntlVssl2", start, end, call_sign, prt_ag_cd, rows, page)
            items = [self._to_call(item) for item in root.iter("item")]
            records.extend(items)
            if len(items) < min(rows, MAX_ROWS):
                break  # 마지막 페이지다
        else:
            _log_page_cap("mof_control", max_pages)
        return records

    def sailing_plans(
        self,
        start: date,
        end: date,
        call_sign: str | None = None,
        prt_ag_cd: str = BUSAN_PRT_AG_CD,
        rows: int = MAX_ROWS,
        max_pages: int = 1,
    ) -> list[SailingPlan]:
        """입출항 신고 기준 운항정보. 미래 날짜를 주면 입항 예정이 나온다.

        관제정보와 달리 아직 안 들어온 배도 준다. 신고가 바뀌면 reqstSeNm이 변경으로 온다.
        """
        plans = []
        for page in range(1, max_pages + 1):
            root = self._fetch(self._sailing_url, "VsslEtrynd5", start, end, call_sign, prt_ag_cd, rows, page)
            items = [self._to_plan(item) for item in root.iter("item")]
            plans.extend(items)
            if len(items) < min(rows, MAX_ROWS):
                break
        else:
            _log_page_cap("mof_sailing", max_pages)
        return plans

    def sailing_plans_all(self, start: date, end: date, prt_ag_cd: str = BUSAN_PRT_AG_CD,
                          max_pages: int = MAX_PAGES, workers: int = 6) -> list[SailingPlan]:
        """기간 전체 입출항 신고를 빨리 받는다 (자연어 선박 검색, docs/specs/chat-search.md).

        sailing_plans는 쪽을 하나씩 차례로 받아 부산 7일치(약 6쪽)에 5초쯤 걸렸다(4.8초).
        첫 쪽의 totalCount로 쪽 수를 알고 나머지 쪽을 동시에 받는다. 결과 순서는 쪽 순서 그대로다.
        쪽 수가 max_pages를 넘으면 앞쪽만 받고 로그를 남긴다 (sailing_plans와 같은 상한).
        """
        first = self._fetch(self._sailing_url, "VsslEtrynd5", start, end, None, prt_ag_cd, MAX_ROWS, 1)
        plans = [self._to_plan(item) for item in first.iter("item")]
        total = _int(first.findtext(".//totalCount")) or len(plans)
        pages = -(-total // MAX_ROWS)  # 올림
        if pages > max_pages:
            _log_page_cap("mof_sailing", max_pages)
            pages = max_pages
        if pages <= 1:
            return plans

        def page(n: int) -> list[SailingPlan]:
            root = self._fetch(self._sailing_url, "VsslEtrynd5", start, end, None, prt_ag_cd, MAX_ROWS, n)
            return [self._to_plan(item) for item in root.iter("item")]

        # httpx.Client는 여러 스레드에서 같이 써도 된다. 실패한 쪽이 있으면 MofError가 그대로 올라간다
        with ThreadPoolExecutor(max_workers=min(workers, pages - 1)) as pool:
            for rest in pool.map(page, range(2, pages + 1)):
                plans.extend(rest)
        return plans

    def find_plan_by_mrn(self, mrn: str, start: date, end: date) -> SailingPlan | None:
        """입항 MRN이 같은 신고를 찾는다. B/L → UNI-PASS MRN → 배(호출부호)로 잇는 단계.

        호출부호를 아직 모르니 기간 전체를 훑는다. 출항 MRN(끝이 E)으로는 찾지 않는다.
        """
        target = mrn.strip().upper()
        for plan in self.sailing_plans(start, end, max_pages=MAX_PAGES):
            if plan.mrn and plan.mrn.upper() == target:
                return plan
        return None

    @staticmethod
    def _to_plan(item) -> SailingPlan:
        arrival = departure = facility = revision = mrn = None
        for detail in item.iter("detail"):
            kind = _text(detail, "etryndNm")
            if kind == "입항":
                arrival = _dt(_text(detail, "etryptDt"))
                facility = _text(detail, "laidupFcltyNm")
                revision = _text(detail, "reqstSeNm")
                mrn = _text(detail, "mrNum")
            elif kind == "출항":
                departure = _dt(_text(detail, "tkoffDt"))
                facility = facility or _text(detail, "laidupFcltyNm")

        return SailingPlan(
            call_sign=_text(item, "clsgn"),
            ship_name=_text(item, "vsslNm") or "",
            nationality=_text(item, "vsslNltyNm"),
            ship_kind=_text(item, "vsslKndNm"),
            purpose=_text(item, "etryptPurpsNm"),
            previous_port=_text(item, "prvsDpmprtPrtNm"),
            next_port=_text(item, "nxlnptPrtNm"),
            planned_arrival=arrival,
            planned_departure=departure,
            facility=facility,
            revision=revision,
            mrn=mrn,
        )

    @staticmethod
    def _to_call(item) -> VesselCall:
        events = [
            ControlEvent(
                kind=_text(detail, "cntrlNm") or "",
                at=_dt(_text(detail, "cntrlOpertDt")),
                facility=_text(detail, "fcltyNm"),
            )
            for detail in item.iter("detail")
        ]
        return VesselCall(
            call_sign=_text(item, "clsgn"),
            ship_name=_text(item, "vsslNm") or "",
            nationality=_text(item, "vsslNltyNm"),
            gross_tonnage=_int(_text(item, "vsslGrtg")),
            ship_kind=_text(item, "vsslKndNm"),
            reported_arrival=_dt(_text(item, "aprtfEtryptDt")),
            events=events,
        )
