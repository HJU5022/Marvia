"""재수입 검사 판정: 같은 물품을 다시 들여올 때 서류검사 대상 요건을 채우는지 본다 (설계 7.1 reimport_check).

하지 않는 일: 사실 짐작(모르는 사실은 missing에 담는다), "면제" 단정(결과는 "서류검사 요건 충족"까지),
재량 검사 판단(무작위표본검사 등은 늘 caveats에 붙인다), 인용 만들기(설계 5.6: basis는 별표 이름표일 뿐이다).
1차는 별표 10 제4호 다목(농산물·임산물)·마목(기구·용기·포장)만 본다. 다른 구분은 "대상 아님".
요건 표·사유 표·단서 문장은 rules/reimport.yaml에서 읽는다.
"""

from __future__ import annotations

import calendar
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from marvia.tools.deadlines import due_date
from marvia.tools.rules import load_rules

# [왜] Literal 값은 rules/reimport.yaml의 키와 같다. LLM이 이 중에서만 고르게 해 표에서 바로 찾는다
Category = Literal["농산물·임산물", "기구·용기·포장", "그 외", "모름"]
SameField = Literal["생산국", "품명", "수출업소", "포장장소", "제조국", "해외제조업소", "재질", "바탕색상"]
Flag = Literal[
    "기준·규격 신설·강화",
    "정밀검사 대상 반송품",
    "부적합 처분 이력",
    "특별관리 영업자",
    "유해물질 검출 업소",
    "수입 최소량 미만 뒤 이상",
    "보완 미이행·반려 3회 이상",
]


class ItemFacts(BaseModel):
    """사용자가 말한 품목 사실. LLM이 채우는 모양이자 reimport_check의 입력이다."""

    # [주의] 기본값을 두지 않는다. 기본값이 있으면 JSON 스키마의 선택 칸이 되어 구조화 출력 한도에 걸리기 쉽다
    category: Category = Field(description="품목 구분. 사용자가 말하지 않았으면 모름")
    same: list[SameField] = Field(description="사용자가 이전 수입과 같다고 말한 칸")
    different: list[SameField] = Field(description="사용자가 이전 수입과 다르다고 말한 칸")
    prior_precise: Literal["받음", "안 받음", "모름"] = Field(description="이전 수입 때 정밀검사를 받았나")
    prior_result: Literal["적합", "부적합", "모름"] = Field(description="이전 정밀검사 결과")
    prior_cert_on: date | None = Field(description="이전 정밀검사 뒤 수입신고확인증 발급일. 모르면 null")
    flags: list[Flag] = Field(description="사용자가 해당한다고 말한 정밀검사 사유. 말하지 않은 것은 빼기")


class ReimportResult(BaseModel):
    """재수입 검사 판정 결과."""

    verdict: Literal["서류검사 요건 충족", "정밀검사 대상", "사실 부족", "대상 아님"]
    failed: list[str]  # 어긋난 조건 (하나라도 있으면 정밀검사 대상)
    missing: list[str]  # 사용자에게 더 물을 사실
    caveats: list[str]  # 늘 함께 보여 줄 단서 (재량 검사, 확인하지 않은 사유, 개정 예정)
    window_end: date | None  # 다시 수입해야 하는 마지막 날. 발급일을 모르면 None
    basis: list[str]  # 별표 이름표. 인용이 아니다


def _years_later(start: date, years: int) -> date:
    """start에서 years년 뒤 같은 날. 그날이 없으면(2월 29일) 그달 말일."""
    # [왜] 민법 제157조·제160조: 발급 다음 날부터 세면 years년 뒤 같은 날에 끝나고,
    #      그달에 같은 날이 없으면 그달 말일에 끝난다 (제160조제3항)
    year = start.year + years
    return start.replace(year=year, day=min(start.day, calendar.monthrange(year, start.month)[1]))


