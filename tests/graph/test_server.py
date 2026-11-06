"""화면 서버(AG-UI SSE) 시험 (계획 4b Task 5·6, C4·C5·C6·C7). 가짜 모델로 키·네트워크 없이 돈다."""

import json
import threading

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from starlette.testclient import TestClient

from marvia.auth import AuthError
from marvia.graph.main import build_main_graph
from marvia.server import build_app
from marvia.watch import WatchDeps

TOKENS = {"tok-a": "user-a", "tok-b": "user-b"}
TWO = [{"label": "부산", "description": "부산항 기준"}, {"label": "인천", "description": "인천항 기준"}]
SNAPSHOT_KEYS = {"plan", "reading", "cargos", "evidence"}


def verify(token: str) -> str:
    if token not in TOKENS:
        raise AuthError(401, "로그인을 확인하지 못했어요")
    return TOKENS[token]


class ToolModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class Inputs(BaseCallbackHandler):
    def __init__(self):
        self.seen: list[str] = []

    def on_chat_model_start(self, serialized, messages, **kwargs):
        self.seen += [f"{m.content} {getattr(m, 'tool_calls', '')}" for batch in messages for m in batch]


def say(name: str, args: dict, n: int = 0) -> AIMessage:
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": f"s{n}-{name}"}])


def served(agent_deps, *messages, **changes):
    """가짜 모델로 만든 그래프와 그 그래프를 띄운 시험 클라이언트."""
    deps = agent_deps(model=ToolModel(messages=iter(messages)), **changes)
    graph = build_main_graph(deps, InMemorySaver(), loop="agent", store=InMemoryStore())
    app = build_app(graph, verify, web_origin="http://web.test")
    return graph, TestClient(app)


def body(thread: str, text: str = "", resume: list | None = None, **extra) -> dict:
    out = {"threadId": thread, "runId": f"run-{thread}", "messages": [], **extra}
    if text:
        out["messages"] = [{"id": "m1", "role": "user", "content": text}]
    if resume:
        out["resume"] = resume
    return out


