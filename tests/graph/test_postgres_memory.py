"""대화 기록과 장기 기억을 Postgres에 둔 채 서버를 껐다 켠다 (계획 3d).
대화 기록에 실제 번호가 평문으로 남는 칸도 본다 (R-034). 로컬 DB가 꺼져 있으면 건너뛴다.
"""

import os
import subprocess
import sys

import psycopg
from cryptography.fernet import Fernet
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.types import Command

from marvia.graph.live import live_memory
from marvia.graph.main import build_main_graph

CHILI = {
    "category": "농산물·임산물",
    "same": ["생산국", "품명", "수출업소", "포장장소"],
    "different": [],
    "prior_precise": "받음",
    "prior_result": "적합",
    "prior_cert_on": "2026-03-10",
    "flags": [],
}


class ToolModel(GenericFakeChatModel):
    """정해 둔 AIMessage를 차례로 내는 가짜 모델 (tests/graph/test_agent.py와 같다)."""

    def bind_tools(self, tools, **kwargs):
        return self


def model(*calls: tuple[str, dict]) -> ToolModel:
    """도구 호출 하나씩을 담은 메시지들 뒤에 루프를 끝내는 빈 답을 붙인 가짜 모델."""
    steps = [AIMessage("", tool_calls=[{"name": n, "args": a, "id": f"c-{n}"}]) for n, a in calls]
    return ToolModel(messages=iter([*steps, AIMessage("")]))


def test_conversation_and_item_card_survive_a_restart(agent_deps, test_url):
    key = Fernet.generate_key().decode()  # [왜] 시험 안에서 만든 키. 저장소의 키를 쓰지 않는다
    config = {"configurable": {"thread_id": "pg-memory", "user_id": "u1"}}
    # 첫 번째 서버: 품목 사실을 확인하고 카드를 승인해 저장한다
    first = model(("check_reimport", {"facts": CHILI}), ("save_item_card", {"name": "건고추"}))
    with live_memory(test_url, key) as (saver, store):
        graph = build_main_graph(agent_deps(model=first), saver, loop="agent", store=store)
        graph.invoke({"text": "건고추 카드로 기억해 줘"}, config)
        graph.invoke(Command(resume={"decisions": [{"type": "approve"}]}), config)
    # 두 번째 서버: 새 연결, 새 그래프, 같은 thread·사용자. 앞 차례 기록과 카드를 DB에서 읽는다
    with live_memory(test_url, key) as (saver, store):
        deps = agent_deps(model=model(("recall_memory", {})))
        graph = build_main_graph(deps, saver, loop="agent", store=store)
        graph.invoke({"text": "내가 저장한 품목이 뭐였지?"}, config)
        messages = graph.get_state(config).values["messages"]
    assert sum(m.type == "human" for m in messages) == 2  # 두 차례의 질문이 모두 남았다
    assert "품목 카드 건고추" in [m.content for m in messages if m.type == "tool"][-1]


def test_checkpoints_keep_real_numbers_only_in_the_plain_text_and_answer_channels(agent_deps, test_url):
    key = Fernet.generate_key().decode()
    config = {"configurable": {"thread_id": "pg-encrypted", "user_id": "u1"}}
    with live_memory(test_url, key) as (saver, store):
        deps = agent_deps(model=model(("calc_deadlines", {})))
        graph = build_main_graph(deps, saver, loop="agent", store=store)
        graph.invoke({"text": "DEMO0001 언제까지 수입신고 해야 해요?"}, config)
    # 새 연결, 같은 키: 암호화한 기록을 풀어 읽는다
    with live_memory(test_url, key) as (saver, store):
        graph = build_main_graph(agent_deps(model=model()), saver, loop="agent", store=store)
        assert graph.get_state(config).values["mask_map"] == {"[BL1]": "DEMO0001"}
    with psycopg.connect(test_url) as conn:
        # 직렬화기를 거치는 칸(가림 표, 화물, 메시지, Send 묶음, 재개 값)은 모두 암호문이다
        blobs = "SELECT channel FROM checkpoint_blobs WHERE position('DEMO0001'::bytea IN blob) > 0"
        writes = "SELECT channel FROM checkpoint_writes WHERE position('DEMO0001'::bytea IN blob) > 0"
        assert conn.execute(blobs).fetchall() == []
        assert conn.execute(writes).fetchall() == []
        others = (
            "SELECT checkpoint_id FROM checkpoints WHERE metadata::text LIKE '%DEMO0001%' "
            "OR (checkpoint - 'channel_values')::text LIKE '%DEMO0001%'"
        )
        assert conn.execute(others).fetchall() == []
        # [주의] str 칸은 PostgresSaver가 직렬화기 없이 JSONB로 둔다.
        #        남은 평문은 text·answer뿐이다 (done.md 4.1)
        plain = (
            "SELECT DISTINCT c.key FROM checkpoints, jsonb_each(checkpoint -> 'channel_values') AS c "
            "WHERE c.value::text LIKE '%DEMO0001%'"
        )
        assert {row[0] for row in conn.execute(plain).fetchall()} <= {"text", "answer"}


# 엄격 직렬화 모드에서 그래프를 컴파일하고, 그 그래프가 쓰는 직렬화기에 평문·암호문 값을 읽혀 본다
STRICT_CHECK = """
import sys
from typing import TypedDict

from langgraph._internal import _serde
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import START, StateGraph

from marvia.graph.live import live_memory

class State(TypedDict):
    text: str

assert _serde.STRICT_MSGPACK_ENABLED  # 환경 변수가 이 프로세스에 걸렸다
graph = StateGraph(State)
graph.add_node("n", lambda state: {})
graph.add_edge(START, "n")
with live_memory(sys.argv[1], sys.argv[2]) as (saver, _store):
    serde = graph.compile(checkpointer=saver).checkpointer.serde
    value = {"text": "DEMO0001"}
    assert serde.loads_typed(serde.dumps_typed(value)) == value
    try:
        serde.loads_typed(JsonPlusSerializer().dumps_typed(value))
    except ValueError:
        print("refused")
    else:
        print("read")
"""


def test_strict_msgpack_mode_still_refuses_a_plain_checkpoint_value(test_url):
    # [왜] LANGGRAPH_STRICT_MSGPACK=true면 컴파일이 저장기를 복제하며 직렬화기를 라이브러리 기본 클래스로
    #      다시 만든다(checkpoint/base with_allowlist). 평문 거절이 조용히 사라지면 안 된다 (R-038)
    # [주의] 이 값은 라이브러리가 불러올 때 읽는다. 같은 프로세스에서 값만 바꾸면 고치지 않아도 통과한다
    key = Fernet.generate_key().decode()  # [왜] 시험 안에서 만든 키. 저장소의 키를 쓰지 않는다
    env = {**os.environ, "LANGGRAPH_STRICT_MSGPACK": "true"}
    command = [sys.executable, "-c", STRICT_CHECK, test_url, key]
    run = subprocess.run(command, env=env, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]
    assert run.stdout.strip() == "refused"