def reimport_check(facts: ItemFacts, today: date) -> ReimportResult:
    """재수입 물품이 서류검사 대상 요건을 채우는지 본다.

    입력: facts=사용자가 말한 품목 사실, today=오늘 (이번 수입신고 날로 본다).
    출력: 어긋난 조건이 있으면 "정밀검사 대상", 없지만 모르는 사실이 있으면 "사실 부족",
          모두 채우면 "서류검사 요건 충족". 다목·마목 밖의 구분이면 "대상 아님".
    주의: 사용자가 말하지 않은 정밀검사 사유는 없다고 보지 않고 caveats에 남긴다.
    """
    rules = load_rules("reimport")
    if facts.category == "그 외":
        return ReimportResult(
            verdict="대상 아님",
            failed=[],
            missing=[],
            caveats=[rules["other_category"]],
            window_end=None,
            basis=[],
        )
    failed: list[str] = []
    missing: list[str] = []
    caveats: list[str] = list(rules["caveats"])
    basis: list[str] = [rules["basis"]]

    # 1. 다시 정밀검사가 되는 사유 (사용자가 말한 것만)
    flags = list(dict.fromkeys(facts.flags))  # [왜] 같은 사유가 두 번 와도 한 번만 센다 (순서는 그대로)
    for flag in flags:
        failed.append(f"{flag} ({rules['forced'][flag]})")
        basis.append(rules["forced"][flag])
    if facts.prior_result == "부적합":
        failed.append(rules["prior_failed"])
    unstated = [f"{flag} ({item})" for flag, item in rules["forced"].items() if flag not in flags]
    if unstated:
        caveats.append("다음에 해당하면 정밀검사 대상이다: " + ", ".join(unstated))

    # 2. 동일사 동일수입식품등의 칸 (별표 10 제4호 다목·마목)
    category = rules["categories"].get(facts.category)
    if category is None:  # 모름
        missing.append("품목 구분 (농산물·임산물 / 기구·용기·포장)")
    else:
        basis.append(category["basis"])
        caveats.append(category["caveat"])
        for field in category["fields"]:
            if field in facts.different:
                failed.append(f"{field} 다름")
            elif field not in facts.same:
                missing.append(f"{field} 같은지")

    # 3. 이전 정밀검사 (별표 10 제1호가목1)·3))
    if facts.prior_precise == "안 받음":
        failed.append(f"이전 정밀검사 없음 ({rules['prior_basis']})")
    elif facts.prior_precise == "모름":
        missing.append("이전 정밀검사를 받았는지")

    # 4. 기간 (별표 10 제4호: 수입신고확인증 발급일부터 window_years년 이내)
    window_end = None
    if facts.prior_cert_on is None:
        missing.append("이전 정밀검사 뒤 수입신고확인증 발급일")
    elif facts.prior_cert_on > today:
        # [왜] 발급일이 오늘보다 뒤일 수는 없다. 연도를 잘못 읽었을 수 있어 판정에 쓰지 않고 다시 묻는다
        missing.append("이전 정밀검사 뒤 수입신고확인증 발급일 (오늘보다 뒤라 다시 확인)")
    else:
        # [왜] 끝날이 토·일·공휴일이면 다음 날 끝난다 (민법 제161조).
        #      공휴일 표는 rules/deadlines.yaml을 같이 쓴다
        # [추정] 민법 제161조를 이 기간에 적용한 예규는 확인하지 못했다
        holidays = set(load_rules("deadlines")["holidays"])
        window_end = due_date(_years_later(facts.prior_cert_on, rules["window_years"]), 0, holidays)
        if window_end > max(holidays):
            # [왜] 공휴일 표 뒤의 날은 토·일만 넘긴다. 공휴일을 반영하지 못했다고 알린다
            last = max(holidays)
            caveats.append(f"공휴일 표가 {last}까지라 기간 끝날 계산에 그 뒤 공휴일은 반영하지 못했다")
        if today > window_end:
            failed.append(f"{rules['window_years']}년 지남 ({window_end}까지)")

    # [왜] 어긋난 조건이 하나라도 있으면 다른 사실을 몰라도 정밀검사 대상이다
    if failed:
        verdict = "정밀검사 대상"
    elif missing:
        verdict = "사실 부족"
    else:
        verdict = "서류검사 요건 충족"
    return ReimportResult(
        verdict=verdict,
        failed=failed,
        missing=missing,
        caveats=caveats,
        window_end=window_end,
        basis=basis,
    )
