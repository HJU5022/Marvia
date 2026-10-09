"""선박 식별 중 MRN으로 호출부호를 찾는 단계 (SDD 5.5, 추가).

B/L → UNI-PASS 화물관리번호 앞 11자리(MRN) → 해수부 입항 신고의 같은 MRN → 그 배의 호출부호.
배 이름으로 찾으면 같은 이름의 배가 여럿 나오거나(동명 선박), 표기가 달라 0척이 나온다.
MRN은 화물 한 건에 하나라서 이름과 상관없이 그 배의 신고를 바로 가리킨다.
해수부 배 이름은 국적선이면 한글이라 ShipFinder 영문 이름과 비교할 수 없고, 호출부호로 이어야 한다.

찾지 못하면 None을 돌려준다. 입항 신고 전이거나 해수부가 실패한 경우다.
그때 라우터는 지금까지처럼 배 이름 검색으로 간다 (MRN은 더 정확한 길이지 유일한 길이 아니다).

라우터에 두지 않고 여기에 둔 이유: 라우터는 외부 API를 직접 부르지 않는다 (routers/agent.py 모듈 설명).
"""
from __future__ import annotations

import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from backend.app.clients.mof import MofClient, MofError
from backend.app.observability.langfuse import tool_span
from backend.app.observability.logging import log_failure
from backend.app.schemas.customs import CustomsRecord
from backend.app.services.judge.evidence import KST  # 근거 카드·판정 입력과 같은 한국 시각

# UNI-PASS 입항(예정)일 앞뒤 며칠의 입항 신고를 훑을지. 실제 B/L 1건이 ±1일 안에서 찾아졌다.
# 넓힐수록 훑는 페이지가 늘어 느려진다 (±1일 1건 실측 7.0초)
SEARCH_DAYS = 1


def call_sign_from_mrn(customs: CustomsRecord, mof: MofClient | None = None) -> str | None:
    """세관 기록의 MRN으로 해수부 입항 신고를 찾아 호출부호를 돌려준다. 못 찾으면 None."""
    if not customs.mrn or not customs.entry_date:
        return None  # 찾을 근거가 없으면 해수부를 부르지 않는다

    day = customs.entry_date.date()
    try:
        # 해수부 구간을 Langfuse에 남긴다. input은 조회 날짜 범위뿐이다. MRN·B/L은 올리지 않는다 (SDD 3.5)
        with tool_span("mof:find_plan_by_mrn", {"days": 2 * SEARCH_DAYS + 1}) as span:
            plan = (mof or MofClient()).find_plan_by_mrn(customs.mrn, day - timedelta(days=SEARCH_DAYS), day + timedelta(days=SEARCH_DAYS))
            span.metadata["found"] = plan is not None
    except MofError as e:
        # 해수부 실패는 식별을 막지 않는다. 라우터가 이름 검색으로 간다. 다만 이름 검색은 느리고 동명선에 약해서
        # 왜 MRN 길을 못 탔는지는 남긴다
        log_failure("identify_mrn", e.code)
        return None
    if plan is None:
        # 입항 신고 전이면 정상적으로 없다 (도착 1주일 안쪽에 신고). 해수부 오류와 구분해서 남긴다
        log_failure("identify_mrn", "not_found")
        return None
    return plan.call_sign



PAPERS_WORKERS = 6  # 후보별 해수부 조회를 동시에 몇 개까지. 차례로 부르면 후보 수만큼 느려진다


def _kst_day(moment: datetime) -> date:
    """한국 날짜. 세관 입항일과 해수부 입항 신고를 같은 기준으로 비교한다. 세관 YYYYMMDD는 시간대가 없어 한국 날짜로 본다."""
    if moment.tzinfo is None:
        return moment.date()
    return moment.astimezone(KST).date()


def _sign(call_sign: str) -> str:
    """호출부호 비교·조회용 모양. 공백을 모두 빼고 대문자 (중복 제거·해수부 조회·MRN 비교에 같은 기준을 쓴다)."""
    return re.sub(r"\s+", "", call_sign).upper()


def _port_key(name: str | None) -> str:
    """항구 이름 비교용. 대문자 영숫자만 (예: "Qingdao" → QINGDAO, "NINGBO PT" → NINGBOPT). 한글 이름은 빈 글자가 된다."""
    return re.sub(r"[^0-9A-Z]", "", (name or "").upper())


def _same_port(loading: str | None, previous: str | None) -> bool:
    """세관 적재항 이름과 해수부 직전 기항지가 같은 항구인가. 한쪽이 다른 쪽 앞부분이면 같다고 본다 (NINGBO ↔ NINGBO PT).
    앞부분만 보는 이유: 가운데에 들어 있기만 해도 같다고 하면 다른 항구를 같은 항구로 볼 수 있다."""
    a, b = _port_key(loading), _port_key(previous)
    return bool(a and b) and (a.startswith(b) or b.startswith(a))


