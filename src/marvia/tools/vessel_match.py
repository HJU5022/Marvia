"""배 확정: 같은 이름의 배가 여럿일 때 코드가 서류로 가르거나, 가르지 못하면 되묻는다 (계획 8a).

하지 않는 일: 바깥 조회(후보와 입항 신고는 부르는 쪽이 넣어 준다), LLM에게 고르게 하기, 되묻는 글.
v1 backend/app/services/judge/identify.py match_by_papers와 routers/agent.py _identify(태그 v1-final)의
코드 판단을 옮겼다. v1이 되묻기 답을 받은 뒤 LLM에게 고르게 하던 길은 옮기지 않았다(11-13 결정).
[왜] 배 이름·배 신호의 목적지·위치는 "어느 배가 내 화물을 실었나"의 근거가 아니다. v1에서 근거 없이
     고르게 했더니 남의 배를 확정했다(평가 문항 B01, B12). 틀린 배를 확정하는 것보다 되묻는 쪽이 낫다.
[주의] 그래프에서는 배 식별 단계(graph/vessel.py)만 부른다. MARVIA_VESSEL=on일 때만 돈다 (계획 8b).
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
    "mrn_lookup_failed",  # MRN으로 입항 신고를 받지 못했다(실패, 쪽 상한, 모양 오류)
    "mrn_report_missing",  # MRN이 없거나 그 MRN의 입항 신고를 찾지 못했다
]

# MRN으로 입항 신고를 찾은 결과: none(찾을 단서가 없다), failed(받지 못했다), not_found(받았지만 그 MRN의
#      줄이 없다),
# found_unsigned(찾았는데 호출부호가 없다), found_signed(찾았고 호출부호가 있다)
MrnLookup = Literal["none", "failed", "not_found", "found_unsigned", "found_signed"]


class Candidate(BaseModel):
    """배 후보 한 척(ShipFinder 검색 결과에서)."""

    mmsi: int
    call_sign: str | None = None
    flag: str | None = None  # 국적 두 글자 코드


class Match(BaseModel):
    """배 확정 결과. confirmed=코드가 이 배라고 정했다, ask=가르지 못했으니 되묻는다, none=후보가 없다,
    user_choice=사용자가 고른 배(자동 확정과 구분한다. 근거와 상한은 basis, reason, cap에 있다)."""

    status: Literal["confirmed", "ask", "none", "user_choice"]
    mmsi: int | None = None
    call_sign: str | None = None
    reason: Reason
    # 확정이어도 확신을 "부분"까지만 허락하면 "partial"이다: 호출부호를 코드로 맞추지 못했거나(서류만) 같은
    #      호출부호의
    # 배가 여럿이라 가르지 못했을 때. judge(cap=...)가 받는다
    cap: Literal["partial"] | None = None
    # 확정할 때 실제로 맞춰 본 칸의 이름: call_sign(MRN 호출부호와 같음), entry_date, loading_port(서류 대조).
    # 호출부호를 맞추지 못한 확정(서류 대조뿐)은 확신을 부분 이상으로 올리지 않는다(11-13 판정)
    basis: list[str] = []


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


def _confirmed(ship: Candidate, reason: Reason, basis: list[str]) -> Match:
    # [왜] 호출부호를 코드로 맞춘 확정만 상한이 없다. 서류(입항일, 적재항)만으로 맞춘 확정은 확신이 부분을
    #      넘지 못한다
    cap = None if "call_sign" in basis else "partial"
    return Match(
        status="confirmed", mmsi=ship.mmsi, call_sign=ship.call_sign, reason=reason, basis=basis, cap=cap
    )


PAPERS = ["entry_date", "loading_port"]


def match_vessel(
    facts: CargoFacts,
    candidates: list[Candidate],
    plans: Mapping[str, list[SailingPlan] | None],
    mrn_call_sign: str | None = None,
    mrn_lookup: MrnLookup | None = None,
) -> Match:
    """후보 가운데 이 화물을 실은 배를 정한다. 자동 확정은 두 길뿐이다.

    (가) MRN으로 얻은 호출부호(mrn_call_sign)와 후보의 호출부호가 글자까지 같고 그 후보가 한 척이다.
    (나) MRN 조회가 성공했고 그 신고에 호출부호가 없을 때(mrn_lookup == "found_unsigned")에 한해,
         후보의 입항 신고에서 입항일과 적재항이 화물의 것과 둘 다 맞는 후보가 한 척이다.
    그 밖은 후보가 한 척이어도 되묻는다. 이름이 같거나 닮은 것은 근거가 아니다.

    plans: 후보의 호출부호(공백 없이 대문자) → 그 배의 입항 신고. 받지 못했으면 None이거나 열쇠가 없다.
    mrn_lookup: MRN으로 입항 신고를 찾은 결과. 안 주면 호출부호가 있을 때 found_signed, 없을 때 none이다.
    """
    if not candidates:
        return Match(status="none", reason="no_candidate")
    wanted = _sign(mrn_call_sign)
    lookup = mrn_lookup or ("found_signed" if wanted else "none")
    sole = len(candidates) == 1
    if wanted:
        same = [c for c in candidates if _sign(c.call_sign) == wanted]
        if len(same) > 1:
            return _ask("same_call_sign_many_mmsi")  # 호출부호가 같은 배가 둘 이상이면 고르는 카드다
        if len(same) == 1:
            if sole and _flags_differ(facts.vessel_flag, same[0].flag):
                return _ask("flag_differs")
            return _confirmed(same[0], "mrn_call_sign", ["call_sign"])
        # MRN 호출부호를 가진 후보가 없다. 서류가 맞아도 다른 배일 수 있어 서류로 가르지 않는다
        if any(not _sign(c.call_sign) for c in candidates):
            return _ask("candidate_without_call_sign")
        return _ask("mrn_call_sign_differs")
    if sole and _flags_differ(facts.vessel_flag, candidates[0].flag):
        return _ask("flag_differs")
    if lookup != "found_unsigned":
        # [왜] 서류로 확정하는 길은 MRN 조회가 성공했고 그 신고에 호출부호가 없을 때만이다
        return _ask("mrn_lookup_failed" if lookup == "failed" else "mrn_report_missing")
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
    return _confirmed(ships[0], "papers_match", list(PAPERS))


def check_candidate(
    facts: CargoFacts,
    candidate: Candidate,
    candidates: list[Candidate],
    plans: Mapping[str, list[SailingPlan] | None],
    mrn_call_sign: str | None = None,
    mrn_lookup: MrnLookup | None = None,
) -> Match:
    """사용자가 고른 후보 하나를 같은 검사에 건다(그 후보 하나만 있다고 보고 맞춘다).

    같은 호출부호를 가진 다른 배가 후보에 더 있으면 호출부호로는 이 배를 가르지 못했다: 확정은 하되
    호출부호를 맞춘 칸을 빼고 확신 상한(부분)을 건다. 그 결과가 되묻기(ask)면 어긋난 까닭을 이유로 달고
    확정하되 상한(부분)을 건다. 돌려주는 status는 늘 user_choice다(자동 확정 confirmed와 구분한다).
    """
    alone = match_vessel(facts, [candidate], plans, mrn_call_sign, mrn_lookup)
    shared = _sign(candidate.call_sign) and any(
        c.mmsi != candidate.mmsi and _sign(c.call_sign) == _sign(candidate.call_sign) for c in candidates
    )
    if alone.status == "confirmed" and shared:
        kept = [name for name in alone.basis if name != "call_sign"]
        return alone.model_copy(
            update={
                "status": "user_choice",
                "reason": "same_call_sign_many_mmsi",
                "basis": kept,
                "cap": "partial",
            }
        )
    if alone.status == "ask":
        # [왜] 사용자의 선택은 받는다. 다만 호출부호를 코드로 맞추지 못했으니 어긋난 까닭을 이유로 달고
        #      확신을 부분까지만 둔다 (11-15 판정, R-126). 사용자가 골랐다는 것만으로 "확실"이 되지 않는다
        return Match(
            status="user_choice",
            mmsi=candidate.mmsi,
            call_sign=candidate.call_sign,
            reason=alone.reason,
            basis=[],
            cap="partial",
        )
    return alone.model_copy(update={"status": "user_choice"})