def run(client: TestClient, payload: dict, token: str = "tok-a") -> list[dict]:
    response = client.post("/agui", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return [json.loads(line[6:]) for line in response.text.split("\n") if line.startswith("data: ")]


def kinds(events: list[dict]) -> list[str]:
    return [event["type"] for event in events]


def test_a_turn_streams_in_protocol_order_and_sends_only_the_allowed_view(agent_deps):
    todos = {"todos": [{"content": "기한 계산", "status": "in_progress"}]}
    graph, client = served(
        agent_deps, say("write_todos", todos, 1), say("calc_deadlines", {}, 2), AIMessage("")
    )
    events = run(client, body("t1", "DEMO0001 언제까지 수입신고 해요?"))
    order = kinds(events)
    assert order[0] == "RUN_STARTED" and order[-1] == "RUN_FINISHED"
    assert sum(kind in ("RUN_FINISHED", "RUN_ERROR") for kind in order) == 1
    text = [kind for kind in order if kind.startswith("TEXT_MESSAGE")]
    assert text == ["TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END"]
    snapshots = [e["snapshot"] for e in events if e["type"] == "STATE_SNAPSHOT"]
    assert all(set(s) == SNAPSHOT_KEYS for s in snapshots)  # 가림 표·메시지·원문·번호 목록은 가지 않는다
    in_progress = next(
        i for i, e in enumerate(events) if e["type"] == "STATE_SNAPSHOT" and e["snapshot"]["plan"]
    )
    assert in_progress < order.index("TEXT_MESSAGE_START")  # 할 일은 답보다 먼저 보인다
    assert snapshots[-1]["reading"] == [{"token": "[BL1]", "number": "DEMO0001", "kind": "B/L"}]
    assert snapshots[-1]["cargos"][0]["number"] == "DEMO0001"  # 화면에는 주인에게 실제 번호를 보인다
    answer = next(e["delta"] for e in events if e["type"] == "TEXT_MESSAGE_CONTENT")
    assert "시험 답이에요." in answer and events[-1]["outcome"] == {"type": "success"}
    assert "text" not in graph.get_state({"configurable": {"thread_id": "user-a/t1"}}).values


def test_a_question_ends_the_run_with_a_choice_card_and_the_answer_resumes_it(agent_deps):
    ask = say("ask_user", {"question": "어느 항이에요?", "options": TWO}, 1)
    graph, client = served(agent_deps, ask, AIMessage(""))
    events = run(client, body("t2", "장치기간이 궁금해요"))
    outcome = events[-1]["outcome"]
    assert outcome["type"] == "interrupt" and "TEXT_MESSAGE_START" not in kinds(events)
    card = outcome["interrupts"][0]
    assert card["reason"] == "choice" and card["metadata"]["options"][1]["label"] == "인천"
    resume = [{"interruptId": card["id"], "status": "resolved", "payload": {"selected": 1}}]
    events = run(client, body("t2", resume=resume))
    assert events[-1]["outcome"] == {"type": "success"}
    values = graph.get_state({"configurable": {"thread_id": "user-a/t2"}}).values
    assert "인천" in "".join(values["clarifications"])


def test_state_and_forwarded_props_from_the_browser_are_ignored(agent_deps):
    graph, client = served(agent_deps, AIMessage(""))
    sneaky = {"llm_calls": 999, "mask_map": {"[BL1]": "EVIL00001"}, "actions": ["다 지웠어요"]}
    run(client, body("t4", "DEMO0001 언제까지?", state=sneaky, forwardedProps=sneaky))
    values = graph.get_state({"configurable": {"thread_id": "user-a/t4"}}).values
    assert values["mask_map"] == {"[BL1]": "DEMO0001"}
    assert values["llm_calls"] < 999 and values["actions"] == []


def test_configurable_keys_from_the_browser_never_reach_the_run_config(agent_deps, monkeypatch):
    # [왜] call 시점 configurable이 with_config 값을 덮는다(R-072). 설정은 서버 값으로만 만든다
    from marvia import server

    seen: list[dict] = []
    real = server.turn_events

    def spy(graph, payload, config, *args):
        seen.append(config)
        return real(graph, payload, config, *args)

    monkeypatch.setattr(server, "turn_events", spy)
    evil = {"configurable": {"surface": "cli", "user_id": "evil", "thread_id": "x"}}
    graph, client = served(agent_deps, AIMessage(""))
    run(client, body("t9", "DEMO0001 언제까지?", state=evil, forwardedProps=evil))
    assert seen == [{"configurable": {"thread_id": "user-a/t9", "user_id": "user-a"}}]
    assert graph.get_state(seen[0]).values["mask_map"] == {"[BL1]": "DEMO0001"}


def test_no_login_is_401_and_the_graph_is_not_called(agent_deps):
    graph, client = served(agent_deps)  # [왜] 모델 메시지가 없다. 그래프가 돌면 StopIteration으로 실패한다
    for headers in ({}, {"Authorization": "Bearer wrong"}):
        response = client.post("/agui", json=body("t5", "DEMO0001 언제?"), headers=headers)
        assert response.status_code == 401
    assert graph.get_state({"configurable": {"thread_id": "user-a/t5"}}).values == {}


def test_another_users_thread_id_reaches_only_that_users_own_thread(agent_deps):
    graph, client = served(agent_deps, AIMessage(""), AIMessage(""))
    run(client, body("shared", "DEMO0001 언제까지?"), token="tok-a")
    events = run(client, body("shared", "그 화물 어디 있어요?"), token="tok-b")
    assert "DEMO0001" not in json.dumps(events, ensure_ascii=False)
    values = graph.get_state({"configurable": {"thread_id": "user-b/shared"}}).values
    assert values.get("mask_map", {}) == {}  # B는 A의 가림 표를 읽지 못한다


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        (body("bad/id", "질문"), 422),
        (body("t6", ""), 422),
        (body("t6", "가" * 2001), 422),
        (body("t6", resume=[{"interruptId": "x", "status": "resolved", "payload": {}}]), 409),
        ({"threadId": "t6"}, 422),
    ],
    ids=["thread-id", "empty", "too-long", "nothing-to-resume", "shape"],
)
def test_bad_requests_are_refused_before_the_graph_runs(agent_deps, payload, status):
    _, client = served(agent_deps)
    response = client.post("/agui", json=payload, headers={"Authorization": "Bearer tok-a"})
    assert response.status_code == status


def test_a_second_run_on_a_busy_thread_is_409(agent_deps, fake_rag):
    entered, gate = threading.Event(), threading.Event()
    rag = fake_rag()

    def slow_search(query, as_of):
        entered.set()
        gate.wait(10)  # [왜] 첫 차례를 검색 안에 붙잡아 두고 둘째 요청을 보낸다
        return rag.search(query, as_of)

    slow = type(rag)(**{**rag.__dict__, "search": slow_search})
    _, client = served(agent_deps, say("search_law", {"query": "수입신고 기한"}, 1), AIMessage(""), rag=slow)
    first: list = []
    worker = threading.Thread(target=lambda: first.append(run(client, body("t8", "수입신고 기한?"))))
    worker.start()
    assert entered.wait(10)
    second = client.post("/agui", json=body("t8", "또 물어요"), headers={"Authorization": "Bearer tok-a"})
    gate.set()
    worker.join(10)
    assert second.status_code == 409
    assert first[0][-1]["type"] == "RUN_FINISHED"


