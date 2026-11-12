"""해수부 공공데이터 조회: 선박운항정보(입항 신고)와 관제정보(입항 실적) (계획 8a, 설계 7.2 port_schedule).

실제 API와 재생 데이터가 같은 파싱 길을 지난다. 기본은 재생이고 MARVIA_MOF_MODE=live에 키가 있을 때만
실제로 부른다.
하지 않는 일: 판정, 배 고르기. 항만 값(청코드, 조회 기간)은 부르는 쪽이 항만 표에서 받아 넘긴다.
[주의] 요청 주소에 키(serviceKey)가 들어간다. 주소·예외 글·바깥 응답 글을 로그·오류 글·LLM에 넣지 않는다.
[주의] 응답의 배 이름·시설 이름·MRN은 바깥에서 온 값이다. MRN은 화물 번호처럼 다룬다(모델·로그에 넣지 않는다).
[주의] 실제 응답으로 확인하지 않았다(키와 실제 호출은 직접 할 일). 응답 모양은 v1 코드와 가공 fixture다.
       부산 밖 청코드의 응답이 같은 모양인지도 확인하지 못했다.
[주의] 아직 그래프의 어느 노드도 이 모듈을 부르지 않는다. 연결은 다음 계획이다.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree

import httpx
from pydantic import BaseModel, ValidationError

from marvia.config import Settings
from marvia.identify.models import ToolError
from marvia.tools.ports import Port
from marvia.tools.rules import load_rules
from marvia.tools.vessel import PortSchedule, SailingPlan
from marvia.trace import _safe_host  # pyright: ignore[reportPrivateUsage]

for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)  # [왜] httpx는 INFO로 요청 주소(키 포함)를 찍는다
CFG = load_rules("mof")
# src/marvia/tools/mof.py에서 세 단계 올라가면 저장소 루트다 → 루트의 fixtures/mof/
FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "mof"
EMPTY = (
    "<response><header><resultCode>00</resultCode></header>"
    "<body><items/><totalCount>0</totalCount></body></response>"
)


class Arrival(BaseModel):
    """관제정보의 배 한 척: 실제 입항 시각과 접안 시설."""

    call_sign: str | None = None
    ship_name: str = ""
    actual_arrival: datetime | None = None
    facility: str | None = None


def _error(code: str) -> ToolError:
    """rules/mof.yaml의 정한 글로만 오류를 만든다."""
    return ToolError(code=code, message=CFG["messages"][code], retryable=code in CFG["retryable"])


def _text(node: ElementTree.Element, tag: str) -> str | None:
    value = (node.findtext(tag) or "").strip()
    return value or None


class _BadShape(Exception):
    """응답 값의 모양이 달라 읽을 수 없다. 부르는 쪽이 bad_response로 바꾼다. 글에 바깥 값을 싣지 않는다."""


def _when(value: str | None) -> datetime | None:
    """2026-09-22T22:30:00+09:00 꼴을 시각으로. 못 읽으면 None. 시간대가 없으면 _BadShape를 낸다."""
    try:
        moment = datetime.fromisoformat(value) if value else None
    except ValueError:
        return None
    if moment is not None and moment.tzinfo is None:
        # [왜] 시간대가 없는 시각은 어느 시간대인지 모른다. 짐작해 채우면 입항 시각이 9시간 어긋날 수 있다.
        #      시간대가 있는 값과 섞이면 견주다 TypeError가 난다
        raise _BadShape
    return moment


# 응답 값을 읽다가 나는 예외. 그 조회를 bad_response로 돌려준다
SHAPE_ERRORS = (_BadShape, ValidationError, TypeError, ValueError, OverflowError)


def _sign(call_sign: str | None) -> str:
    return re.sub(r"\s+", "", call_sign or "").upper()


def _get(
    client: httpx.Client, url: str, params: dict, sleep: Callable[[float], None]
) -> ElementTree.Element | ToolError:
    """한 번 부르고, 시간 초과·연결 오류·5xx면 retries번까지 다시 부른다. 응답 머리의 결과 코드도 본다."""
    last = "unavailable"
    for attempt in range(CFG["retries"] + 1):
        if attempt:
            sleep(CFG["backoff_s"] * attempt)
        try:
            response = client.get(url, params=params)
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
            root = ElementTree.fromstring(response.text)
        except ElementTree.ParseError:
            return _error("bad_response")
        gate = CFG["gateway"]
        if root.tag == gate["root"]:
            # [왜] 관문의 오류 본문에는 resultCode가 없다. 정상 0건으로 읽으면 키가 틀려도
            #      "입항 신고 없음"이 된다.
            #      안의 글(returnAuthMsg 등)은 바깥 글이라 옮기지 않는다. [주의] 실제 본문으로 확인하기 전이다
            reason = (root.findtext(f".//{gate['code_tag']}") or "").strip()
            if reason in gate["key_codes"]:
                return _error("bad_key")
            return _error("quota_exhausted" if reason in gate["quota_codes"] else "api_error")
        code = (root.findtext(".//resultCode") or "").strip()
        if root.tag != "response" or not code:
            return _error("bad_response")  # [왜] 기대한 모양이 아니면 0건이 아니라 못 읽은 것이다
        if code not in CFG["ok_codes"]:
            # [왜] resultMsg는 바깥에서 온 글이다. 옮기지 않고 정한 글로 바꾼다
            return _error("bad_key" if code in CFG["key_error_codes"] else "api_error")
        if root.find(".//items") is None:
            return _error("bad_response")  # 정상 코드인데 목록 칸이 없다
        return root
    return _error(last)


def _pages(
    path: str,
    office: str,
    start: date,
    end: date,
    *,
    key: str,
    client: httpx.Client,
    base_url: str,
    call_sign: str | None,
    max_pages: int,
    sleep: Callable[[float], None],
) -> list[ElementTree.Element] | ToolError:
    """기간 안의 item을 쪽을 넘기며 모은다. 쪽 상한까지 꽉 차 있으면 too_many다."""
    items: list[ElementTree.Element] = []
    for page in range(1, max_pages + 1):
        params = {
            "serviceKey": key,
            "prtAgCd": office,
            "sde": start.strftime("%Y%m%d"),
            "ede": end.strftime("%Y%m%d"),
            "numOfRows": CFG["max_rows"],
            "pageNo": page,
        }
        if call_sign:
            params["clsgn"] = _sign(call_sign)
        root = _get(client, base_url.rstrip("/") + path, params, sleep)
        if isinstance(root, ToolError):
            return root
        found = list(root.iter("item"))
        items += found
        if len(found) < CFG["max_rows"]:
            return items  # 마지막 쪽이다
    # [왜] 상한까지 꽉 찼으면 뒤에 못 본 배가 있다. 그 배가 목록에 없다고 "신고 없음"으로 답하지 않는다
    return _error("too_many")


def _plan(item: ElementTree.Element) -> SailingPlan:
    arrival = next((d for d in item.iter("detail") if _text(d, "etryndNm") == CFG["arrival_report"]), None)
    return SailingPlan(
        call_sign=_text(item, "clsgn"),
        ship_name=_text(item, "vsslNm") or "",
        previous_port=_text(item, "prvsDpmprtPrtNm"),
        planned_arrival=_when(_text(arrival, "etryptDt")) if arrival is not None else None,
        revision=_text(arrival, "reqstSeNm") if arrival is not None else None,
        facility=_text(arrival, "laidupFcltyNm") if arrival is not None else None,
        mrn=_text(arrival, "mrNum") if arrival is not None else None,  # 입항 MRN. 출항 MRN은 번호가 다르다
    )


def _arrival(item: ElementTree.Element) -> Arrival:
    events = [
        (_when(_text(d, "cntrlOpertDt")), _text(d, "fcltyNm"))
        for d in item.iter("detail")
        if _text(d, "cntrlNm") in CFG["arrival_events"]
    ]
    times = [at for at, _ in events if at is not None]
    return Arrival(
        call_sign=_text(item, "clsgn"),
        ship_name=_text(item, "vsslNm") or "",
        actual_arrival=min(times) if times else None,
        facility=next((name for _, name in events if name), None),
    )


def sailing_plans(
    office: str,
    start: date,
    end: date,
    *,
    key: str,
    client: httpx.Client,
    base_url: str,
    call_sign: str | None = None,
    max_pages: int = 1,
    sleep: Callable[[float], None] = time.sleep,
) -> list[SailingPlan] | ToolError:
    """기간 안의 입항 신고. office는 항만 표의 청코드다. call_sign을 주면 그 배만, 없으면 기간 전체다."""
    items = _pages(
        CFG["sailing_path"],
        office,
        start,
        end,
        key=key,
        client=client,
        base_url=base_url,
        call_sign=call_sign,
        max_pages=max_pages,
        sleep=sleep,
    )
    if isinstance(items, ToolError):
        return items
    try:
        return [_plan(item) for item in items]
    except SHAPE_ERRORS:
        return _error("bad_response")  # [주의] 예외 글에는 바깥 값이 있다. 옮기지 않는다


def control_arrivals(
    office: str,
    start: date,
    end: date,
    *,
    key: str,
    client: httpx.Client,
    base_url: str,
    call_sign: str | None = None,
    max_pages: int = 1,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Arrival] | ToolError:
    """기간 안의 입항 실적. 관제정보는 이미 일어난 일만 준다(미래 날짜는 0건)."""
    items = _pages(
        CFG["control_path"],
        office,
        start,
        end,
        key=key,
        client=client,
        base_url=base_url,
        call_sign=call_sign,
        max_pages=max_pages,
        sleep=sleep,
    )
    if isinstance(items, ToolError):
        return items
    try:
        return [_arrival(item) for item in items]
    except SHAPE_ERRORS:
        return _error("bad_response")


def plan_by_mrn(plans: list[SailingPlan], mrn: str) -> SailingPlan | None:
    """입항 MRN이 같은 신고. 화물관리번호 앞 11자리(MRN)에서 배의 호출부호로 잇는 고리다."""
    target = mrn.strip().upper()
    return next((p for p in plans if target and (p.mrn or "").upper() == target), None)


def _replay(request: httpx.Request) -> httpx.Response:
    """재생: fixtures/mof/<API>/<청코드>/<호출부호 또는 _ALL>.xml. 파일이 없으면 빈 결과다."""
    api = "VsslEtrynd5" if CFG["sailing_path"] in request.url.path else "CntlVssl2"
    params = request.url.params
    office = re.sub(
        r"[^0-9A-Za-z]", "", params.get("prtAgCd", "")
    )  # [왜] 폴더 이름에 경로 글자를 넣지 않는다
    name = re.sub(r"[^0-9A-Z]", "", params.get("clsgn", "").upper()) or "_ALL"
    path = FIXTURES / api / office / f"{name}.xml"
    # 가공 fixture는 한 쪽 분량이다. 둘째 쪽부터는 빈 결과다
    first = params.get("pageNo", "1") == "1"
    return httpx.Response(200, text=path.read_text(encoding="utf-8") if first and path.exists() else EMPTY)


def _session() -> tuple[httpx.Client, str, str] | ToolError:
    """설정대로 클라이언트, 주소, 키를 만든다. 재생이면 바깥 연결 없이 fixture를 읽는 클라이언트다."""
    settings = Settings()
    if settings.mof_mode != "live":
        return httpx.Client(transport=httpx.MockTransport(_replay)), CFG["base_url"], "replay"
    key = settings.mof_key.get_secret_value()
    if not key:
        return _error("no_key")
    base_url = settings.mof_base_url or CFG["base_url"]
    # [왜] https가 아닌 주소(이 컴퓨터의 http는 예외)로는 키와 릴레이 토큰이 그대로 읽힌다. 열기 전에 멈춘다.
    #      주소 검사는 Langfuse 주소에 쓰는 것과 같다 (marvia.trace._safe_host)
    if not _safe_host(base_url):
        return _error("unsafe_address")
    # [왜] 릴레이 토큰은 릴레이 주소를 정했을 때만 싣는다. 주소가 비면 해수부로 바로 가므로 보낼 곳이 아니다
    token = settings.mof_relay_token.get_secret_value() if settings.mof_base_url else ""
    # [왜] follow_redirects=False: 넘겨 주는 주소를 따라가면 키가 다른 호스트로 갈 수 있다
    client = httpx.Client(
        timeout=httpx.Timeout(CFG["timeout_s"], connect=CFG["connect_timeout_s"]),
        follow_redirects=False,
        headers={"X-Relay-Token": token} if token else {},
    )
    return client, base_url, key


def port_schedule(row: Port, call_sign: str, *, today: date) -> PortSchedule | ToolError:
    """배 한 척의 그 항만 입항 일정: 지난 며칠의 실적과 앞으로 며칠의 예정. 기간과 청코드는 항만 표의 값."""
    if not row.mof_office or row.schedule_lookback_days is None or row.schedule_lookahead_days is None:
        return _error("port_unknown")  # [왜] 다른 항만의 청코드나 기간으로 대신 부르지 않는다
    session = _session()
    if isinstance(session, ToolError):
        return session
    client, base_url, key = session
    with client:
        back = today - timedelta(days=row.schedule_lookback_days)
        ahead = today + timedelta(days=row.schedule_lookahead_days)
        done = control_arrivals(
            row.mof_office, back, today, key=key, client=client, base_url=base_url, call_sign=call_sign
        )
        if isinstance(done, ToolError):
            return done
        plans = sailing_plans(
            row.mof_office, today, ahead, key=key, client=client, base_url=base_url, call_sign=call_sign
        )
        if isinstance(plans, ToolError):
            return plans
    # [왜] 해수부가 조회 조건을 다르게 적용해도 남의 배 기록을 쓰지 않게 호출부호를 다시 본다
    sign = _sign(call_sign)
    arrived = next((a for a in done if _sign(a.call_sign) == sign and a.actual_arrival), None)
    plan = next((p for p in plans if _sign(p.call_sign) == sign), None)
    # [왜] 최종 신고의 시각은 실제 입항 시각이다. 예정으로 쓰지 않고 따로 싣는다: 관제 실적이 아직 없는
    #      막 입항한 배의 입항 시각이 된다 (믿을 ETA의 순서는 rules/verdict.yaml eta_priority)
    final = bool(plan) and plan.revision == CFG["final_revision"]
    return PortSchedule(
        planned_arrival=plan.planned_arrival if plan and not final else None,
        final_arrival=plan.planned_arrival if plan and final else None,
        actual_arrival=arrived.actual_arrival if arrived else None,
        # 접안 시설은 실적이 있으면 실적 쪽을 쓴다. 예정은 바뀔 수 있다
        facility=(arrived.facility if arrived else None) or (plan.facility if plan else None),
        fetched_at=datetime.now(UTC),
    )


def plans_near(row: Port, day: date) -> list[SailingPlan] | ToolError:
    """세관 입항(예정)일 앞뒤의 입항 신고 전체. MRN으로 배를 찾을 때 쓴다(plan_by_mrn). 범위는 항만 표에서."""
    if not row.mof_office or row.mrn_search_days is None:
        return _error("port_unknown")
    session = _session()
    if isinstance(session, ToolError):
        return session
    client, base_url, key = session
    span = timedelta(days=row.mrn_search_days)
    with client:
        return sailing_plans(
            row.mof_office,
            day - span,
            day + span,
            key=key,
            client=client,
            base_url=base_url,
            max_pages=CFG["max_pages"],
        )
