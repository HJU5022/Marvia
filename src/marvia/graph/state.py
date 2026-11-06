"""그래프가 함께 쓰는 공책(state)의 칸을 정한다 (설계 6.2).

하지 않는 일: 값 계산. 계획 1은 식별과 답, 계획 2는 RAG 칸, 계획 3a는 근거·계산·초안·검증 칸,
계획 3c는 에이전트 루프 칸(messages, todos, assumptions, stopped, out_of_scope)과 루프 공책(LoopState)을 둔다.
계획 3d부터 messages와 mask_map은 차례를 넘어 이어진다(start가 비우지 않는다).
"""

from __future__ import annotations

import operator
from datetime import date
from typing import Annotated, NotRequired, Required, TypedDict

from langchain.agents import AgentState
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from langgraph.managed import RemainingSteps

from marvia.tools.rules import load_rules


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
    # [왜] LangGraph가 단계마다 채우는 값(recursion_limit까지 남은 단계 수). 읽기만 하고 start도 비우지 않는다
    remaining_steps: RemainingSteps
    answer: str  # 화면에 보낼 답 (번호를 되돌린 글)
    # 아래는 에이전트 루프 칸 (계획 3c). 계획자 길에서는 쓰지 않는다
    # [왜] add_messages: 메시지 목록을 덮어쓰지 않고 id로 합친다.
    #      루프가 돌려준 전체 목록을 다시 받아도 겹치지 않는다
    # 에이전트 대화 기록 (가린 글만). 차례를 넘어 이어지고 길면 brief가 앞부분을 요약한다
    messages: Annotated[list[AnyMessage], add_messages]
    todos: list[dict]  # 화면에 보일 할 일 [{"content", "status"}]. 진행 중은 하나 (설계 6.2)
    assumptions: list[str]  # 답이 없어 권장안으로 진행하며 세운 가정 (설계 결정 4의 ②)
    stopped: str  # 루프가 한도·LLM 실패로 멈췄으면 그 이유. 비었으면 정상 끝
    out_of_scope: bool  # 도메인 밖 질문이라 정중히 거절할 차례인가 (설계 1절 "하지 않는 일")
    clarifications: list[str]  # 이번 차례에 사용자에게 물은 것과 답
    # 색인 밖 공식 출처 {"name", "effective", "url", "trust"} (계획 3d). 근거 묶음이 아니라 인용할 수 없다
    official: list[dict]
    watch_news: list[str]  # 감시 중인 화물의 새 변화 (토큰 글, 계획 3d). 이번 차례 답 맨 앞에 보인다
    # 이번 차례에 승인을 받고 실제로 한 일 (토큰 글). 코드가 답 아래에 쓰고 작성자에게 데이터로 준다
    actions: list[str]


def merge_evidence(old: list[dict], new: list[dict], limit: int) -> list[dict]:
    """근거 묶음을 합친다. 같은 unit_id는 점수가 높은 것 하나만 남기고, 점수 높은 순으로 limit개까지 둔다."""
    best: dict[str, dict] = {}
    for item in old + new:
        if item["unit_id"] not in best or item["score"] > best[item["unit_id"]]["score"]:
            best[item["unit_id"]] = item
    return sorted(best.values(), key=lambda item: item["score"], reverse=True)[:limit]


def add_evidence(old: list[dict], new: list[dict]) -> list[dict]:
    """루프 공책의 근거 칸 합치기(reducer). 병렬 검색 결과가 함께 들어와도 merge_evidence로 합친다."""
    return merge_evidence(old, new, load_rules("agent")["answer"]["max_evidence"])


def merge_calc(old: dict, new: dict) -> dict:
    """계산 칸 합치기(reducer). 기한(deadlines)과 재수입(reimport)은 다른 도구가 따로 채운다."""
    return {**old, **new}


def keep_last(old: dict, new: dict) -> dict:
    """나중 값으로 바꾸는 reducer. 같은 단계에 값이 둘 와도 오류 없이 마지막 값을 남긴다."""
    return new


def merge_cargos(old: list[dict], new: list[dict]) -> list[dict]:
    """화물 칸 합치기(reducer). 같은 토큰은 새 조회 결과로 바꾸고, 처음 보는 토큰은 뒤에 붙인다."""
    by_token = {cargo["token"]: cargo for cargo in old}
    by_token.update({cargo["token"]: cargo for cargo in new})
    return list(by_token.values())


# 에이전트 루프(create_agent)의 공책 (계획 3c). 메인 공책과 칸 이름이 같으면 값을 주고받는다
# [왜] 도구는 병렬로 돌 수 있다. 여러 도구가 같은 칸에 쓰면 합치는 함수(reducer)가 있어야 한다
#      (없으면 LangGraph가 InvalidUpdateError를 낸다). 메인 공책은 루프가 끝난 뒤의 전체 값을 받아 덮어쓴다
class LoopState(AgentState):
    masked_text: NotRequired[str]
    # [주의] 도구 안에서 조회할 때만 쓴다. 메시지에 넣지 않는다.
    #        reducer가 없다. ask_user를 혼자 부르게 하는 Guards 덕에만 안전하다
    mask_map: NotRequired[dict[str, str]]
    cargos: NotRequired[Annotated[list[dict], merge_cargos]]
    evidence: NotRequired[Annotated[list[dict], add_evidence]]
    gaps: NotRequired[Annotated[list[str], operator.add]]
    calc: NotRequired[Annotated[dict, merge_calc]]
    # [왜] 한 단계에 check_reimport를 둘 불러도 멈추지 않게 한다. 마지막 판정만 남는다(calc의 reimport와 같다)
    item: NotRequired[Annotated[dict, keep_last]]
    failed_tools: NotRequired[Annotated[list[dict], operator.add]]
    # [왜] 더하기 reducer라 도구·모델 호출은 "몇 번 더 했다"만 돌려준다.
    #      RAG 안의 LLM 호출도 search_law가 더한다
    llm_calls: NotRequired[Annotated[int, operator.add]]
    assumptions: NotRequired[Annotated[list[str], operator.add]]
    searched: NotRequired[
        Annotated[list[str], operator.add]
    ]  # 이번 차례에 이미 찾은 질의 (같은 질의 다시 찾지 않기)
    stopped: NotRequired[str]
    # [왜] 같은 단계에 거절이 둘 와도 멈추지 않는다 (하나라도 거절이면 거절)
    out_of_scope: NotRequired[Annotated[bool, operator.or_]]
    clarifications: NotRequired[Annotated[list[str], operator.add]]
    official: NotRequired[Annotated[list[dict], operator.add]]
    actions: NotRequired[Annotated[list[str], operator.add]]  # 승인한 도구가 병렬로 돌아도 모두 남는다


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
