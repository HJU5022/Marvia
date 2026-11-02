"""실제 LLM·DB·Voyage로 AgentDeps를 만든다 (계획 3a Task 8). 키와 DB가 필요하다.

하지 않는 일: 그래프 흐름(graph/main.py). 테스트는 이 파일 대신 가짜 AgentDeps를 쓴다(conftest.py).
LLM 실패는 llm.structured가 LLMFailed로 바꿔 던지고, 그래프가 잡아 부분 답으로 간다.
"""

from __future__ import annotations

import psycopg

from marvia.config import Settings
from marvia.graph.main import AgentDeps
from marvia.graph.schemas import Draft, Plan
from marvia.llm import chat_model, structured
from marvia.rag.live import live_deps
from marvia.tools.reimport import ItemFacts


def agent_deps(settings: Settings, conn: psycopg.Connection) -> AgentDeps:
    """설정의 모델과 로컬 DB로 AgentDeps를 만든다. 만들기만 하고 부르지는 않는다."""
    llm = chat_model(settings)
    return AgentDeps(
        rag=live_deps(settings, conn),  # 계획 2의 RAG 바깥 기능을 그대로 쓴다
        plan=structured(llm, Plan),
        item=structured(llm, ItemFacts),
        write=structured(llm, Draft),
    )
