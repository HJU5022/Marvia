"""배 식별 스위치가 꺼져 있으면(기본) 그래프, 화면 스트림, 공책, 트레이스 가림이 계획 8b 전과 같다 (C1).

계획 8a의 고정 시험은 그래프 폴더와 서버·화면·추적 파일을 측정 커밋(48ca3c5)의 해시로 묶었다.
계획 8b는 그 가운데 다섯 파일(graph/main.py, graph/state.py, server.py, view.py, trace.py)을 고친다.
그 다섯은 해시 묶음에서 빼고 여기서 "스위치가 꺼져 있으면 동작이 같다"로 묶는다.
나머지 파일은 해시 묶음에 그대로 남는다.
아래 값(MODEL_SHA, CARD_SHA, ASK_SHA 포함)은 계획 8b의 첫 코드 커밋 전 상태
(ad17004와 같은 코드, 다섯 파일은 48ca3c5와 같다)에서 낸 값이다. 뒤의 셋은 2bc6073에서 다시 냈다.
값이 달라지면 고치기 전에 무엇이 달라졌는지부터 본다.
"""

import ast
import hashlib
import json
from dataclasses import replace
from pathlib import Path

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from pydantic import Field
from starlette.testclient import TestClient

from marvia.graph.main import LOOPS, build_main_graph
from marvia.graph.schemas import Plan, Step
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
# 모델이 받는 것(묶은 도구 이름의 순서, 메시지 글, 계획자·품목·작성자 프롬프트)을 길 셋에서 적은 것
MODEL_SHA = "de8187c266cc314f21f529503c3ddd4b794eeb3c470e48d65e507ee332e13e27"
# 번호가 애매한 화물의 선택 카드와 직접 적은 글로 재개한 차례: 이벤트와 재개 뒤 공책
CARD_SHA = "d8dbe213efd5cb155faf0f82e34a229c12c58cbc19a1ddf266ff767012e190cd"
# 모델이 부른 ask_user 카드와 직접 적은 글로 재개한 차례: 이벤트, 공책, 다음 모델 호출이 받은 메시지
ASK_SHA = "5ea06eede07f3d4d515e05335678bc80db17221cb34a06e78188f02c4aee067f"
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


class Recorder(ToolModel):
    """가짜 모델이 받은 것을 적는다: 묶은 도구 이름(순서 그대로)과 호출마다 받은 메시지 글(id 뺌)."""

    bound: list = Field(default_factory=list)
    calls: list = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        self.bound.append([getattr(t, "name", None) or t.get("name") for t in tools])
        return self

    def _generate(self, messages, *args, **kwargs):
        self.calls.append(
            [
                [m.type, m.content, [(c["name"], c["args"]) for c in getattr(m, "tool_calls", [])]]
                for m in messages
            ]
        )
        return super()._generate(messages, *args, **kwargs)


