"""선박 식별 중 MRN으로 호출부호를 찾는 단계 (SDD 5.5, 09-28 추가).

B/L → UNI-PASS 화물관리번호 앞 11자리(MRN) → 해수부 입항 신고의 같은 MRN → 그 배의 호출부호.
배 이름으로 찾으면 같은 이름의 배가 여럿 나오거나(동명 선박), 표기가 달라 0척이 나온다.
MRN은 화물 한 건에 하나라서 이름과 상관없이 그 배의 신고를 바로 가리킨다.
해수부 배 이름은 국적선이면 한글이라 ShipFinder 영문 이름과 비교할 수 없고, 호출부호로 이어야 한다 (09-28 실측).

찾지 못하면 None을 돌려준다. 입항 신고 전이거나 해수부가 실패한 경우다.
그때 라우터는 지금까지처럼 배 이름 검색으로 간다 (MRN은 더 정확한 길이지 유일한 길이 아니다).

라우터에 두지 않고 여기에 둔 이유: 라우터는 외부 API를 직접 부르지 않는다 (routers/agent.py 모듈 설명).
"""
from __future__ import annotations

from datetime import timedelta

from backend.app.clients.mof import MofClient, MofError
from backend.app.observability.logging import log_failure
from backend.app.schemas.customs import CustomsRecord

# UNI-PASS 입항(예정)일 앞뒤 며칠의 입항 신고를 훑을지. 09-28 실제 B/L 1건이 ±1일 안에서 찾아졌다.
# 넓힐수록 훑는 페이지가 늘어 느려진다 (±1일 1건 실측 7.0초)
SEARCH_DAYS = 1


def call_sign_from_mrn(customs: CustomsRecord, mof: MofClient | None = None) -> str | None:
    """세관 기록의 MRN으로 해수부 입항 신고를 찾아 호출부호를 돌려준다. 못 찾으면 None."""
    if not customs.mrn or not customs.entry_date:
        return None  # 찾을 근거가 없으면 해수부를 부르지 않는다

    day = customs.entry_date.date()
    try:
        plan = (mof or MofClient()).find_plan_by_mrn(customs.mrn, day - timedelta(days=SEARCH_DAYS), day + timedelta(days=SEARCH_DAYS))
    except MofError as e:
        # 해수부 실패는 식별을 막지 않는다. 라우터가 이름 검색으로 간다. 다만 이름 검색은 느리고 동명선에 약해서
        # 왜 MRN 길을 못 탔는지는 남긴다
        log_failure("identify_mrn", e.code)
        return None
    if plan is None:
        # 입항 신고 전이면 정상적으로 없다 (도착 1주일 안쪽에 신고, 09-23 실측). 해수부 오류와 구분해서 남긴다
        log_failure("identify_mrn", "not_found")
        return None
    return plan.call_sign
