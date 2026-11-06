"""실제 LLM·DB·Voyage로 AgentDeps를 만든다 (계획 3a Task 8). 키와 DB가 필요하다.
대화 기록(checkpointer)과 장기 기억(Store)도 Postgres에 둔다 (계획 3d, 설계 8절).

하지 않는 일: 그래프 흐름(graph/main.py). 테스트는 이 파일 대신 가짜 AgentDeps를 쓴다(conftest.py).
LLM 실패는 llm.structured가 LLMFailed로 바꿔 던지고, 그래프가 잡아 부분 답으로 간다.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import httpx
import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres import PostgresStore

from marvia.config import Settings
from marvia.graph.main import AgentDeps
from marvia.graph.schemas import Draft, Plan
from marvia.llm import chat_model, structured
from marvia.rag.live import live_deps
from marvia.rag.provision import find_provision
from marvia.tools.reimport import ItemFacts
from marvia.tools.rules import load_rules
from marvia.watch import live_watch, watch_keys


def agent_deps(settings: Settings, conn: psycopg.Connection) -> AgentDeps:
    """설정의 모델과 로컬 DB로 AgentDeps를 만든다. 만들기만 하고 부르지는 않는다."""
    llm = chat_model(settings)
    # [왜] 키가 없으면 실제 번호를 저장하지 않는다(fail-closed).
    #      watch=None이면 그래프에 watch_cargo와 새 소식이 없다
    secret = settings.watch_key.get_secret_value()
    watch = live_watch(conn, watch_keys(secret)) if secret else None
    return AgentDeps(
        rag=live_deps(settings, conn),  # 계획 2의 RAG 바깥 기능을 그대로 쓴다
        plan=structured(llm, Plan),
        item=structured(llm, ItemFacts),
        write=structured(llm, Draft),
        provision=lambda label, as_of: find_provision(conn, label, as_of),
        model=llm,  # [왜] 에이전트 길은 같은 모델에 도구를 묶어 부른다(create_agent가 bind_tools를 한다)
        # [왜] follow_redirects=False: 넘겨 주는 주소를 따라가면 허용 목록 밖으로 갈 수 있다 (official_lookup)
        web=httpx.Client(timeout=load_rules("agent")["official"]["timeout_s"], follow_redirects=False),
        watch=watch,  # 감시 표는 같은 로컬 DB에 있다(migrations/002_watch.sql)
    )


@contextmanager
def live_memory(url: str) -> Iterator[tuple[PostgresSaver, PostgresStore]]:
    """대화 기록(checkpointer)과 장기 기억(Store)을 Postgres에 둔다. 표가 없으면 만든다."""
    # [왜] from_conn_string은 연결을 열고 닫는 with 블록이다. 블록을 나가면 연결이 닫힌다
    with PostgresSaver.from_conn_string(url) as saver, PostgresStore.from_conn_string(url) as store:
        # [왜] setup은 표가 없을 때만 만들고 있으면 그대로 둔다. 처음 쓰기 전에 꼭 불러야 한다
        saver.setup()
        store.setup()
        yield saver, store
