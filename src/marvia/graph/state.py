"""그래프가 함께 쓰는 공책(state)의 칸을 정한다 (설계 6.2).

하지 않는 일: 값 계산. 계획 1은 식별과 답, 계획 2는 RAG 칸, 계획 3a는 근거·계산·초안·검증 칸을 둔다.
계획 3a에서 빼는 칸: messages(대화 기록), assumptions(권장안으로 진행한 가정), Store(장기 기억).
"""

from __future__ import annotations

from datetime import date
from typing import Required, TypedDict


# [왜] TypedDict는 "이 dict에는 이런 칸이 있다"를 적어 두는 문법이다. 실행 중 검사는 하지 않고 pyright가 본다
# [왜] total=False: 모든 칸이 처음부터 있을 필요는 없다. 노드가 하나씩 채워 간다
class IdentifyState(TypedDict, total=False):
    text: str  # 사용자가 준 단서 글 원문. [주의] LLM에 넘기지 않는다
    masked_text: str  # 번호를 가린 글. LLM에 넘겨도 되는 글
    mask_map: dict[str, str]  # [BL1] → 실제 번호
    numbers: list[str]  # 조회할 번호 (확정한 것만)
    question: dict | None  # 메인 그래프가 사용자에게 물을 것. 없으면 None
    cargos: list[dict]  # 화물별 결과 (CargoIdentity를 dict로 바꾼 것)


# [왜] 메인 그래프는 식별 칸을 모두 쓰고 아래 칸을 더 쓴다. 상속으로 같은 칸을 두 번 적지 않는다
# [주의] 아래 칸(answer 빼고)은 start 노드가 차례마다 비운다. 칸을 더하면 start에도 더한다
class MarviaState(IdentifyState, total=False):
    plan: list[dict]  # 할 일 [{"action", "query", "reason", "status"}]. 진행 중은 하나 (설계 6.2)
    evidence: list[dict]  # 근거 묶음 (Evidence를 dict로 바꾼 것). unit_id마다 하나, 점수 높은 순
    gaps: list[str]  # RAG가 부족하다고 한 빠진 근거 문장 (막힘 처리 재료)
    item: dict  # 사용자가 말한 품목 사실 (ItemFacts를 dict로 바꾼 것). 뽑지 않았으면 빈 dict
    calc: dict  # 계산 결과 {"deadlines": [...], "reimport": {...}}. 인용은 없고 날짜·조건·이름표만
    draft: dict  # 작성자 초안 (Draft를 dict로 바꾼 것, 가린 토큰 그대로)
    verification: list[str]  # 마지막 초안의 검증 위반 (설계 6.2). 빈 목록이면 통과
    write_attempts: int  # 이번 차례 작성자 호출 수
    llm_calls: int  # 이번 차례 LLM 호출 수
    failed_tools: list[dict]  # 실패한 도구 호출 {"tool", "message"}
    answer: str  # 화면에 보낼 답 (번호를 되돌린 글)


# RAG 서브그래프의 공책 (설계 5.4). 메인 그래프와 칸을 나눠 쓰고, 계획 3에서 메인 그래프가 evidence를 받는다
class RagState(TypedDict, total=False):
    # [왜] Required: total=False여도 이 두 칸은 처음 부를 때 꼭 넣는다. 나머지 칸은 노드가 채운다
    question: Required[str]  # 가린 질문. [주의] 실제 번호는 식별 단계에서 이미 토큰으로 바뀐 글이어야 한다
    as_of: Required[date]  # 기준 날짜. 처음엔 오늘, 질문이 날짜를 말하면 질의 분석이 바꾼다
    question_type: str  # 문구 해석 / 위임 사슬 / 다단계 요건 / 화물 결합
    search_query: str  # 지금 검색에 쓰는 질의. 고쳐 쓰면 바뀐다
    evidence: list[dict]  # 근거 묶음 (Evidence를 dict로 바꾼 것, 리랭커 점수 순서)
    sufficient: bool  # 근거 채점 결과
    missing: str  # 부족할 때 빠진 근거. 막힘 처리(계획 3)의 재료
    rewrites: int  # 질의를 고쳐 쓴 횟수
