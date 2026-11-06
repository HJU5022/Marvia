"""실제 LLM·DB·Voyage로 RagDeps를 만든다 (계획 2 Task 8). 키와 DB가 필요하다.

하지 않는 일: 그래프 흐름(graph/rag.py). 테스트는 이 파일을 쓰지 않고 가짜 RagDeps를 만든다.
"""

from __future__ import annotations

from datetime import date

import psycopg

from marvia.config import Settings
from marvia.graph.rag import RagDeps, top_ranked
from marvia.llm import chat_model, structured
from marvia.rag import voyage
from marvia.rag.graphdb import graph_expand
from marvia.rag.mcp import build_server, mcp_ranked
from marvia.rag.models import Evidence
from marvia.rag.schemas import Grade, QueryAnalysis, Rewrite
from marvia.rag.search import hybrid_search


def live_deps(settings: Settings, conn: psycopg.Connection) -> RagDeps:
    """설정의 모델과 로컬 DB로 RagDeps를 만든다."""
    llm = chat_model(settings)
    # [왜] 그래프를 끄면 계획 3b 전과 같은 검색이다
    expand = graph_expand(settings) if settings.graph == "on" else None

    def embed(texts: list[str]) -> list[list[float]]:
        return voyage.embed(texts, settings, "query")

    def search(query: str, as_of: date) -> list[Evidence]:
        return hybrid_search(conn, query, embed, as_of, expand)

    def rerank(query: str, texts: list[str]) -> list[float]:
        return voyage.rerank(query, texts, settings)

    # [왜] mcp: 같은 검색 함수를 MCP 서버에 싣고, RAG는 MCP 클라이언트로 그 서버를 부른다 (설계 9절)
    via_mcp = settings.rag_via == "mcp"
    ranked = mcp_ranked(build_server(lambda q, d: top_ranked(search, rerank, q, d))) if via_mcp else None
    return RagDeps(
        analyze=structured(llm, QueryAnalysis),
        search=search,
        rerank=rerank,
        grade=structured(llm, Grade),
        rewrite=structured(llm, Rewrite),
        ranked=ranked,
    )