def match_by_papers(customs: CustomsRecord, candidates: list[dict], *, mrn_call_sign: str | None = None,
                    same_call_sign: Callable[[str, str], bool], same_nationality: Callable[[str, str], bool],
                    mof: MofClient | None = None) -> tuple[int, str, str] | None:
    """같은 이름의 배가 여럿일 때, 서류끼리 맞는 배가 정확히 1척이면 그 배를 돌려준다.

    확정 근거는 두 가지이고 둘 다 맞아야 한다:
      ① 세관(UNI-PASS) 입항(예정)일 = 그 배의 해수부 부산 입항 신고 날짜 (한국 날짜 기준)
      ② 세관 적재항 = 그 배의 해수부 입항 신고 직전 기항지
    두 서류는 같은 입항을 가리키는 신고라 배를 잇는 근거가 된다.
    배 이름·AIS 목적지·위치는 쓰지 않는다. "어느 배가 내 화물을 실었나"의 근거가 아니기 때문이다
    (routers/agent._identify. 근거 없이 LLM이 고르게 했더니 B01·B12·데모 TESTBL04에서 남의 배를 확정했다).

    빼는 근거 (확정 근거가 아니라, 확실히 아닌 배를 빼는 데만 쓴다):
      - 세관 국적이 있고 후보 국적이 다르면 뺀다. 둘 중 하나라도 없으면 빼지 않는다 (단일 후보 B14와 같은 기준)
    확정하지 않는 경우 (틀린 배를 확정하는 것보다 되묻는 쪽이 낫다, PRD 6.2):
      - 맞는 배가 0척이거나 2척 이상
      - 확인하지 못한 후보가 있다 (호출부호 없음, 해수부 실패). "1척만 맞다"고 말할 수 없다
      - MRN 서류의 호출부호를 아는데 맞은 배의 호출부호가 다르다 (단일 후보 B07과 같은 기준)
    한계: 적재항에서 실은 뒤 다른 항구를 들렀다 오면 직전 기항지가 달라 맞지 않는다. 그때는 되묻는다.

    candidates: ShipFinder 후보 줄 (mmsi, call_sign, flag 칸). same_call_sign·same_nationality는 라우터의 비교 함수다
    (routers/agent._same_call_sign, _same_nationality). 같은 기준을 두 곳에 쓰지 않으려고 받아서 쓴다.
    돌려주는 값: (mmsi, call_sign, 사용자에게 보일 근거 한 줄). 확정하지 않으면 None.
    """
    if not customs.entry_date or not customs.loading_port_name:
        return None  # 비교할 세관 값이 없다
    rows = [r for r in candidates
            if not (customs.ship_nat and r.get("flag") and not same_nationality(customs.ship_nat, r["flag"]))]
    if any(not r.get("call_sign") for r in rows):
        log_failure("identify_papers", "candidate_without_call_sign")
        return None
    # 호출부호 한 개당 해수부를 한 번만 부른다. 같은 호출부호에 MMSI가 둘 이상이면 어느 MMSI인지 가를 근거가 없어
    # 그 호출부호가 맞아도 확정하지 않는다
    by_sign: dict[str, list[dict]] = {}
    for r in rows:
        by_sign.setdefault(_sign(r["call_sign"]), []).append(r)
    if not by_sign:
        return None
    day = _kst_day(customs.entry_date)
    start, end = day - timedelta(days=SEARCH_DAYS), day + timedelta(days=SEARCH_DAYS)
    try:
        client = mof or MofClient()  # 키가 없으면 여기서 MofError가 난다. 되묻기로 끝내야 해서 try 안에서 만든다
        # 후보별 조회를 동시에 도는 구간 전체를 span 하나로 남긴다. 풀 스레드는 문맥이 없어 그 안에서는 못 연다.
        # 호출부호는 올리지 않고 개수만 적는다
        with tool_span("mof:sailing_plans", {"candidates": len(by_sign)}):
            with ThreadPoolExecutor(max_workers=min(PAPERS_WORKERS, len(by_sign))) as pool:
                plans = dict(zip(by_sign, pool.map(lambda sign: client.sailing_plans(start, end, call_sign=sign), by_sign)))
    except MofError as e:
        log_failure("identify_papers", e.code)
        return None
    matched = [
        (sign, group) for sign, group in by_sign.items()
        # 해수부가 준 신고가 정말 그 호출부호의 것인지도 본다. 조회 조건을 해수부가 다르게 적용해도 남의 신고를 쓰지 않게
        if any(p.planned_arrival and _kst_day(p.planned_arrival) == day
               and _same_port(customs.loading_port_name, p.previous_port)
               and p.call_sign and same_call_sign(_sign(p.call_sign), sign)
               for p in plans[sign])
    ]
    if len(matched) != 1:
        log_failure("identify_papers", f"matched_{min(len(matched), 2)}")  # 0척인지 여럿인지 남겨야 놓친 이유를 안다
        return None
    sign, group = matched[0]
    if len({r["mmsi"] for r in group}) != 1:
        log_failure("identify_papers", "same_call_sign_many_mmsi")
        return None
    mmsi, call_sign = group[0]["mmsi"], group[0]["call_sign"]
    if mrn_call_sign and not same_call_sign(_sign(mrn_call_sign), sign):
        log_failure("identify_papers", "mrn_call_sign_differs")
        return None
    reason = f"세관 입항일({day.isoformat()})·적재항({customs.loading_port_name})과 해수부 입항 신고가 일치"
    return mmsi, call_sign, reason
