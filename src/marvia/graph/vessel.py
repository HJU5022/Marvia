"""배 식별 단계: 식별한 화물마다 실은 배를 코드가 찾아 확정하거나 되묻는다 (계획 8b, 설계 4.1 ②, 6.3).

길: 화물의 MRN → 해수부 입항 신고 → 호출부호 → ShipFinder 후보(호출부호, 없으면 세관이 준 배 이름)
→ (MRN 호출부호가 없거나 맞지 않으면 후보마다 해수부 입항 신고) → tools/vessel_match.match_vessel.
자동 확정은 두 길뿐이다: (가) MRN에서 얻은 호출부호와 후보의 호출부호가 글자까지 같다,
(나) MRN 호출부호가 없을 때 그 후보의 입항 신고에서 입항일과 적재항이 둘 다 맞는다.
한 척이어도, 이름이 같아도 그 밖에는 되묻는다. 배에서 내린 단계의 화물은 배를 찾지 않는다.
하지 않는 일: LLM에게 고르게 하기, 배 이름·목적지 글·위치로 고르기, 후보의 국적 조회(후보마다 한 번
더 불러야 해서 두지 않았다. 국적은 모르는 값으로 넘긴다), 판정 계산(tools/judge.py).
[주의] 스위치 MARVIA_VESSEL=on일 때만 그래프에 들어간다. 꺼져 있으면 이 파일의 어떤 함수도 돌지 않는다.
[주의] 여기서 얻은 배 이름·호출부호·배 번호는 모델에 주지 않는다. 화면의 화물 카드와 선택 카드로만 간다.
"""

from __future__ import annotations

import re

from marvia.identify.models import CargoFacts, ToolError
from marvia.tools import mof, shipfinder
from marvia.tools.ports import port
from marvia.tools.rules import load_rules
from marvia.tools.signals import watches_ship
from marvia.tools.vessel import SailingPlan
from marvia.tools.vessel_match import Candidate, MrnLookup, match_vessel


def _sign(call_sign: str | None) -> str:
    return re.sub(r"\s+", "", call_sign or "").upper()


def _spend(budget: list[int], cost: int) -> bool:
    """남은 요청 수에서 cost만큼 쓴다. 모자라면 쓰지 않고 거짓을 돌려준다."""
    if budget[0] < cost:
        return False
    budget[0] -= cost
    return True


def find_vessel(facts: CargoFacts, *, near: dict | None = None) -> dict:
    """화물 한 건의 배를 찾는다.

    status: confirmed(이 배다), ask(되묻는다), none(후보 없음), unknown(찾지 않았거나 실패).

    near: 같은 차례에 받은 해수부 입항 신고 목록(항만 코드, 입항일 → 목록). 같은 날의 목록은 한 번만 받는다.
    """
    cfg = load_rules("vessel")
    if not watches_ship(facts.stage):
        return {"status": "unknown", "reason": "landed"}  # [왜] 내린 화물은 배를 조회하지 않는다
    near = {} if near is None else near
    budget = [cfg["max_find_calls"]]
    row = port(facts.port_code) if facts.port_code else None
    mrn_sign = None
    lookup: MrnLookup = "none"  # MRN으로 입항 신고를 찾은 결과(vessel_match.MrnLookup)
    if row and facts.mrn and facts.entry_date:
        key = (facts.port_code, facts.entry_date)
        if key not in near:
            if not _spend(budget, cfg["max_mrn_pages"]):
                return {"status": "unknown", "reason": "call_limit"}
            near[key] = mof.plans_near(row, facts.entry_date, max_pages=cfg["max_mrn_pages"])
        listed = near[key]
        report = None if isinstance(listed, ToolError) else mof.plan_by_mrn(listed, facts.mrn)
        if isinstance(listed, ToolError):
            lookup = "failed"  # 실패, 쪽 상한(too_many), 모양 오류
        elif report is None:
            lookup = "not_found"
        elif _sign(report.call_sign):
            lookup, mrn_sign = "found_signed", report.call_sign
        else:
            lookup = "found_unsigned"
    keyword = mrn_sign or facts.vessel_name
    if not keyword:
        return {"status": "unknown", "reason": "no_clue"}
    if not _spend(budget, 1):
        return {"status": "unknown", "reason": "call_limit"}
    hits = shipfinder.vessel_candidates(keyword)
    if isinstance(hits, ToolError):
        # [왜] 클라이언트의 정한 오류 글을 그대로 싣는다: 한도 소진("내일")과 일시 실패("잠시 뒤")가 갈린다
        return {"status": "unknown", "reason": "lookup_failed", "detail": hits.message}
    signs = sorted({_sign(h.call_sign) for h in hits} - {""})
    plans: dict[str, list[SailingPlan] | None] = {}
    # [왜] 후보마다의 입항 신고는 서류로 확정하는 길(MRN의 신고에 호출부호가 없을 때)에만 쓴다. 다른 길은
    #      받을 일이 없다. 후보 수가 상한을 넘으면 조회하지 않는다: 목록을 잘라 "한 척만 맞다"고 하지 않고,
    #      입항 신고를 받지 못한 것으로 넘겨 되묻는다
    if (
        hits
        and row
        and facts.entry_date
        and lookup == "found_unsigned"
        and len(signs) <= cfg["max_candidates"]
    ):
        for sign in signs:
            if not _spend(budget, 1):
                return {"status": "unknown", "reason": "call_limit"}
            got = mof.plans_for(row, sign, facts.entry_date)
            plans[sign] = None if isinstance(got, ToolError) else got
    # [왜] 배 번호를 글로 둔다. 트레이스 가림(trace.scrub)은 글만 본다. 숫자로 두면 가려지지 않고 나간다
    ships = [{"mmsi": str(h.mmsi), "call_sign": h.call_sign or None, "name": h.ship_name} for h in hits]
    listed_hits = [Candidate(mmsi=h.mmsi, call_sign=h.call_sign or None) for h in hits]
    match = match_vessel(facts, listed_hits, plans, mrn_sign, lookup)
    if match.status == "confirmed":
        chosen = next(s for s in ships if s["mmsi"] == str(match.mmsi))
        return {
            "status": "confirmed",
            "reason": match.reason,
            "basis": match.basis,
            "cap": match.cap,
            **chosen,
        }
    if match.status == "ask":
        # 후보마다 서류로 맞춰 본 결과(선택 카드의 "서류로 본 결과"). 그 후보 하나만 있다고 보고 맞춘 이유
        #      이름이다.
        # [주의] 여기서는 check_candidate를 부르지 않는다. 그것은 사용자가 고른 뒤(ask_vessel)에 한다
        shown = []
        for ship, cand in list(zip(ships, listed_hits, strict=True))[: cfg["max_candidates"]]:
            alone = match_vessel(facts, [cand], plans, mrn_sign, lookup)
            shown.append({**ship, "check": alone.reason})
        # 고른 뒤의 검사가 쓸 것: MRN으로 입항 신고를 찾은 결과와 그 호출부호(공책에는 입항 신고를 두지
        #      않는다)
        return {
            "status": "ask",
            "reason": match.reason,
            "candidates": shown,
            "lookup": lookup,
            "mrn_call_sign": mrn_sign,
        }
    return {"status": "none", "reason": match.reason}
