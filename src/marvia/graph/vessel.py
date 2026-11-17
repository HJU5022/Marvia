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
import time
from collections.abc import Callable
from datetime import date, datetime

from langgraph.types import interrupt

from marvia.graph.state import MarviaState
from marvia.identify.models import CargoFacts, ToolError
from marvia.tools import mof, shipfinder
from marvia.tools.judge import judge
from marvia.tools.ports import port
from marvia.tools.rules import load_rules
from marvia.tools.signals import watches_ship
from marvia.tools.vessel import KST, SailingPlan
from marvia.tools.vessel_match import Candidate, Match, MrnLookup, check_candidate, match_vessel

_clock = time.monotonic  # [왜] 시험이 시계를 바꿔 끼운다


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
            # [왜] 그 후보 하나만 보면 확정인데 같은 호출부호가 검색 결과에서 겹치면, 그것이 되묻는 까닭이다
            twins = [h for h in listed_hits if _sign(h.call_sign) == _sign(ship["call_sign"])]
            many = alone.status == "confirmed" and bool(_sign(ship["call_sign"])) and len(twins) > 1
            shown.append({**ship, "check": "same_call_sign_many_mmsi" if many else alone.reason})
        # 고른 뒤의 검사가 쓸 것: MRN으로 입항 신고를 찾은 결과와 그 호출부호(공책에는 입항 신고를 두지
        #      않는다)
        return {
            "status": "ask",
            "reason": match.reason,
            "candidates": shown,
            # 검색 결과 전체(카드에 보이는 둘이나 상한으로 자르기 전). 같은 호출부호의 다른 배를 가리는 데
            #      쓴다
            "hits": [{"mmsi": ship["mmsi"], "call_sign": ship["call_sign"]} for ship in ships],
            "lookup": lookup,
            "mrn_call_sign": mrn_sign,
        }
    return {"status": "none", "reason": match.reason}


def find_vessels(state: MarviaState) -> dict:
    """vessel 노드: 조회에 성공한 화물마다 배를 찾는다. 한 차례에 max_cargos건까지 찾고 하나만 되묻는다."""
    cfg = load_rules("vessel")
    # [왜] 되돌리기 요청(계획 8c, D17): 이번 차례에 말한 화물에 소비하지 않은 요청이 있으면 그 화물의 행을
    #      지워 다시 찾는다. 한 차례에 한 번이고 한 대화에서 토큰마다 redo_limit번까지다. 세는 곳은 여기다.
    #      상한에 닿은 요청은 바깥 호출 없이 소비하고 앞의 행에 그렇다고 적는다
    redo, consumed = state.get("vessel_redo", {}), dict(state.get("vessel_consumed", {}))
    refound = dict(state.get("vessel_refound", {}))
    dropped: set[str] = set()
    capped: set[str] = set()
    for cargo in state.get("cargos", []):
        token = cargo["token"]
        if cargo.get("facts") and redo.get(token, 0) > consumed.get(token, 0):
            if refound.get(token, 0) < cfg["redo_limit"]:
                dropped.add(token)
                refound[token] = refound.get(token, 0) + 1
            else:
                capped.add(token)
            consumed[token] = redo[token]
    # [왜] 확정한 배와 "모르겠어요"라고 답한 화물은 같은 대화에서 다시 찾거나 다시 묻지 않는다
    kept = {
        v["token"]: ({**v, "redo_capped": True} if v["token"] in capped else v)
        for v in state.get("vessels", [])
        if (v["status"] in ("confirmed", "user_choice") or v["reason"] == "user_skipped")
        and v["token"] not in dropped
    }
    rows: list[dict] = []
    question = None
    looked = 0
    started = _clock()
    near: dict = {}  # 같은 차례에 같은 항만·같은 날의 해수부 입항 신고 목록은 한 번만 받는다
    for cargo in state.get("cargos", []):
        token = cargo["token"]
        if not cargo.get("facts"):
            continue  # 조회에 실패한 화물은 화물 카드가 이미 그 까닭을 보인다
        facts = CargoFacts.model_validate(cargo["facts"])
        if token in kept:
            rows.append(kept[token])
            continue
        if not watches_ship(facts.stage):
            rows.append({"token": token, "status": "unknown", "reason": "landed"})  # 바깥 호출이 없다
            continue
        if looked >= cfg["max_cargos"]:
            rows.append({"token": token, "status": "unknown", "reason": "over_cap"})
            continue
        if looked and _clock() - started >= cfg["max_seconds"]:
            rows.append({"token": token, "status": "unknown", "reason": "time_limit"})
            continue
        looked += 1
        found = find_vessel(facts, near=near)
        ships = found.pop("candidates", [])
        meta = {
            "lookup": found.pop("lookup", "none"),
            "mrn_call_sign": found.pop("mrn_call_sign", None),
            "hits": found.pop("hits", []),
        }
        if found["status"] == "ask" and question is not None:
            found = {"status": "unknown", "reason": "another_question"}
        elif found["status"] == "ask":
            # [왜] 이름·호출부호·배 번호는 끼어들기 값에 싣지 않는다(트레이스와 체크포인트로 간다).
            #      자리표만 싣고 서버가 화면으로 보낼 때 이 후보들(question["candidates"])로 바꾼다
            options = [
                {"label": f"{{ship{i}}}", "description": f"{{ship{i}_info}}"}
                for i in range(1, min(len(ships), cfg["max_choices"]) + 1)
            ]
            question = {
                "kind": "choice",
                "question": cfg["question"].format(token=token),
                "options": [cfg["skip"], *options],
                "recommended": 0,  # [왜] 근거 없이 한 척을 권하지 않는다. 권고는 "배 없이 진행"이다
                "token": token,
                "candidates": ships,
                **meta,  # 고른 뒤 검사가 쓴다
            }
        rows.append({"token": token, **found})
    # [왜] 화물 칸은 이번 차례에 말한 화물만 담는다. 말하지 않은 화물의 확정과 답도 다음 차례를 위해 남긴다
    seen = {row["token"] for row in rows}
    rows += [row for token, row in kept.items() if token not in seen]
    # [왜] 지난 차례의 카드 답은 이번 차례 날짜의 근거가 아니다. 화물이 없는 차례에도 비운다 (계획 8c, D21)
    return {
        "vessels": rows,
        "vessel_question": question,
        "verdicts": [],
        "turn_answers": [],
        "vessel_refound": refound,
        "vessel_consumed": consumed,
    }