def _stable(value):
    """실행마다 달라지는 값(조회 시각, 끼어들기·메시지 id)을 고정 글로 바꾼다."""
    if isinstance(value, dict):
        return {
            k: ("X" if k in ("fetched_at", "id", "interruptId", "message_id", "messageId") else _stable(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_stable(v) for v in value]
    return value


def _client(graph):
    return TestClient(build_app(graph, lambda token: "user-a", web_origin="http://web.test", forget=print))


def _post(client, thread: str, text: str = "", resume: list | None = None) -> list[dict]:
    payload: dict = {"threadId": thread, "runId": f"run-{thread}", "messages": []}
    if text:
        payload["messages"] = [{"id": "m1", "role": "user", "content": text}]
    if resume:
        payload["resume"] = resume
    response = client.post("/agui", json=payload, headers={"Authorization": "Bearer tok"})
    return [json.loads(line[6:]) for line in response.text.split("\n") if line.startswith("data: ")]


def _notebook(graph, thread: str) -> dict:
    values = graph.get_state({"configurable": {"thread_id": f"user-a/{thread}"}}).values
    messages = [[m.type, m.content] for m in values.get("messages", [])]
    rest = {k: v for k, v in values.items() if k != "messages"}
    return {"messages": messages, "values": _stable(rest), "view": _stable(screen_view(values))}


def test_what_the_model_receives_is_unchanged_when_the_switch_is_off(agent_deps):
    # [왜] 11-16 R-136. 위의 해시는 화면과 공책만 본다. 모델이 받는 것(묶은 도구, 메시지 글,
    #      계획자·품목·작성자 프롬프트)이 바뀌어도 화면이 같으면 지나간다. 길 셋 모두 적어 해시한다
    seen = {}
    for loop in LOOPS:
        prompts: dict[str, list] = {"plan": [], "item": [], "write": []}

        def record(name, fn, sink=prompts):
            return lambda prompt: sink[name].append(prompt) or fn(prompt)

        # [왜] 수퍼바이저 길은 먼저 서브에이전트(law)에 넘긴다. 서브에이전트가 묶는 도구도 적는다
        handoff = (
            (_say("handoff", {"to": "law", "task": "조문 찾기"}, 0), AIMessage(""))
            if loop == "supervisor"
            else ()
        )
        model = Recorder(
            messages=iter(
                (
                    *handoff,
                    _say("write_todos", {"todos": [{"content": "기한 계산", "status": "in_progress"}]}, 1),
                    _say("calc_deadlines", {}, 2),
                    AIMessage(""),
                    AIMessage(""),
                    AIMessage(""),
                )
            )
        )
        base = agent_deps(model=model)
        # [왜] 11-16 R-150. 계획자 길은 첫 계획에서 품목 사실 뽑기(extract_item)를 한 번 내게 해
        #      품목 프롬프트도 적는다
        first = iter([Plan(steps=[Step(action="extract_item", query="", reason="품목을 본다")])])
        deps = replace(
            base,
            plan=record("plan", lambda p, sink=first, fn=base.plan: next(sink, None) or fn(p)),
            item=record("item", base.item),
            write=record("write", base.write),
        )
        graph = build_main_graph(
            deps,
            InMemorySaver(),
            loop=loop,
            store=InMemoryStore(),
        )
        events = _post(_client(graph), "off", "DEMO0001 DEMO0002 고춧가루 수입 요건이 뭐예요?")
        assert events[-1]["type"] == "RUN_FINISHED"
        seen[loop] = {"bound": model.bound, "calls": _stable(model.calls), "prompts": _stable(prompts)}
    assert seen["planner"]["prompts"]["item"]  # 품목 프롬프트가 실제로 불렸다
    assert _sha(seen) == MODEL_SHA


def test_a_number_card_and_the_typed_reply_are_unchanged_when_the_switch_is_off(agent_deps):
    # [왜] 11-16 R-136. 번호가 애매해 카드가 뜨는 화물로 멈추고 직접 적은 글로 재개한다. 서버의 카드 처리와
    #      재개 뒤 공책이 꺼진 길에서 그대로여야 한다
    graph = build_main_graph(
        agent_deps(model=ToolModel(messages=iter([AIMessage("")] * 5))),
        InMemorySaver(),
        loop="agent",
        store=InMemoryStore(),
    )
    client = _client(graph)
    first = _post(client, "card", "MOCK12345678TEST87654321 어디예요?")
    card = first[-1]["outcome"]["interrupts"][0]
    resume = [{"interruptId": card["id"], "status": "resolved", "payload": {"custom": "TEST87654321"}}]
    second = _post(client, "card", resume=resume)
    seen = {"first": _stable(first), "second": _stable(second), "notebook": _notebook(graph, "card")}
    assert _sha(seen) == CARD_SHA


def test_an_ask_user_card_and_the_typed_reply_are_unchanged_when_the_switch_is_off(agent_deps):
    # [왜] 11-16 R-136. B가 서버의 카드 처리를 모든 카드에 걸었다. 모델이 ask_user를 부르고
    #      사용자가 글로 답하는 한 차례: 화면 이벤트, 차례 뒤 공책, 다음 모델 호출이 받은 메시지를 묶는다
    options = [
        {"label": "부산", "description": "부산항 기준"},
        {"label": "인천", "description": "인천항 기준"},
    ]
    model = Recorder(
        messages=iter(
            [_say("ask_user", {"question": "어느 항구 기준으로 볼까요?", "options": options}, 1)]
            + [AIMessage("")] * 4
        )
    )
    graph = build_main_graph(agent_deps(model=model), InMemorySaver(), loop="agent", store=InMemoryStore())
    client = _client(graph)
    first = _post(client, "ask", "장치기간이 궁금해요")
    card = first[-1]["outcome"]["interrupts"][0]
    resume = [{"interruptId": card["id"], "status": "resolved", "payload": {"custom": "광양이요"}}]
    second = _post(client, "ask", resume=resume)
    seen = {
        "first": _stable(first),
        "second": _stable(second),
        "notebook": _notebook(graph, "ask"),
        "model": _stable(model.calls),
    }
    assert _sha(seen) == ASK_SHA


def test_the_eval_runner_builds_a_graph_without_the_vessel_step_even_when_the_env_asks_for_it(
    agent_deps, monkeypatch
):
    # [왜] 11-13 판정. 켜는 길은 서버 하나다. 평가 실행기가 스위치를 환경에서 읽으면 측정이 달라진다.
    #      환경에 MARVIA_VESSEL=on을 넣고 평가 실행기가 실제로 만든 그래프를 본다(글자 찾기가 아니라 동작)
    from marvia.eval import run as eval_run
    from marvia.eval.dataset import Item, load_set
    from marvia.tools.rules import load_rules

    monkeypatch.setenv("MARVIA_VESSEL", "on")
    built = []
    real = eval_run.build_main_graph
    monkeypatch.setattr(
        eval_run, "build_main_graph", lambda *a, **k: built.append(real(*a, **k)) or built[-1]
    )
    base = {"id": "T1", "group": "related", "kind": "시험", "behaviour": ["answer"]}
    asked = Item.model_validate({**base, "question": "DEMO0001 언제까지 수입신고 해요?"})
    for loop in ("planner", "agent"):
        deps = agent_deps(model=ToolModel(messages=iter([AIMessage("끝")] * 5)))
        eval_run.evaluate_item(deps, asked, loop, load_set().as_of, load_rules("pricing"))
    assert len(built) == 2 and all("vessel" not in graph.nodes for graph in built)
    # 서버 진입점만 스위치를 읽는다: build_main_graph를 부르며 vessel= 키워드를 넘기는 파일은 server.py뿐이다
    root = Path(__file__).resolve().parents[2]
    passing = []
    # [왜] 폴더 목록으로 좁히면 eval/ 같은 새 폴더의 호출을 놓친다. 시험과 점으로 시작하는 폴더, 설치·빌드
    #      산출물을 뺀 저장소의 모든 .py를 본다. git을 부르지 않는다(git archive로 푼 사본에는 .git이 없다)
    skipped = {"tests", "node_modules", "graphify-out"}
    for path in sorted(root.rglob("*.py")):
        parts = path.relative_to(root).parts
        if any(part.startswith(".") or part in skipped for part in parts[:-1]):
            continue
        name = str(path.relative_to(root))
        for node in ast.walk(ast.parse((root / name).read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and ast.unparse(node.func).split(".")[-1] == "build_main_graph":
                for keyword in node.keywords:
                    if keyword.arg == "vessel":
                        passing.append((name, ast.unparse(keyword.value)))
    assert sorted(passing) == [
        ("e2e/fake_api.py", "settings.vessel == 'on'"),
        ("src/marvia/server.py", "settings.vessel == 'on'"),
    ]


def test_the_default_setting_is_off_and_compose_does_not_turn_it_on_for_the_runtime(monkeypatch):
    from marvia.config import Settings

    monkeypatch.delenv("MARVIA_VESSEL", raising=False)
    assert Settings(_env_file=None).vessel == "off"  # type: ignore[call-arg]
