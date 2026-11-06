"""실제 LLM·DB·Voyage로 AgentDeps를 만든다 (계획 3a Task 8). 키와 DB가 필요하다.

하지 않는 일: 그래프 흐름(graph/main.py). 테스트는 이 파일 대신 가짜 AgentDeps를 쓴다(conftest.py).
LLM 실패는 llm.structured가 LLMFailed로 바꿔 던지고, 그래프가 잡아 부분 답으로 간다.
"""

from __future__ import annotations

import httpx
import psycopg

from marvia.config import Settings
from marvia.graph.main import AgentDeps
from marvia.graph.schemas import Draft, Plan
from marvia.llm import chat_model, structured
from marvia.rag.live import live_deps
from marvia.rag.provision import find_provision
from marvia.tools.reimport import ItemFacts
from marvia.tools.rules import load_rules


def agent_deps(settings: Settings, conn: psycopg.Connection) -> AgentDeps:
    """설정의 모델과 로컬 DB로 AgentDeps를 만든다. 만들기만 하고 부르지는 않는다."""
    llm = chat_model(settings)
    return AgentDeps(
        rag=live_deps(settings, conn),  # 계획 2의 RAG 바깥 기능을 그대로 쓴다
        plan=structured(llm, Plan),
        item=structured(llm, ItemFacts),
        write=structured(llm, Draft),
        provision=lambda label, as_of: find_provision(conn, label, as_of),
        model=llm,  # [왜] 에이전트 길은 같은 모델에 도구를 묶어 부른다(create_agent가 bind_tools를 한다)
        # [왜] follow_redirects=False: 넘겨 주는 주소를 따라가면 허용 목록 밖으로 갈 수 있다 (official_lookup)
        web=httpx.Client(timeout=load_rules("agent")["official"]["timeout_s"], follow_redirects=False),
    )