def check_pick(state: MarviaState, token: str, question: dict, picked: dict) -> Match:
    """고른 후보를 check_candidate에 건다. 그 배의 입항 신고는 서류로 맞추는 길일 때만 한 번 받는다."""
    cargo = next(c for c in state.get("cargos", []) if c["token"] == token)
    facts = CargoFacts.model_validate(cargo["facts"])
    # [왜] 검색 결과 전체를 넘긴다. 카드에 보인 후보만 넘기면 잘린 쪽의 같은 호출부호의 배를 놓쳐 상한이
    #      빠진다
    everyone = [Candidate(mmsi=int(c["mmsi"]), call_sign=c["call_sign"]) for c in question["hits"]]
    mine = Candidate(mmsi=int(picked["mmsi"]), call_sign=picked["call_sign"])
    lookup: MrnLookup = question.get("lookup", "none")
    plans: dict[str, list[SailingPlan] | None] = {}
    row = port(facts.port_code) if facts.port_code else None
    sign = _sign(picked["call_sign"])
    if lookup == "found_unsigned" and sign and row and facts.entry_date:
        got = mof.plans_for(row, sign, facts.entry_date)
        if isinstance(got, ToolError):
            lookup = (
                "failed"  # 고른 뒤의 조회가 실패하면 조회 실패로 본다(확신 상한과 이유 mrn_lookup_failed)
            )
        else:
            plans[sign] = got
    return check_candidate(facts, mine, everyone, plans, question.get("mrn_call_sign"), lookup)


def ask_vessel(state: MarviaState) -> dict:
    """ask_vessel 노드: 선택 카드로 묻고 답으로 배를 정한다. 답이 없으면 배 없이 진행하고 가정으로 남긴다."""
    cfg = load_rules("vessel")
    question = state.get("vessel_question") or {}
    # [주의] 재개하면 이 노드가 처음부터 다시 돈다. interrupt 앞에 바깥 조회를 두지 않는다
    reply = interrupt({k: question[k] for k in ("kind", "question", "options", "recommended")}) or {}
    ships, picked = question["candidates"], None
    selected = reply.get("selected")
    # [왜] 번호만 받는다. 직접 입력한 글은 서버가 후보와 맞춰 번호로 바꿔 보낸다(server.turn_input)
    #      그래서 사용자가 적은 호출부호가 그래프의 입력과 트레이스에 실리지 않는다
    if isinstance(selected, int) and 1 <= selected <= len(ships):
        picked = ships[selected - 1]
    reason = "user_skipped" if "selected" in reply else "no_answer"  # 시간 초과나 취소는 선택이 없다
    token = question["token"]
    if picked:
        # [왜] 사용자가 고른 배를 같은 검사에 건다(check_candidate). 서류로 맞추는 길(MRN 조회가 성공했고
        #      신고에
        #      호출부호가 없을 때)에는 그 배의 입항 신고를 이때 한 번 받는다(해수부 요청 1회, rules
        #      pick_calls).
        #      받지 못하면 조회 실패로 본다. 입항 신고는 공책에 두지 않는다
        found = check_pick(state, token, question, picked)
        row = {
            "token": token,
            "status": found.status,  # user_choice: 자동 확정(confirmed)과 구분한다
            "reason": found.reason,
            "basis": found.basis,
            "cap": found.cap,
            "mmsi": picked["mmsi"],
            "call_sign": picked["call_sign"],
            "name": picked["name"],
        }
    else:
        row = {"token": token, "status": "unknown", "reason": reason}
    update: dict = {
        "vessels": [row if v["token"] == token else v for v in state.get("vessels", [])],
        "vessel_question": None,
    }
    if not picked and reason == "no_answer":
        update["assumptions"] = [*state.get("assumptions", []), cfg["assumption"].format(token=token)]
    return update


