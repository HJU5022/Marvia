"""RAG 서브그래프 (Agentic RAG): 질의 분석 → 검색·리랭커 → 근거 채점 → 부족하면 질의 고쳐 다시 (설계 5.4).

하지 않는 일: 사용자에게 묻기와 답 쓰기. 부족하면 missing에 담아 끝내고,
그다음 일은 메인 그래프가 정한다(계획 3).
순서도: START → analyze → retrieve → grade → (충분·한도면 END, 아니면 rewrite → retrieve)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from langgraph.graph import END, START, StateGraph

from marvia.graph.state import RagState
from marvia.prompts import render
from marvia.rag.models import Evidence
from marvia.rag.schemas import Grade, QueryAnalysis, Rewrite
from marvia.tools.rules import load_rules


# [왜] 바깥 기능(LLM·DB·Voyage)을 함수로 받아 둔다. 테스트는 가짜 함수를 넣어 키·DB 없이 돈다
@dataclass(frozen=True)
class RagDeps:
    """RAG 서브그래프가 쓰는 바깥 기능 묶음. 실제 값은 marvia.rag.live.live_deps가 만든다."""

    analyze: Callable[[str], QueryAnalysis]  # 프롬프트 → 질의 분석
    search: Callable[[str, date], list[Evidence]]  # (질의, 기준 날짜) → 근거 후보
    rerank: Callable[[str, list[str]], list[float]]  # (질의, 글 목록) → 글마다 점수
    grade: Callable[[str], Grade]  # 프롬프트 → 근거 채점
    rewrite: Callable[[str], Rewrite]  # 프롬프트 → 고친 질의


def top_ranked(
    search: Callable[[str, date], list[Evidence]],
    rerank: Callable[[str, list[str]], list[float]],
    query: str,
    as_of: date,
) -> list[Evidence]:
    """후보를 찾아 리랭커 점수로 다시 줄 세우고 상위 n개를 돌려준다. score는 리랭커 점수다."""
    candidates = search(query, as_of)
    if not candidates:
        return []
    scores = rerank(query, [c.text for c in candidates])
    ranked = sorted(zip(candidates, scores, strict=True), key=lambda pair: pair[1], reverse=True)
    # [왜] model_copy(update=…)로 점수만 리랭커 점수로 바꾼 새 객체를 만든다
    return [
        c.model_copy(update={"score": s}) for c, s in ranked[: load_rules("rag")["search"]["rerank_top_n"]]
    ]


def evidence_block(evidence: list[dict]) -> str:
    """프롬프트에 넣을 근거 글. unit_id를 앞에 붙여 어느 조문인지 보이게 한다. 작성자 프롬프트도 쓴다."""
    return "\n\n".join(f"[{e['unit_id']}] {e['heading']}\n{e['text']}" for e in evidence)


def build_rag_graph(deps: RagDeps, max_rewrites: int | None = None):
    """RAG 서브그래프를 만든다. max_rewrites를 주면 rules/rag.yaml의 고쳐 쓰기 한도 대신 쓴다."""
    cfg = load_rules("rag")
    limit = cfg["loop"]["max_rewrites"] if max_rewrites is None else max_rewrites

    def analyze(state: RagState) -> dict:
        """질문 유형·기준 날짜·검색 질의를 정한다."""
        prompt = render("rag_analyze", question=state["question"], today=state["as_of"].isoformat())
        result = deps.analyze(prompt)
        # [왜] 질문이 날짜를 말하지 않으면(None) 처음 받은 기준 날짜(오늘)를 그대로 쓴다
        return {
            "question_type": result.question_type,
            "search_query": result.search_query,
            "as_of": result.as_of or state["as_of"],
            "rewrites": 0,
        }

    def retrieve(state: RagState) -> dict:
        """하이브리드 검색으로 후보를 찾고, 리랭커로 다시 줄 세워 상위 n개를 근거로 남긴다."""
        # [왜] 노드가 채우는 칸은 .get으로 읽는다. 처음 넣는 칸(question, as_of)만 []로 바로 읽는다
        query = state.get("search_query", "")
        found = top_ranked(deps.search, deps.rerank, query, state["as_of"])
        # [왜] mode="json"은 날짜를 "2026-10-02" 글로 바꾼다. 체크포인트와 화면에 그대로 넘길 수 있다
        return {"evidence": [e.model_dump(mode="json") for e in found]}

    def grade(state: RagState) -> dict:
        """근거가 질문에 답하기에 충분한지 채점한다."""
        evidence = state.get("evidence", [])
        if not evidence:
            return {"sufficient": False, "missing": "검색 결과가 없다"}
        prompt = render("rag_grade", question=state["question"], evidence=evidence_block(evidence))
        result = deps.grade(prompt)
        return {"sufficient": result.sufficient, "missing": "" if result.sufficient else result.missing}

    def rewrite(state: RagState) -> dict:
        """빠진 근거를 보고 검색 질의를 고쳐 쓴다."""
        prompt = render(
            "rag_rewrite",
            question=state["question"],
            query=state.get("search_query", ""),
            missing=state.get("missing", ""),
        )
        return {"search_query": deps.rewrite(prompt).search_query, "rewrites": state.get("rewrites", 0) + 1}

    def after_grade(state: RagState) -> str:
        """충분하거나 고쳐 쓴 횟수가 한도에 닿으면 끝낸다."""
        if state.get("sufficient") or state.get("rewrites", 0) >= limit:
            return END
        return "rewrite"

    graph = StateGraph(RagState)
    graph.add_node("analyze", analyze)
    graph.add_node("retrieve", retrieve)
    graph.add_node("grade", grade)
    graph.add_node("rewrite", rewrite)
    graph.add_edge(START, "analyze")
    graph.add_edge("analyze", "retrieve")
    graph.add_edge("retrieve", "grade")
    graph.add_conditional_edges("grade", after_grade, ["rewrite", END])
    graph.add_edge("rewrite", "retrieve")  # [왜] 고친 질의로 다시 찾는다. 이 화살표가 Agentic RAG의 되돌이다
    return graph.compile()
