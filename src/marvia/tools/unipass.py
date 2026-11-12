"""UNI-PASS 화물통관진행정보 조회 (설계 7.2, done 2.3). 실제 API와 재생 데이터가 같은 모양을 돌려준다.

하지 않는 일: 판정, 번호 읽기·가림. 실제 응답은 저장소에 넣지 않는다(약관). 시험은 httpx.MockTransport로 돈다.
[주의] 요청 주소에 키(crkyCn)와 실제 번호가 들어간다. 주소·예외 글을 로그·오류 글·LLM에 넣지 않는다.
       httpx는 INFO로 요청 주소 전체를 찍는다. 그래서 이 모듈을 읽을 때 httpx 로거를 WARNING으로 올린다
       (v1 backend/app/observability/logging.py: 실제 B/L 호출에서 키와 번호가 로그에 남은 것을 찾았다).
[주의] 실제 응답으로 확인하지 않았다(키와 실제 호출은 직접 할 일). 응답 모양은 v1 코드와 가공 fixture다.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from xml.etree import ElementTree

import httpx

from marvia.config import Settings
from marvia.identify.models import CargoFacts, ToolError
from marvia.identify.parse import kind_of
from marvia.tools import unipass_replay
from marvia.tools.rules import load_rules

KST = timezone(timedelta(hours=9))  # UNI-PASS 처리일시는 한국 시각이다
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)
CFG = load_rules("unipass")
# [왜] 조회 서브그래프의 동시 실행 상한(loop.max_concurrency)은 그래프 한 층마다 걸린다. 프로세스 전체는
#      여기서 막는다
SLOTS = threading.BoundedSemaphore(CFG["max_concurrency"])


def _error(code: str) -> ToolError:
    """rules/unipass.yaml의 정한 글로만 오류를 만든다."""
    return ToolError(code=code, message=CFG["messages"][code], retryable=code in CFG["retryable"])


def _get(client: httpx.Client, params: dict, sleep: Callable[[float], None]) -> httpx.Response | ToolError:
    """한 번 부르고, 시간 초과·연결 오류·5xx면 retries번까지 다시 부른다. 4xx는 다시 부르지 않는다."""
    last = "unavailable"
    for attempt in range(CFG["retries"] + 1):
        if attempt:
            sleep(CFG["backoff_s"] * attempt)
        try:
            with SLOTS:
                response = client.get(CFG["url"], params=params)
        except httpx.TimeoutException:
            last = "timeout"
            continue
        except httpx.TransportError:  # [주의] 예외 글에 주소가 있다. 종류만 본다
            last = "unavailable"
            continue
        except httpx.HTTPError:
            # [왜] 잘못된 압축 본문(DecodingError) 같은 나머지 httpx 오류도 정한 모양으로 돌려준다.
            #      예외 객체의 요청 주소에는 키와 번호가 있어 밖으로 내보내지 않는다(raise 없이 버린다)
            return _error("bad_response")
        if response.status_code >= 500:
            last = "unavailable"
            continue
        if response.status_code >= 400:
            return _error("bad_response")
        return response
    return _error(last)


def _text(node: ElementTree.Element, tag: str) -> str | None:
    value = (node.findtext(tag) or "").strip()
    return value or None


def _kst(value: str | None) -> datetime | None:
    """20260929100000 꼴 처리일시를 한국 시각으로 읽는다. 못 읽으면 None."""
    for fmt in ("%Y%m%d%H%M%S", "%Y%m%d"):
        try:
            return datetime.strptime(value or "", fmt).replace(tzinfo=KST)
        except ValueError:
            continue
    return None


def parse_progress(text: str, number: str) -> CargoFacts | ToolError:
    """응답 XML을 화물 사실로 바꾼다. 없음(tCnt 0), 인자 오류(tCnt -1), 화물 여럿, 읽지 못함은 ToolError."""
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return _error("bad_response")
    count = (root.findtext("tCnt") or "").strip()
    if count == "-1":
        # [왜] HTTP 200에 안내 글(ntceInfo)로 오는 인자 오류다. "없음"으로 읽지 않는다
        return _error("bad_input")
    if count == "0":
        return _error("not_found")
    heads = root.findall("cargCsclPrgsInfoQryVo")
    if len(heads) > 1:
        return _error("ambiguous")  # [왜] 첫 줄을 고르면 남의 화물 단계를 말할 수 있다
    if not heads:
        return _error("bad_response")
    head = heads[0]
    # [왜] 상단 csclPrgsStts는 수입신고수리에서 멈춰 반출을 못 보인다(v1 실제 B/L). 가장 늦은 이력 줄이 지금
    #      단계다
    history = sorted(
        (row.findtext("prcsDttm") or "", name, _text(row, "shedNm") or "")
        for row in root.iter("cargCsclPrgsInfoDtlQryVo")
        if (name := _text(row, "cargTrcnRelaBsopTpcd"))
    )
    stage = history[-1][1] if history else _text(head, "csclPrgsStts")
    if stage is None:
        return _error("bad_response")
    cargo_no = _text(head, "cargMtNo")
    return CargoFacts(
        number=number,
        stage=stage,
        stage_at=_kst(history[-1][0]) if history else None,
        vessel_name=_text(head, "shipNm"),
        port=_text(head, "dsprNm"),
        mrn=cargo_no[:11] if cargo_no else None,
        # 배 추적이 쓰는 칸 (계획 8a). 칸 이름은 v1이 실제 응답으로 확인한 것이다(v1-final judge/customs.py)
        port_code=_text(head, "dsprCd"),
        entry_date=entry.date() if (entry := _kst(_text(head, "etprDt"))) else None,
        loading_port=_text(head, "ldprNm"),
        vessel_flag=_text(head, "shipNat"),
        voyage=_text(head, "vydf"),
        shed=(history[-1][2] or None) if history else None,
        source="unipass",
        fetched_at=datetime.now(UTC),
    )


def fetch_cargo(
    number: str,
    *,
    key: str,
    client: httpx.Client,
    year: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> CargoFacts | ToolError:
    """실제 API로 번호 하나를 조회한다. 화물관리번호는 cargMtNo, B/L은 하우스 → 마스터 순서로 본다."""
    if kind_of(number) == "cargo_no":
        attempts = [{"cargMtNo": number}]
    else:
        # [왜] B/L 조회에는 연도가 필요하고 기본은 올해다(설계 7.2). 소량 수입자는 보통 하우스 B/L을 받는다
        #      [추정]
        bl_year = str(year or datetime.now(KST).year)
        attempts = [{"hblNo": number, "blYy": bl_year}, {"mblNo": number, "blYy": bl_year}]
    result: CargoFacts | ToolError = _error("not_found")
    for params in attempts:
        response = _get(client, {"crkyCn": key, **params}, sleep)
        if isinstance(response, ToolError):
            return response
        result = parse_progress(response.text, number)
        if not (isinstance(result, ToolError) and result.code == "not_found"):
            return result
    return result


def facts_carry_containers() -> bool:
    """화물 사실에 컨테이너 번호가 실릴 수 있는가. 지금은 재생 모드만 그렇다 (계획 6a 정정)."""
    # shortcut: 실제 응답(parse_progress)은 컨테이너 칸을 읽지 않는다.
    #           연계가이드에서 API001의 cntrNo를 확인하면 바꾼다
    return Settings().unipass_mode != "live"


def lookup_cargo(number: str) -> CargoFacts | ToolError:
    """번호 하나를 조회한다. 기본은 재생 데이터, MARVIA_UNIPASS_MODE=live에 키가 있을 때만 실제 API.
    컨테이너 번호는 어느 모드에서도 조회하지 않고 정한 글(container_unknown)을 돌려준다."""
    if kind_of(number) == "container":
        # [주의] 이 서비스는 화물관리번호·마스터 B/L·하우스 B/L로만 찾는다(data.go.kr 15126268).
        #        컨테이너 번호를 B/L 칸에 넣어 보내지 않는다. 컨테이너는 이미 아는 화물에서 찾는다 (계획 6a)
        return _error("container_unknown")
    settings = Settings()
    if settings.unipass_mode != "live":
        return unipass_replay.lookup_cargo(number)
    key = settings.unipass_key.get_secret_value()
    if not key:
        return _error("no_key")
    # [왜] follow_redirects=False: 넘겨 주는 주소를 따라가면 키가 다른 호스트로 갈 수 있다
    with httpx.Client(timeout=CFG["timeout_s"], follow_redirects=False) as client:
        return fetch_cargo(number, key=key, client=client)