def test_cors_opens_only_the_screen_origin(agent_deps):
    _, client = served(agent_deps)
    asked = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization"}
    ok = client.options("/agui", headers={"Origin": "http://web.test", **asked})
    other = client.options("/agui", headers={"Origin": "http://evil.test", **asked})
    assert ok.headers.get("access-control-allow-origin") == "http://web.test"
    assert "access-control-allow-origin" not in other.headers


def test_the_server_refuses_to_start_without_model_and_data_keys(monkeypatch, tmp_path):
    # [왜] 키 없이 뜨면 차례마다 실패한다. 시작에서 거절해 배포 확인(dry-run)에서 바로 보이게 한다 (C10)
    from marvia import server

    monkeypatch.chdir(tmp_path)  # [왜] 저장소의 .env를 읽지 않게 빈 폴더에서 돈다
    for name in ("MARVIA_ANTHROPIC_API_KEY", "MARVIA_VOYAGE_API_KEY", "MARVIA_DATA_KEY", "K_SERVICE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MARVIA_AUTH", "dev")
    monkeypatch.setenv("MARVIA_DEV_TOKEN", "local-dev-token")
    with pytest.raises(RuntimeError, match="MARVIA_ANTHROPIC_API_KEY"):
        server.main()


def test_the_view_links_only_to_the_official_site_over_https(evidence):
    # [왜] 근거 패널의 링크는 국가법령정보센터(rules agent.yaml official.allowed_hosts)만 연다.
    #      javascript: 링크를 막는다
    from marvia.view import screen_view

    urls = [
        "https://www.law.go.kr/법령/관세법",
        "javascript:alert(1)",
        "http://www.law.go.kr/x",
        "https://evil.test/x",
    ]
    values = {"evidence": [dict(evidence[0], unit_id=f"u{i}", source_url=url) for i, url in enumerate(urls)]}
    assert [e["source_url"] for e in screen_view(values)["evidence"]] == [urls[0], None, None, None]


def test_an_approval_card_shows_real_numbers_but_the_model_gets_tokens_back(agent_deps):
    inputs, added = Inputs(), []
    watch = WatchDeps(add=lambda *row: added.append(row), news=lambda user: [], ack=lambda user, ids: None)
    steps = (say("watch_cargo", {"token": "[BL1]"}, 1), AIMessage(""))
    deps = agent_deps(model=ToolModel(messages=iter(steps)), watch=watch)
    graph = build_main_graph(deps, InMemorySaver(), loop="agent", store=InMemoryStore())
    # [왜] 그래프에 기록 콜백을 붙여 모델이 받은 글을 모두 본다
    app = build_app(graph.with_config(callbacks=[inputs]), verify, web_origin="http://web.test")
    client = TestClient(app)
    card = run(client, body("t3", "DEMO0001 계속 지켜봐 줘"))[-1]["outcome"]["interrupts"][0]
    assert card["reason"] == "approval" and card["metadata"]["actions"][0]["args"] == {"token": "DEMO0001"}
    edit = {"type": "edit", "edited_action": {"name": "watch_cargo", "args": {"token": "DEMO0001"}}}
    resume = [{"interruptId": card["id"], "status": "resolved", "payload": {"decisions": [edit]}}]
    assert run(client, body("t3", resume=resume))[-1]["outcome"] == {"type": "success"}
    assert added == [("user-a", "DEMO0001", "반입신고")]  # 다시 가린 [BL1]로 도구가 돌았다
    assert not any("DEMO0001" in text for text in inputs.seen)  # 모델은 화면에서 온 실제 번호를 받지 않았다


def test_an_edit_with_a_number_new_to_the_thread_ends_as_a_rejection_and_adds_nothing(agent_deps):
    added = []
    watch = WatchDeps(add=lambda *row: added.append(row), news=lambda user: [], ack=lambda user, ids: None)
    steps = (say("watch_cargo", {"token": "[BL1]"}, 1), AIMessage(""))
    deps = agent_deps(model=ToolModel(messages=iter(steps)), watch=watch)
    graph = build_main_graph(deps, InMemorySaver(), loop="agent", store=InMemoryStore())
    client = TestClient(build_app(graph, verify, web_origin="http://web.test"))
    card = run(client, body("t10", "DEMO0001 계속 지켜봐 줘"))[-1]["outcome"]["interrupts"][0]
    edit = {"type": "edit", "edited_action": {"name": "watch_cargo", "args": {"token": "DEMO0009"}}}
    resume = [{"interruptId": card["id"], "status": "resolved", "payload": {"decisions": [edit]}}]
    assert run(client, body("t10", resume=resume))[-1]["outcome"] == {"type": "success"}
    assert added == []
