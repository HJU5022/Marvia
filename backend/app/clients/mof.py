"""해양수산부 공공데이터 클라이언트 (작업 B5).

두 API를 부른다.
- 관제정보(CntlVssl2/Info): 전국 해상교통관제센터가 남긴 관제 실적이고,
  선박 1건 안에 입항·접안·이안·출항 같은 이벤트가 여러 개 들어 있다.
- 선박운항정보(VsslEtrynd5/Info5): 선사·대리점이 낸 입출항 신고. 입항 예정 시각과
  적하목록 관리번호(MRN)가 여기서 나온다. 아래 "선박운항정보" 절 참고.

확인한 것 (2026-09-23):
- 필수 파라미터는 serviceKey, prtAgCd, sde, ede. 하나라도 빠지면 INVALID_REQUEST_PARAMETER_ERROR
- 부산 항만청 코드는 020 (인천 030, 경인 050)
- 미래 날짜로 부르면 0건이다. 이 API는 실적만 주고 입항 예정은 주지 않는다.
  입항 예정은 해수부 선박운항정보(별도 활용신청)에서 가져와야 한다
- MMSI가 없다. 호출부호(clsgn)와 선명으로 ShipFinder 쪽과 맞춰야 한다

응답은 XML이다. 값은 원본 그대로 돌려주고 판정은 하지 않는다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime
from xml.etree import ElementTree

import httpx

from backend.app.clients.retry import with_retry

BASE_URL = "https://apis.data.go.kr/1192000/CntlVssl2/Info"
# 선박운항정보. 주소 끝이 Info5다 (Swagger 확인 2026-09-23, /Info로 부르면 NO_OPENAPI 오류)
REPORT_URL = "https://apis.data.go.kr/1192000/VsslEtrynd5/Info5"
TIMEOUT_SEC = 15.0
MAX_PAGES = 20  # 선박운항정보 페이지 넘김 상한. 부산 5일치가 12페이지였다 (2026-09-23 실측)
BUSAN_PRT_AG_CD = "020"
MAX_ROWS = 50  # API 상한

# 관제구분(cntrlNm) 값. 2026-09-22 부산 하루치에서 확인한 6종
ARRIVAL_KINDS = ("입항", "접안")
DEPARTURE_KINDS = ("출항", "이안")


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


# ---- 선박운항정보 ----
# 확인한 것 (2026-09-23, 부산 실측):
# - 미래 날짜로 부르면 입항 신고가 나온다 (09-24~30 조회 264척). 이게 "해수부 입항 예정"이다
# - 신고 단계(reqstSeNm)는 최초/변경/최종. API는 이력을 주지 않고 현재 단계 값 하나만 준다
# - 입항 뒤 '최종' 신고가 되면 etryptDt가 실제 입항 시각과 거의 같아진다
#   (09-20~22 입항 238척 중 최종 175척, 그중 85%가 관제 입항 시각과 분 단위까지 일치).
#   그래서 입항 예정으로 믿을 수 있는 것은 최초·변경 단계 값뿐이다
# - mrNum은 적하목록 관리번호(MRN). 입항은 끝이 I, 출항은 E로 번호가 다르다.
#   UNI-PASS 화물관리번호(cargMtNo) 앞 11자리와 같아서 B/L에서 배를 특정하는 열쇠가 된다
# - IMO·MMSI는 없다. 호출부호(clsgn)가 ShipFinder와 잇는 값이다
REPORT_STAGE_FINAL = "최종"


@dataclass(frozen=True)
class ArrivalReport:
    """입항 신고 1건 (선박운항정보의 '입항' detail 하나)."""

    call_sign: str | None
    ship_name: str
    nationality: str | None
    ship_kind: str | None       # vsslKndNm. 워커가 풀컨테이너선만 추적 대상으로 고를 때 쓴다
    stage: str | None           # reqstSeNm: 최초/변경/최종
    arrival_at: datetime | None  # etryptDt. 최종이면 실제 입항 시각에 가깝다
    facility: str | None        # laidupFcltyNm, 신고한 선석 또는 박지
    mrn: str | None             # mrNum, 입항 적하목록 관리번호

    @property
    def planned_arrival(self) -> datetime | None:
        """입항 예정 시각. 최종 신고 값은 실제 시각이라 예정으로 쓰지 않는다 (위 확인 내용)."""
        return None if self.stage == REPORT_STAGE_FINAL else self.arrival_at


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
        if not self._key:
            raise MofError("bad_key", "DATA_GO_KR_KEY가 비어 있습니다")
        self._http = httpx.Client(timeout=TIMEOUT_SEC, transport=transport)

    def close(self) -> None:
        self._http.close()

    def control_records(
        self,
        start: date,
        end: date,
        call_sign: str | None = None,
        prt_ag_cd: str = BUSAN_PRT_AG_CD,
        rows: int = MAX_ROWS,
    ) -> list[VesselCall]:
        """기간 안의 관제 실적을 가져온다. call_sign을 주면 그 배만 조회한다.

        페이지를 끝까지 넘긴다. 호출부호로 부르면 보통 한 페이지지만, 워커는 부산 전체를
        받아서 여러 페이지가 된다 (3일치 332척 = 7페이지, 2026-09-23 실측).
        """
        calls: list[VesselCall] = []
        for page in range(1, MAX_PAGES + 1):
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
            root = self._get(BASE_URL, params, label="관제정보")
            items = list(root.iter("item"))
            calls.extend(self._to_call(item) for item in items)
            total = _int(root.findtext(".//totalCount")) or 0
            if not items or page * params["numOfRows"] >= total:
                break
        return calls

    def arrival_reports(
        self,
        start: date,
        end: date,
        call_sign: str | None = None,
        prt_ag_cd: str = BUSAN_PRT_AG_CD,
    ) -> list[ArrivalReport]:
        """기간 안의 입항 신고를 선박운항정보에서 가져온다. 페이지를 끝까지 넘긴다.

        call_sign이 없으면 기간 전체를 훑는다. MRN으로 배를 찾을 때는 호출부호를 아직
        모르니 이렇게 불러야 한다 (부산 5일치 12페이지, 2026-09-23 실측).
        """
        reports: list[ArrivalReport] = []
        for page in range(1, MAX_PAGES + 1):
            params = {
                "serviceKey": self._key,
                "prtAgCd": prt_ag_cd,
                "sde": start.strftime("%Y%m%d"),
                "ede": end.strftime("%Y%m%d"),
                "numOfRows": MAX_ROWS,
                "pageNo": page,
            }
            if call_sign:
                params["clsgn"] = call_sign
            root = self._get(REPORT_URL, params, label="선박운항정보")
            items = list(root.iter("item"))
            reports.extend(r for item in items if (r := self._to_report(item)) is not None)
            # totalCount를 다 읽었거나 빈 페이지면 멈춘다
            total = _int(root.findtext(".//totalCount")) or 0
            if not items or page * MAX_ROWS >= total:
                break
        return reports

    def find_arrival_by_mrn(self, mrn: str, start: date, end: date) -> ArrivalReport | None:
        """입항 MRN이 같은 신고를 찾는다. B/L → UNI-PASS MRN → 배(호출부호)로 잇는 단계.

        이름으로 찾지 않는 이유: UNI-PASS는 영문 선명, 해수부는 한글 선명이라 맞지 않는다
        (HEUNG-A JANICE / 흥아 제니스, 2026-09-23 실측).
        """
        target = mrn.strip().upper()
        for report in self.arrival_reports(start, end):
            if report.mrn and report.mrn.upper() == target:
                return report
        return None

    def _get(self, url: str, params: dict, label: str):
        """GET 한 번 부르고 XML 루트를 돌려준다. 두 API의 오류 처리가 같아서 한 곳에 둔다."""

        def call() -> httpx.Response:
            resp = self._http.get(url, params=params)
            resp.raise_for_status()
            return resp

        try:
            # 타임아웃·5xx는 2회까지 다시 부른다 (A9, SDD 8절)
            root = ElementTree.fromstring(with_retry(call, name=f"mof:{url.rsplit('/', 2)[-2]}").text)
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

    @staticmethod
    def _to_report(item) -> ArrivalReport | None:
        """신고 1건에서 '입항' detail만 꺼낸다. 출항만 있는 신고는 None."""
        for detail in item.iter("detail"):
            if _text(detail, "etryndNm") == "입항":
                return ArrivalReport(
                    call_sign=_text(item, "clsgn"),
                    ship_name=_text(item, "vsslNm") or "",
                    nationality=_text(item, "vsslNltyNm"),
                    ship_kind=_text(item, "vsslKndNm"),
                    stage=_text(detail, "reqstSeNm"),
                    arrival_at=_dt(_text(detail, "etryptDt")),
                    facility=_text(detail, "laidupFcltyNm"),
                    mrn=_text(detail, "mrNum"),
                )
        return None

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
