"""배 확정: 같은 이름의 배가 여럿일 때 코드가 서류로 가르거나, 가르지 못하면 되묻는다 (계획 8a).

하지 않는 일: 바깥 조회(후보와 입항 신고는 부르는 쪽이 넣어 준다), LLM에게 고르게 하기, 되묻는 글.
v1 backend/app/services/judge/identify.py match_by_papers와 routers/agent.py _identify(태그 v1-final)의
코드 판단을 옮겼다. v1이 되묻기 답을 받은 뒤 LLM에게 고르게 하던 길은 옮기지 않았다(11-13 결정).
[왜] 배 이름·배 신호의 목적지·위치는 "어느 배가 내 화물을 실었나"의 근거가 아니다. v1에서 근거 없이
     고르게 했더니 남의 배를 확정했다(평가 문항 B01, B12). 틀린 배를 확정하는 것보다 되묻는 쪽이 낫다.
[주의] 아직 그래프의 어느 노드도 이 함수를 부르지 않는다. 연결은 다음 계획이다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel

from marvia.identify.models import CargoFacts
from marvia.tools.vessel import KST, SailingPlan, as_utc

Reason = Literal[
    "no_candidate",  # 후보가 없다
    "single_candidate",  # 후보가 한 척이고 서류와 어긋나지 않는다
    "mrn_call_sign",  # MRN으로 찾은 입항 신고의 호출부호와 같은 배가 한 척
    "papers_match",  # 세관 입항일·적재항과 해수부 입항 신고가 맞는 배가 한 척
    "mrn_call_sign_differs",
    "flag_differs",
    "same_call_sign_many_mmsi",
    "candidate_without_call_sign",
    "no_papers",  # 맞춰 볼 세관 값(입항일, 적재항)이 없다
    "schedule_lookup_failed",  # 입항 신고를 받지 못한 후보가 있다
    "papers_match_none",
    "papers_match_many",
]


class Candidate(BaseModel):
    """배 후보 한 척(ShipFinder 검색 결과에서)."""

    mmsi: int
    call_sign: str | None = None
    flag: str | None = None  # 국적 두 글자 코드


class Match(BaseModel):
    """배 확정 결과. confirmed=이 배다, ask=가르지 못했으니 되묻는다, none=후보가 없다."""

    status: Literal["confirmed", "ask", "none"]
    mmsi: int | None = None
    call_sign: str | None = None
    reason: Reason


def _sign(call_sign: str | None) -> str:
    """호출부호 비교용: 공백을 빼고 대문자."""
    return re.sub(r"\s+", "", call_sign or "").upper()


def _flags_differ(a: str | None, b: str | None) -> bool:
    """두 국적이 확실히 다른가. 하나라도 모르거나 두 글자 코드가 아니면 다르다고 하지 않는다."""
    x, y = (a or "").strip().upper(), (b or "").strip().upper()
    return len(x) == 2 and len(y) == 2 and x != y


def _port_key(name: str | None) -> str:
    return re.sub(r"[^0-9A-Z]", "", (name or "").upper())


def _same_port(loading: str | None, previous: str | None) -> bool:
    """세관 적재항과 해수부 직전 기항지가 같은 항구인가. 한쪽이 다른 쪽의 앞부분이면 같다(NINGBO PT)."""
    # [왜] 가운데에 들어 있기만 해도 같다고 하면 다른 항구를 같은 항구로 볼 수 있다. 앞부분만 본다
    a, b = _port_key(loading), _port_key(previous)
    return bool(a and b) and (a.startswith(b) or b.startswith(a))


def _ask(reason: Reason) -> Match:
    return Match(status="ask", reason=reason)


def _confirmed(ship: Candidate, reason: Reason) -> Match:
    return Match(status="confirmed", mmsi=ship.mmsi, call_sign=ship.call_sign, reason=reason)


def match_vessel(
    facts: CargoFacts,
    candidates: list[Candidate],
    plans: Mapping[str, list[SailingPlan] | None],
    mrn_call_sign: str | None = None,
) -> Match:
    """후보 가운데 이 화물을 실은 배를 정한다.

    plans: 후보의 호출부호(공백 없이 대문자) → 그 배의 입항 신고. 받지 못했으면 None이거나 열쇠가 없다.
    mrn_call_sign: 화물의 MRN과 같은 입항 신고에서 얻은 호출부호(있으면 가장 센 근거다).
    """
    if not candidates:
        return Match(status="none", reason="no_candidate")
    wanted = _sign(mrn_call_sign)
    if len(candidates) == 1:
        only = candidates[0]
        if wanted and _sign(only.call_sign) and _sign(only.call_sign) != wanted:
            return _ask("mrn_call_sign_differs")
        return (
            _ask("flag_differs")
            if _flags_differ(facts.vessel_flag, only.flag)
            else _confirmed(only, "single_candidate")
        )
    if wanted:
        same = [c for c in candidates if _sign(c.call_sign) == wanted]
        if len(same) == 1:
            return _confirmed(same[0], "mrn_call_sign")
        if len(same) > 1:
            return _ask("same_call_sign_many_mmsi")
    # 서류 대조: 세관 입항(예정)일 = 해수부 입항 신고의 날짜(한국 날짜), 세관 적재항 = 그 신고의 직전 기항지
    if facts.entry_date is None or not facts.loading_port:
        return _ask("no_papers")
    rows = [c for c in candidates if not _flags_differ(facts.vessel_flag, c.flag)]
    if any(not _sign(c.call_sign) for c in rows):
        return _ask("candidate_without_call_sign")  # 확인하지 못한 후보가 있으면 "한 척만 맞다"고 할 수 없다
    signs = sorted({_sign(c.call_sign) for c in rows})
    if any(plans.get(sign) is None for sign in signs):
        return _ask("schedule_lookup_failed")
    matched = [
        sign
        for sign in signs
        if any(
            p.planned_arrival is not None
            and as_utc(p.planned_arrival).astimezone(KST).date() == facts.entry_date
            and _same_port(facts.loading_port, p.previous_port)
            and _sign(p.call_sign) == sign  # 해수부가 준 신고가 정말 그 호출부호의 것인지도 본다
            for p in plans.get(sign) or []
        )
    ]
    if len(matched) != 1:
        return _ask("papers_match_none" if not matched else "papers_match_many")
    ships = [c for c in rows if _sign(c.call_sign) == matched[0]]
    if len({c.mmsi for c in ships}) != 1:
        return _ask("same_call_sign_many_mmsi")
    if wanted and wanted != matched[0]:
        return _ask("mrn_call_sign_differs")
    return _confirmed(ships[0], "papers_match")
