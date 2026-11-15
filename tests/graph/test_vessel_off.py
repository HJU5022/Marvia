"""배 식별 스위치가 꺼져 있으면(기본) 그래프, 화면 스트림, 공책, 트레이스 가림이 계획 8b 전과 같다 (C1).

계획 8a의 고정 시험은 그래프 폴더와 서버·화면·추적 파일을 측정 커밋(48ca3c5)의 해시로 묶었다.
계획 8b는 그 가운데 다섯 파일(graph/main.py, graph/state.py, server.py, view.py, trace.py)을 고친다.
그 다섯은 해시 묶음에서 빼고 여기서 "스위치가 꺼져 있으면 동작이 같다"로 묶는다.
나머지 파일은 해시 묶음에 그대로 남는다.
아래 값은 계획 8b의 첫 코드 커밋 전(a632dff, 다섯 파일은 48ca3c5와 같다)에 낸 값이다.
값이 달라지면 고치기 전에 무엇이 달라졌는지부터 본다.
"""

import hashlib
import json

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from starlette.testclient import TestClient

from marvia.graph.main import LOOPS, build_main_graph
from marvia.server import build_app
from marvia.trace import scrub
from marvia.view import screen_view

# 길마다 그래프의 노드와 화살표 (get_graph). 스위치가 꺼져 있으면 노드 하나 늘지 않는다
SHAPE_SHA = "e75c31fff2a5071a2a17b7db21c8b9fb3850f68a4507e87b8b891c2091130fa2"
# 가짜 모델 대본 한 차례의 화면 이벤트 전체(조회 시각만 뺀 것)
STREAM_SHA = "48a3d2b6d6d226e7dcc2ae8585de7f168f1442314538b39741d188e5f32a8394"
# 그 차례가 끝난 뒤 공책의 칸 이름과 화물 칸(조회 시각만 뺀 것)
STATE_SHA = "32b3a156446f45ec5f2be40b059ca30a46e744435c45e7888d971d5ec376aee7"
# 길 셋의 한 차례씩: 화면 이벤트, 공책의 칸 이름, 그 둘을 트레이스 가림에 넣은 결과
LOOPS_SHA = "99e5986c5e0f58cb7d17296aa97e89ce9923967e5f290a11b9b072f0fdd6b1b0"
CARD_KEYS = ["error", "fetched_at", "number", "port", "source", "stage", "stage_at", "vessel"]


class ToolModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def _sha(value) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _timeless(value):
    """조회 시각(fetched_at)만 고정 글로 바꾼다. 실행마다 달라지는 값은 이것뿐이다."""
    if isinstance(value, dict):
        return {k: ("T" if k == "fetched_at" else _timeless(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_timeless(v) for v in value]
    return value


def _say(name: str, args: dict, n: int) -> AIMessage:
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": f"s{n}-{name}"}])


def _turn(agent_deps, loop: str = "agent"):
    todos = {"todos": [{"content": "기한 계산", "status": "in_progress"}]}
    steps = (_say("write_todos", todos, 1), _say("calc_deadlines", {}, 2), AIMessage(""))
    graph = build_main_graph(
        agent_deps(model=ToolModel(messages=iter(steps))),
        InMemorySaver(),
        loop=loop,
        store=InMemoryStore(),
    )
    client = TestClient(build_app(graph, lambda token: "user-a", web_origin="http://web.test", forget=print))
    payload = {
        "threadId": "off",
        "runId": "run-off",
        "messages": [{"id": "m1", "role": "user", "content": "DEMO0001 DEMO0002 언제까지 수입신고 해요?"}],
    }
    response = client.post("/agui", json=payload, headers={"Authorization": "Bearer tok"})
    events = [json.loads(line[6:]) for line in response.text.split("\n") if line.startswith("data: ")]
    return graph, events


def test_graph_shape_is_unchanged_when_the_switch_is_off(agent_deps):
    shapes = {}
    for loop in LOOPS:
        deps = agent_deps(model=ToolModel(messages=iter([])))
        drawn = build_main_graph(deps, InMemorySaver(), loop=loop, store=InMemoryStore()).get_graph()
        edges = sorted((e.source, e.target, bool(e.conditional)) for e in drawn.edges)
        shapes[loop] = {"nodes": sorted(drawn.nodes), "edges": edges}
    assert "vessel" not in shapes["agent"]["nodes"]
    assert _sha(shapes) == SHAPE_SHA


def test_screen_stream_is_unchanged_when_the_switch_is_off(agent_deps):
    _, events = _turn(agent_deps)
    assert events[0]["type"] == "RUN_STARTED" and events[-1]["type"] == "RUN_FINISHED"
    snapshots = [e["snapshot"] for e in events if e["type"] == "STATE_SNAPSHOT"]
    assert all(
        sorted(card) == CARD_KEYS for s in snapshots for card in s["cargos"]
    )  # 화물 카드에 새 칸이 없다
    assert _sha(_timeless(events)) == STREAM_SHA


def test_state_after_a_turn_is_unchanged_when_the_switch_is_off(agent_deps):
    graph, _ = _turn(agent_deps)
    values = graph.get_state({"configurable": {"thread_id": "user-a/off"}}).values
    assert not {"vessels", "verdicts", "vessel_question"} & set(values)  # 새 칸은 스위치가 켜졌을 때만 생긴다
    seen = {
        "keys": sorted(values),
        "cargos": _timeless(values["cargos"]),
        "view": _timeless(screen_view(values)),
    }
    assert _sha(seen) == STATE_SHA


def test_other_loops_and_the_trace_scrubber_are_unchanged_when_the_switch_is_off(agent_deps):
    # [왜] 위의 두 시험은 에이전트 길만 돈다. 계획자 길과 수퍼바이저 길의 한 차례, 그리고 그 차례의 이벤트와
    #      공책을 트레이스 가림(trace.scrub)에 넣은 결과도 묶는다. 가림 코드는 계획 8b가 고치는 파일이다
    seen = {}
    for loop in LOOPS:
        graph, events = _turn(agent_deps, loop)
        values = graph.get_state({"configurable": {"thread_id": "user-a/off"}}).values
        view = {k: v for k, v in values.items() if k != "messages"}  # 메시지 id는 실행마다 다르다
        seen[loop] = {
            "events": _timeless(events),
            "keys": sorted(values),
            "scrubbed": _timeless(scrub([events, view])),
        }
        assert not {"vessels", "verdicts", "vessel_question"} & set(values), loop
    assert _sha(seen) == LOOPS_SHA
