"""그래프가 함께 쓰는 공책(state)의 칸을 정한다 (설계 6.2).

하지 않는 일: 값 계산. 계획 1은 식별과 답에 필요한 칸만 두고, plan·evidence·calc 칸은 계획 2·3에서 더한다.
"""

from __future__ import annotations

from typing import TypedDict


# [왜] TypedDict는 "이 dict에는 이런 칸이 있다"를 적어 두는 문법이다. 실행 중 검사는 하지 않고 pyright가 본다
# [왜] total=False: 모든 칸이 처음부터 있을 필요는 없다. 노드가 하나씩 채워 간다
class IdentifyState(TypedDict, total=False):
    text: str  # 사용자가 준 단서 글 원문. [주의] LLM에 넘기지 않는다
    masked_text: str  # 번호를 가린 글. LLM에 넘겨도 되는 글
    mask_map: dict[str, str]  # [BL1] → 실제 번호
    numbers: list[str]  # 조회할 번호 (확정한 것만)
    question: dict | None  # 메인 그래프가 사용자에게 물을 것. 없으면 None
    cargos: list[dict]  # 화물별 결과 (CargoIdentity를 dict로 바꾼 것)


# [왜] 메인 그래프는 식별 칸을 모두 쓰고 답 칸을 하나 더 쓴다. 상속으로 같은 칸을 두 번 적지 않는다
class MarviaState(IdentifyState, total=False):
    answer: str  # 화면에 보낼 답 (번호를 되돌린 글)