def _given_dates(cells: dict) -> dict:
    """공책의 날짜 칸(ISO 글)을 judge가 받는 꼴로 바꾼다. 처음 알던 도착 예정은 그날 낮 시각이다."""
    hour = load_rules("vessel")["dates"]["first_eta_hour"]
    out: dict = {}
    if cells.get("sale_date"):
        out["sale_due"] = date.fromisoformat(cells["sale_date"])
    if cells.get("forwarder_eta"):
        out["forwarder_eta"] = date.fromisoformat(cells["forwarder_eta"])
    if cells.get("first_eta"):
        day = date.fromisoformat(cells["first_eta"])
        out["first_eta"] = datetime(day.year, day.month, day.day, hour, tzinfo=KST)
    return out


# [주의] 돌려주는 타입을 Callable로 적지 않는다. 인자 이름(state)이 빠져 add_node 타입 검사가 거절한다
def verdict_node(now: Callable[[], datetime]):
    """verdict 노드를 만든다. now는 판정의 기준 시각(시험이 고정한다)."""

    def verdict(state: MarviaState) -> dict:
        ships = {v["token"]: v for v in state.get("vessels", [])}
        limit = load_rules("vessel")["max_cargos"]
        out = []
        looked = 0
        for cargo in state.get("cargos", []):
            ship = ships.get(cargo["token"])
            # [왜] 이번 차례의 화물 조회가 실패했으면 지난 차례에 배를 확정했어도 판정하지 않는다
            if ship is None or not cargo.get("facts"):
                continue
            facts = CargoFacts.model_validate(cargo["facts"])
            position = plan = None
            # [왜] 배를 확정하지 못했거나 내린 화물이면 위치와 일정을 부르지 않는다.
            #      판정은 화물 사실만으로 낸다(tools/judge.py). 도착 시각을 모르니 등급이 비고
            #      확신이 내려간다. 값을 지어내지 않는다
            # [주의] 지난 차례에 배를 확정했어도 이번 차례 단계가 내린 뒤면 배를 보지 않는다
            #      (화물 수 상한 칸도 쓰지 않는다)
            sailing = ship["status"] in ("confirmed", "user_choice") and watches_ship(facts.stage)
            capped = sailing and looked >= limit
            if sailing and not capped:
                looked += 1
                got = shipfinder.vessel_position(int(ship["mmsi"]))
                position = None if isinstance(got, ToolError) else got
                row = port(facts.port_code) if facts.port_code else None
                if row and ship.get("call_sign"):
                    today = now().astimezone(KST).date()  # 한국 날짜
                    schedule = mof.port_schedule(
                        row, ship["call_sign"], today=today, entry_date=facts.entry_date
                    )
                    plan = None if isinstance(schedule, ToolError) else schedule
            # [왜] 호출부호를 코드로 맞춘 배만 "확실"이 될 수 있다. 서류(입항일·적재항)로만 확정했거나
            #      사용자가 고른 배,
            #      같은 호출부호의 배가 여럿인 배는 확신이 부분을 넘지 못한다(11-15 판정). 상한은 judge가 건다
            cap = ship.get("cap") if sailing else None
            given = _given_dates(state.get("cargo_dates", {}).get(cargo["token"], {}))
            found = judge(facts, position, plan, now=now(), cap=cap, cap_note="ship_unchecked", **given)
            found = found.model_dump(mode="json")
            if capped:
                found["notes"].append("over_cap")  # 글은 rules/vessel.yaml reasons에 있다
            out.append({"token": cargo["token"], **found})
        return {"verdicts": out}

    return verdict
