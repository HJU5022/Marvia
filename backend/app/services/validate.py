"""출력 검증 7규칙 (작업 C-7, SDD 5.7).

LLM 판정이 붙은 응답이 나가기 전에 코드가 7규칙을 건다. 위반이 있으면 라우터가 위반 내용을 붙여
LLM에 다시 묻고, 세 번째에도 위반이면 status=failed로 끝낸다 (SDD 5.7 재시도, routers/agent.py).

규칙은 전부 "LLM이 근거 없이 말하지 못하게" 하는 울타리다. 판정 숫자는 코드가 계산하고(C-8),
LLM이 쓴 문장 속 숫자도 근거 카드에 있는 값이어야 한다 (V7).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import get_args

from backend.app.schemas.agent import AgentResponse
from backend.app.schemas.signals import SignalId

KNOWN_RULES = set(get_args(SignalId))  # V2: reasons[].rule은 rules.md의 신호 id (SDD 3.3)
NUMBER = re.compile(r"\d+(?:\.\d+)?")  # V7: answer 안의 숫자. 날짜도 숫자 조각으로 나눠 대조한다
CURRENT_POSITION = "현재 위치"  # V1


@dataclass(frozen=True)
class Violation:
    rule: str  # V1~V7
    detail: str  # LLM에 다시 물을 때 그대로 붙인다 (SDD 5.7)


def check(response: AgentResponse) -> list[Violation]:
    """7규칙을 모두 걸어 위반 목록을 돌려준다. 빈 목록이면 통과."""
    found: list[Violation] = []
    sources = {card.source for card in response.evidence}

    # V1 위치가 오래됐으면 "현재 위치"라고 말하지 않는다
    if response.position and response.position.freshness == "stale" and CURRENT_POSITION in response.answer:
        found.append(Violation("V1", 'The position is stale. Do not write "현재 위치". Say it is the last known position.'))

    # V2 주의·조치 판정에는 켜진 규칙이 1개 이상, 규칙 이름은 신호 id 그대로
    if response.verdict in ("act", "watch"):
        if not response.reasons:
            found.append(Violation("V2", "verdict is act or watch, so give at least one reason."))
        unknown = [r.rule for r in response.reasons if r.rule not in KNOWN_RULES]
        if unknown:
            found.append(Violation("V2", f"reasons[].rule must be one of the given signal ids. Not allowed: {unknown}"))

    # V3 ETA를 말하면 근거 카드가 1장 이상
    eta = response.eta
    if eta and any((eta.ais_eta, eta.mof_eta, eta.calc_eta, eta.trusted_eta)) and not response.evidence:
        found.append(Violation("V3", "An ETA is given but there is no evidence."))

    # V4 배를 확정하지 못했으면 판정하지 않는다
    if response.vessel_match == "uncertain" and response.verdict is not None:
        found.append(Violation("V4", "The vessel is not confirmed, so verdict must be null."))

    # V5 정보 부족이면 무엇이 필요한지 1개 이상 묻는다
    if response.status == "insufficient" and not response.missing_inputs:
        found.append(Violation("V5", "status is insufficient, so name at least one missing input."))

    # V6 상충에서 믿은 출처는 근거 카드에 있는 출처여야 한다
    bad_sources = [c.chosen for c in response.conflicts if c.chosen not in sources]
    if bad_sources:
        found.append(Violation("V6", f"conflicts[].chosen must be one of the evidence sources {sorted(sources)}. Not allowed: {bad_sources}"))

    # V7 answer의 숫자는 근거 카드 값이나 여유 일수에서 온 것이어야 한다
    stray = sorted(set(_numbers(response.answer)) - _allowed_numbers(response), key=float)
    if stray:
        found.append(Violation("V7", f"These numbers in answer are not in the evidence: {stray}. Use only given values."))
    return found


def _numbers(text: str) -> list[str]:
    """숫자 조각을 뽑아 비교하기 좋게 다듬는다. 01과 1, 4.0과 4를 같은 값으로 본다."""
    return [_normal(n) for n in NUMBER.findall(text or "")]


def _allowed_numbers(response: AgentResponse) -> set[str]:
    allowed = {n for card in response.evidence for n in _numbers(card.value)}
    if response.days_margin is not None:
        allowed.add(_normal(str(abs(response.days_margin))))  # "2일 넘깁니다"처럼 부호 없이 말한다
    return allowed


def _normal(number: str) -> str:
    value = float(number)
    return str(int(value)) if value.is_integer() else str(value)
