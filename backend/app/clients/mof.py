"""해양수산부 공공데이터 클라이언트 (작업 B5).

관제정보(CntlVssl2/Info)를 부른다. 전국 해상교통관제센터가 남긴 관제 실적이고,
선박 1건 안에 입항·접안·이안·출항 같은 이벤트가 여러 개 들어 있다.

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
TIMEOUT_SEC = 15.0
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
        """기간 안의 관제 실적을 가져온다. call_sign을 주면 그 배만 조회한다."""
        params = {
            "serviceKey": self._key,
            "prtAgCd": prt_ag_cd,
            "sde": start.strftime("%Y%m%d"),
            "ede": end.strftime("%Y%m%d"),
            "numOfRows": min(rows, MAX_ROWS),
            "pageNo": 1,
        }
        if call_sign:
            params["clsgn"] = call_sign

        def call() -> httpx.Response:
            resp = self._http.get(BASE_URL, params=params)
            resp.raise_for_status()
            return resp

        try:
            # 타임아웃·5xx는 2회까지 다시 부른다 (A9, SDD 8절)
            root = ElementTree.fromstring(with_retry(call, name="mof:CntlVssl2").text)
        except httpx.TimeoutException as e:
            raise MofError("timeout", "관제정보 응답 시간 초과") from e
        except httpx.HTTPError as e:
            raise MofError("error", f"관제정보 호출 실패: {type(e).__name__}") from e
        except ElementTree.ParseError as e:
            raise MofError("error", "관제정보 응답이 XML이 아닙니다") from e

        result_code = root.findtext(".//resultCode")
        if result_code and result_code not in ("00", "0"):
            message = root.findtext(".//resultMsg") or f"resultCode {result_code}"
            code = "bad_key" if result_code in ("30", "31") else "error"
            raise MofError(code, message, result_code=result_code)

        return [self._to_call(item) for item in root.iter("item")]

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
