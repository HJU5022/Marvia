"""화면 서버(AG-UI SSE) 시험 (계획 4b Task 5·6, C4·C5·C6·C7). 가짜 모델로 키·네트워크 없이 돈다."""

import asyncio
import json
import logging
import threading
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from cryptography.fernet import Fernet
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langfuse import get_client
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from psycopg.conninfo import make_conninfo
from starlette.testclient import TestClient

from marvia import langfuse_trace
from marvia.auth import TRACING_VARS, AuthError
from marvia.config import Settings
from marvia.graph.live import live_memory
from marvia.graph.main import build_main_graph
from marvia.graph.resume import NEW_NUMBER
from marvia.server import build_app, forget_account
from marvia.watch import WatchDeps, add_watch, watch_keys

TOKENS = {"tok-a": "user-a", "tok-b": "user-b", "tok-ab": "user-ab"}
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
    app = build_app(graph, verify, web_origin="http://web.test", forget=lambda user: None)
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
    sneaky = {"llm_calls": 999, "mask_map": {"[BL1]": "NOPE00001"}, "actions": ["다 지웠어요"]}
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


def test_the_reading_list_names_a_container_number():
    # [왜] 이름표 → 화면 이름 표에 없는 토큰은 KeyError로 화면 보기 전체를 깨뜨린다 (계획 6a)
    from marvia.view import screen_view

    reading = screen_view({"mask_map": {"[CNTR1]": "DEMU1234560"}})["reading"]
    assert reading == [{"token": "[CNTR1]", "number": "DEMU1234560", "kind": "컨테이너 번호"}]


def test_an_approval_card_carries_the_korean_label_and_the_choices_from_the_rules():
    # [왜] 화면이 규칙 목록을 따로 들고 있으면 규칙이 바뀔 때 어긋난다. 카드가 한국어 이름과 고를 값을 싣는다
    from marvia.tools.rules import load_rules
    from marvia.view import interrupt_card

    def request(name):
        return {"name": name, "args": {}, "description": ""}

    value = {"action_requests": [request("save_preference"), request("watch_cargo"), request("new_tool")]}
    prefs, watch, unknown = interrupt_card(value, {})["actions"]
    rules = load_rules("agent")
    depths = rules["memory"]["depths"]
    assert (prefs["label"], prefs["choices"]) == (rules["approval"]["labels"]["save_preference"], depths)
    assert (watch["label"], watch["choices"]) == ("화물 감시 추가", None)
    assert (unknown["label"], unknown["choices"]) == ("new_tool", None)  # 이름이 없는 도구는 영어 이름 그대로


def test_an_approval_card_shows_real_numbers_but_the_model_gets_tokens_back(agent_deps):
    inputs, added = Inputs(), []
    watch = WatchDeps(add=lambda *row: added.append(row), news=lambda user: [], ack=lambda user, ids: None)
    steps = (say("watch_cargo", {"token": "[BL1]"}, 1), AIMessage(""))
    deps = agent_deps(model=ToolModel(messages=iter(steps)), watch=watch)
    graph = build_main_graph(deps, InMemorySaver(), loop="agent", store=InMemoryStore())
    # [왜] 그래프에 기록 콜백을 붙여 모델이 받은 글을 모두 본다
    app = build_app(graph.with_config(callbacks=[inputs]), verify, web_origin="http://web.test", forget=print)
    client = TestClient(app)
    card = run(client, body("t3", "DEMO0001 계속 지켜봐 줘"))[-1]["outcome"]["interrupts"][0]
    assert card["reason"] == "approval" and card["metadata"]["actions"][0]["args"] == {"token": "DEMO0001"}
    edit = {"type": "edit", "edited_action": {"name": "watch_cargo", "args": {"token": "DEMO0001"}}}
    resume = [{"interruptId": card["id"], "status": "resolved", "payload": {"decisions": [edit]}}]
    assert run(client, body("t3", resume=resume))[-1]["outcome"] == {"type": "success"}
    assert added == [("user-a", "DEMO0001", "반입신고")]  # 다시 가린 [BL1]로 도구가 돌았다
    assert not any("DEMO0001" in text for text in inputs.seen)  # 모델은 화면에서 온 실제 번호를 받지 않았다


def test_an_edit_with_a_number_new_to_the_thread_ends_as_a_rejection_and_adds_nothing(agent_deps):
    inputs, added = Inputs(), []
    watch = WatchDeps(add=lambda *row: added.append(row), news=lambda user: [], ack=lambda user, ids: None)
    steps = (say("watch_cargo", {"token": "[BL1]"}, 1), AIMessage(""))
    deps = agent_deps(model=ToolModel(messages=iter(steps)), watch=watch)
    graph = build_main_graph(deps, InMemorySaver(), loop="agent", store=InMemoryStore())
    client = TestClient(
        build_app(graph.with_config(callbacks=[inputs]), verify, web_origin="http://web.test", forget=print)
    )
    card = run(client, body("t10", "DEMO0001 계속 지켜봐 줘"))[-1]["outcome"]["interrupts"][0]
    edit = {"type": "edit", "edited_action": {"name": "watch_cargo", "args": {"token": "DEMO0009"}}}
    resume = [{"interruptId": card["id"], "status": "resolved", "payload": {"decisions": [edit]}}]
    assert run(client, body("t10", resume=resume))[-1]["outcome"] == {"type": "success"}
    assert added == []
    assert not any("DEMO0009" in text for text in inputs.seen)  # 모델은 화면에서 온 새 번호를 받지 않았다
    # [왜] 새 번호 갈래를 지워도 [BL2]로 가려져 위 검사는 통과한다. 거절 글이 모델에 닿았는지로 갈래를 본다
    assert any(NEW_NUMBER["message"] in text for text in inputs.seen)


class Stub:
    """그래프 자리에 들어가는 가짜: get_state와 stream만 있다."""

    def __init__(self, interrupts=(), error: Exception | None = None):
        self.interrupts, self.error = list(interrupts), error

    def with_config(self, **kwargs):
        return self

    def get_state(self, config):
        return SimpleNamespace(values={}, interrupts=self.interrupts)

    def stream(self, *args, **kwargs):
        if self.error:
            raise self.error
        return iter([])


def test_a_failure_after_the_graph_run_still_ends_with_one_run_error():
    # [왜] 모르는 모양의 interrupt 값으로 카드 만들기가 죽어도 끝 이벤트가 정확히 하나여야 한다 (C6)
    unknown = SimpleNamespace(id="i1", value={"weird": 1})
    client = TestClient(build_app(Stub([unknown]), verify, web_origin="http://web.test", forget=print))
    order = kinds(run(client, body("t11", "질문")))
    assert order == ["RUN_STARTED", "RUN_ERROR"]


def test_the_server_log_names_the_error_class_and_place_but_never_the_message(caplog):
    client = TestClient(
        build_app(Stub(error=RuntimeError("DEMO0001 비밀")), verify, web_origin="http://x.test", forget=print)
    )
    with caplog.at_level(logging.INFO):
        events = run(client, body("t12", "질문"))
    assert kinds(events)[-1] == "RUN_ERROR"
    assert "RuntimeError" in caplog.text and "server.py" in caplog.text
    assert "DEMO0001" not in caplog.text


def test_the_login_check_runs_off_the_event_loop():
    on_loop = []

    def checking(token):
        try:
            asyncio.get_running_loop()
            on_loop.append(True)
        except RuntimeError:
            on_loop.append(False)
        return "user-a"

    client = TestClient(build_app(Stub(), checking, web_origin="http://web.test", forget=print))
    run(client, body("t13", "질문"))
    assert on_loop == [False]


def test_only_the_last_message_is_read_and_it_must_be_user_text(agent_deps):
    _, client = served(agent_deps)
    head = {"Authorization": "Bearer tok-a"}
    user = {"id": "m1", "role": "user", "content": "질문이에요"}
    for messages in (
        [user, {"id": "m2", "role": "assistant", "content": "답이에요"}],  # 앞의 user 글로 물러서지 않는다
        [user, {"id": "m3", "role": "user", "content": [{"type": "text", "text": "x"}]}],
    ):
        response = client.post("/agui", json=body("t14") | {"messages": messages}, headers=head)
        assert response.status_code == 422


@pytest.mark.parametrize("selected", ["0", 99, -1, True, 1.5, None], ids=str)
def test_a_choice_outside_the_cards_options_is_422_and_the_card_stays(agent_deps, selected):
    ask = say("ask_user", {"question": "어느 항이에요?", "options": TWO}, 1)
    graph, client = served(agent_deps, ask, AIMessage(""))
    card = run(client, body("t15", "장치기간이 궁금해요"))[-1]["outcome"]["interrupts"][0]
    resume = [{"interruptId": card["id"], "status": "resolved", "payload": {"selected": selected}}]
    response = client.post(
        "/agui", json=body("t15", resume=resume), headers={"Authorization": "Bearer tok-a"}
    )
    assert response.status_code == 422
    assert graph.get_state(
        {"configurable": {"thread_id": "user-a/t15"}}
    ).interrupts  # 카드는 그대로 열려 있다


@pytest.mark.parametrize(
    "payload",
    [{"custom": 123}, {"custom": ["a"]}, {"custom": "가" * 2001}, {"timeout": "yes"}, {"timeout": 1}],
    ids=str,
)
def test_a_choice_answer_must_be_text_within_the_cap_and_timeout_a_bool(agent_deps, payload):
    # [왜] custom이 글이 아니면 뒤에서 TypeError로 차례가 죽고, 상한은 글자 수로만 확인되던 곳이 있었다
    ask = say("ask_user", {"question": "어느 항이에요?", "options": TWO}, 1)
    graph, client = served(agent_deps, ask, AIMessage(""))
    card = run(client, body("t17", "장치기간이 궁금해요"))[-1]["outcome"]["interrupts"][0]
    resume = [{"interruptId": card["id"], "status": "resolved", "payload": payload}]
    response = client.post(
        "/agui", json=body("t17", resume=resume), headers={"Authorization": "Bearer tok-a"}
    )
    assert response.status_code == 422
    assert graph.get_state({"configurable": {"thread_id": "user-a/t17"}}).interrupts


@pytest.mark.parametrize(
    "decision",
    [
        {"type": "reject", "message": "가" * 2001},
        {"type": "edit", "edited_action": {"name": "watch_cargo", "args": {"token": "가" * 2001}}},
    ],
    ids=["reject", "edit"],
)
def test_approval_text_is_capped_like_a_question_and_the_card_stays(agent_deps, decision):
    watch = WatchDeps(add=lambda *row: None, news=lambda user: [], ack=lambda user, ids: None)
    steps = (say("watch_cargo", {"token": "[BL1]"}, 1), AIMessage(""))
    deps = agent_deps(model=ToolModel(messages=iter(steps)), watch=watch)
    graph = build_main_graph(deps, InMemorySaver(), loop="agent", store=InMemoryStore())
    client = TestClient(build_app(graph, verify, web_origin="http://web.test", forget=print))
    card = run(client, body("t18", "DEMO0001 계속 지켜봐 줘"))[-1]["outcome"]["interrupts"][0]
    resume = [{"interruptId": card["id"], "status": "resolved", "payload": {"decisions": [decision]}}]
    response = client.post(
        "/agui", json=body("t18", resume=resume), headers={"Authorization": "Bearer tok-a"}
    )
    assert response.status_code == 422
    assert graph.get_state({"configurable": {"thread_id": "user-a/t18"}}).interrupts


def test_a_cancelled_card_resumes_without_its_payload_on_the_recommended_path(agent_deps):
    ask = say("ask_user", {"question": "어느 항이에요?", "options": TWO}, 1)
    graph, client = served(agent_deps, ask, AIMessage(""))
    card = run(client, body("t16", "장치기간이 궁금해요"))[-1]["outcome"]["interrupts"][0]
    resume = [{"interruptId": card["id"], "status": "cancelled", "payload": {"selected": 1}}]
    assert run(client, body("t16", resume=resume))[-1]["outcome"] == {"type": "success"}
    said = "".join(graph.get_state({"configurable": {"thread_id": "user-a/t16"}}).values["clarifications"])
    assert "부산" in said and "인천" not in said


@pytest.mark.parametrize(("host_env", "expected"), [(None, "127.0.0.1"), ("0.0.0.0", "0.0.0.0")])
def test_main_listens_on_loopback_unless_marvia_host_says_otherwise(
    monkeypatch, tmp_path, host_env, expected
):
    # [왜] 컨테이너 밖에서 돌리면 이 컴퓨터의 모든 주소에서 듣지 않게 한다. 컨테이너는 MARVIA_HOST로 연다
    from contextlib import contextmanager

    from marvia import server

    @contextmanager
    def fake(*args, **kwargs):
        yield (None, None) if args and isinstance(args[0], str) and len(args) == 2 else None

    monkeypatch.chdir(tmp_path)
    for name, value in {
        "MARVIA_AUTH": "dev",
        "MARVIA_DEV_TOKEN": "local-dev-token",
        "MARVIA_ANTHROPIC_API_KEY": "k",
        "MARVIA_VOYAGE_API_KEY": "k",
        "MARVIA_DATA_KEY": "k",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.delenv("MARVIA_HOST", raising=False)
    for name in TRACING_VARS:  # [왜] 셸에 켜진 트레이싱 변수가 시작 검사에 걸리지 않게 한다
        monkeypatch.delenv(name, raising=False)
    if host_env:
        monkeypatch.setenv("MARVIA_HOST", host_env)
    seen = {}
    monkeypatch.setattr(server, "live_memory", fake)
    monkeypatch.setattr(server, "read_pool", fake)
    monkeypatch.setattr(server.psycopg, "connect", fake)
    monkeypatch.setattr(server, "agent_deps", lambda *a: None)
    monkeypatch.setattr(server, "build_main_graph", lambda *a, **k: None)
    monkeypatch.setattr(server, "tracer_callbacks", lambda settings: ["tracer"])
    monkeypatch.setattr(server, "build_app", lambda *a, **k: seen.update(callbacks=k["callbacks"]))
    monkeypatch.setattr(server.uvicorn, "run", lambda app, **kwargs: seen.update(kwargs))
    monkeypatch.setenv("PORT", "9999")
    server.main()
    # [왜] 서버도 CLI·평가와 같은 트레이서 콜백(trace.tracer_callbacks)을 앱에 넘긴다 (계획 6b)
    assert seen == {"host": expected, "port": 9999, "callbacks": ["tracer"]}


def test_a_failed_run_sends_the_fixed_error_text_and_the_next_request_is_served():
    client = TestClient(
        build_app(Stub(error=RuntimeError("DEMO0001 비밀")), verify, web_origin="http://x.test", forget=print)
    )
    for _ in range(2):  # [왜] 둘째 요청이 200이면 실패한 차례가 잠금을 풀었다는 뜻이다
        last = run(client, body("t17", "질문"))[-1]
        assert (
            last["type"] == "RUN_ERROR"
            and last["message"] == "이번 차례를 끝내지 못했어요. 다시 물어봐 주세요."
        )
        assert "DEMO0001" not in json.dumps(last, ensure_ascii=False)


def test_a_body_over_the_cap_is_413(agent_deps):
    _, client = served(agent_deps)
    big = body("t18", "질문") | {"state": {"pad": "x" * 70000}}
    response = client.post("/agui", json=big, headers={"Authorization": "Bearer tok-a"})
    assert response.status_code == 413


def test_resuming_with_another_card_id_while_one_is_pending_is_409(agent_deps):
    ask = say("ask_user", {"question": "어느 항이에요?", "options": TWO}, 1)
    graph, client = served(agent_deps, ask, AIMessage(""))
    run(client, body("t19", "장치기간이 궁금해요"))
    resume = [{"interruptId": "another-card", "status": "resolved", "payload": {"selected": 1}}]
    response = client.post(
        "/agui", json=body("t19", resume=resume), headers={"Authorization": "Bearer tok-a"}
    )
    assert response.status_code == 409
    assert graph.get_state({"configurable": {"thread_id": "user-a/t19"}}).interrupts  # 카드는 그대로다


def test_the_real_run_carries_the_server_surface_and_the_tokens_user(agent_deps, monkeypatch):
    # [왜] turn_events가 받은 설정만 보는 R-072 시험과 달리, 그래프 안에서 user_of가 실제로 본 설정을 본다
    from marvia.graph import main, tools

    seen: list[dict] = []
    real = tools.user_of

    def spy(config):
        seen.append(dict(config["configurable"]))
        return real(config)

    monkeypatch.setattr(tools, "user_of", spy)
    monkeypatch.setattr(main, "user_of", spy)
    graph, client = served(agent_deps, AIMessage(""))
    evil = {"configurable": {"surface": "cli", "user_id": "evil"}}
    run(client, body("t20", "DEMO0001 언제까지?", forwardedProps=evil))
    assert seen and all(c["surface"] == tools.SERVER_SURFACE and c["user_id"] == "user-a" for c in seen)


def test_account_deletion_forgets_watches_memory_and_only_that_users_threads(agent_deps, db):
    # [왜] R-033: 계정을 지우면 감시 목록, 장기 기억, 그 사람의 대화 기록(체크포인트)이 남지 않는다.
    #      남의 것은 그대로다
    schema = db.execute("SELECT current_schema()").fetchone()[0]
    db.commit()
    url = make_conninfo(Settings().database_url, options=f"-c search_path={schema},public")
    secret = Fernet.generate_key().decode()  # [왜] 시험 안에서 만든 키. 저장소의 키를 쓰지 않는다
    add_watch(db, watch_keys(secret), "user-a", "DEMO0001", "반입신고")
    add_watch(db, watch_keys(secret), "user-b", "DEMO0002", "반입신고")
    with live_memory(url, secret) as (saver, store), psycopg.connect(url, autocommit=True) as conn:
        deps = agent_deps(model=ToolModel(messages=iter([AIMessage(""), AIMessage(""), AIMessage("")])))
        graph = build_main_graph(deps, saver, loop="agent", store=store)
        forget = lambda user: forget_account(conn, store, user, url)  # noqa: E731
        client = TestClient(build_app(graph, verify, web_origin="http://web.test", forget=forget))
        run(client, body("t1", "DEMO0001 언제까지?"), token="tok-a")
        run(client, body("t1", "DEMO0002 언제까지?"), token="tok-b")
        run(
            client, body("t1", "DEMO0003 언제까지?"), token="tok-ab"
        )  # [왜] "user-a" 앞머리가 겹치는 다른 사용자
        mine = "SELECT count(*) FROM {} WHERE thread_id LIKE 'user-a/%'"
        assert conn.execute(mine.format("checkpoint_blobs")).fetchone()[0] > 0  # 지우기 전에는 있었다
        store.put(("users", "user-a", "items"), "고추", {"name": "고추"})
        store.put(("users", "user-a", "prefs"), "depth", {"depth": "짧게"})
        store.put(("users", "user-a", "later"), "x", {"n": 1})  # [왜] 나중에 생긴 이름 공간도 지워야 한다
        store.put(("users", "user-ab", "items"), "밀", {"name": "밀"})
        store.put(("users", "user-b", "items"), "쌀", {"name": "쌀"})
        assert client.delete("/account").status_code == 401
        assert client.delete("/account", headers={"Authorization": "Bearer tok-a"}).status_code == 204
        threads = {row[0] for row in conn.execute("SELECT DISTINCT thread_id FROM checkpoints")}
        assert threads == {"user-b/t1", "user-ab/t1"}  # "user-a/"로 시작하는 것만 지웠다
        for table in ("checkpoint_blobs", "checkpoint_writes"):
            assert conn.execute(mine.format(table)).fetchone()[0] == 0
        assert store.search(("users", "user-a")) == []
        assert [item.key for item in store.search(("users", "user-ab", "items"))] == ["밀"]
        assert [item.key for item in store.search(("users", "user-b", "items"))] == ["쌀"]
    assert db.execute("SELECT user_id FROM watches").fetchall() == [("user-b",)]


def test_an_event_the_encoder_cannot_serialize_still_ends_with_one_run_error():
    class Unserializable(Stub):
        def stream(self, *args, **kwargs):
            # [왜] 화물 칸에 JSON으로 바꿀 수 없는 값이 섞인 갱신
            return iter([((), {"read": {"todos": [{"content": object(), "status": "pending"}]}})])

    client = TestClient(build_app(Unserializable(), verify, web_origin="http://x.test", forget=print))
    events = run(client, body("t21", "질문"))
    assert kinds(events) == ["RUN_STARTED", "RUN_ERROR"]
    assert events[-1]["message"] == "이번 차례를 끝내지 못했어요. 다시 물어봐 주세요."
    assert kinds(run(client, body("t21", "질문"))) == ["RUN_STARTED", "RUN_ERROR"]  # 잠금도 풀렸다


def test_a_cancelled_approval_card_rejects_every_action_even_with_an_approve_payload(agent_deps):
    added = []
    watch = WatchDeps(add=lambda *row: added.append(row), news=lambda user: [], ack=lambda user, ids: None)
    steps = (say("watch_cargo", {"token": "[BL1]"}, 1), AIMessage(""))
    deps = agent_deps(model=ToolModel(messages=iter(steps)), watch=watch)
    graph = build_main_graph(deps, InMemorySaver(), loop="agent", store=InMemoryStore())
    client = TestClient(build_app(graph, verify, web_origin="http://web.test", forget=print))
    card = run(client, body("t22", "DEMO0001 계속 지켜봐 줘"))[-1]["outcome"]["interrupts"][0]
    approve = {"decisions": [{"type": "approve"}]}
    resume = [{"interruptId": card["id"], "status": "cancelled", "payload": approve}]
    assert run(client, body("t22", resume=resume))[-1]["outcome"] == {"type": "success"}
    assert added == []  # 취소한 카드의 승인 payload는 읽지 않았다


class NoTransactionOnWatchConn:
    """감시 연결 대역: 트랜잭션을 열거나 대화 기록 표를 건드리면 실패한다 (R-041)."""

    def __init__(self, real):
        self.real = real

    def transaction(self, *args, **kwargs):
        raise AssertionError("감시 연결 위에 트랜잭션을 열었다")

    def execute(self, query, *args, **kwargs):
        assert "checkpoint" not in str(query), "감시 연결로 대화 기록을 지웠다"
        return self.real.execute(query, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.real, name)


def test_account_deletion_never_opens_a_transaction_on_the_watch_connection(agent_deps, db):
    schema = db.execute("SELECT current_schema()").fetchone()[0]
    db.commit()
    url = make_conninfo(Settings().database_url, options=f"-c search_path={schema},public")
    secret = Fernet.generate_key().decode()
    with live_memory(url, secret) as (saver, store), psycopg.connect(url, autocommit=True) as conn:
        deps = agent_deps(model=ToolModel(messages=iter([AIMessage("")])))
        graph = build_main_graph(deps, saver, loop="agent", store=store)
        client = TestClient(build_app(graph, verify, web_origin="http://x.test", forget=print))
        run(client, body("t1", "DEMO0001 언제까지?"), token="tok-a")
        forget_account(NoTransactionOnWatchConn(conn), store, "user-a", url)
        assert not conn.execute("SELECT 1 FROM checkpoints WHERE thread_id LIKE 'user-a/%'").fetchall()


def test_account_deletion_is_409_while_a_turn_of_that_user_runs():
    entered, gate, forgotten = threading.Event(), threading.Event(), []

    class Slow(Stub):
        def stream(self, *args, **kwargs):
            entered.set()
            gate.wait(10)
            return iter([])

    client = TestClient(build_app(Slow(), verify, web_origin="http://x.test", forget=forgotten.append))
    worker = threading.Thread(target=lambda: run(client, body("t23", "질문")))
    worker.start()
    assert entered.wait(10)
    mine = client.delete("/account", headers={"Authorization": "Bearer tok-a"})
    other = client.delete("/account", headers={"Authorization": "Bearer tok-b"})
    gate.set()
    worker.join(10)
    assert mine.status_code == 409 and other.status_code == 204
    assert forgotten == ["user-b"]


def test_running_is_only_touched_while_the_guard_is_held(monkeypatch):
    # [왜] 잠금 밖의 변경은 시간이 맞아야만 드러나서(GIL) 아래의 스레드 시험은 못 잡는다. 여기서는 running의
    #      추가·삭제·순회가 일어날 때마다 잠금이 잡혀 있는지를 직접 본다 (한 번에 한 요청씩이라 결정적이다)
    from types import SimpleNamespace

    from marvia import server

    lock, ops = threading.Lock(), []

    class Watched(set):
        def add(self, item):
            ops.append(("add", lock.locked()))
            super().add(item)

        def discard(self, item):
            ops.append(("discard", lock.locked()))
            super().discard(item)

        def __iter__(self):
            ops.append(("iter", lock.locked()))
            return super().__iter__()

    # 모듈 안의 set과 threading.Lock만 바꾼다 (나머지 threading은 그대로)
    monkeypatch.setattr(server, "set", Watched, raising=False)
    monkeypatch.setattr(server, "threading", SimpleNamespace(**{**vars(threading), "Lock": lambda: lock}))
    client = TestClient(build_app(Stub(), verify, web_origin="http://x.test", forget=print))
    head = {"Authorization": "Bearer tok-a"}
    assert client.post("/agui", json=body("g1", "질문"), headers=head).status_code == 200
    assert client.delete("/account", headers=head).status_code == 204
    # [왜] 바꿔 둔 set·Lock을 앱이 실제로 썼는지 먼저 본다 (이름이 달라져 헛돌면 여기서 실패한다)
    assert {name for name, _ in ops} == {"add", "discard", "iter"}
    assert [name for name, held in ops if not held] == []


def test_deleting_an_account_while_turns_start_and_finish_never_gives_500():
    # [주의] 스레드를 겹쳐 돌리는 연기 시험이다. 잠금 밖 변경은 시간이 맞아야만 드러나서 이 시험만으로는
    #        못 잡는다(위 결정적 시험이 잡는다)
    # [왜] running 집합을 잠금 밖에서 바꾸면 DELETE /account의 순회가 "Set changed size"로 500이 될 수 있다
    forgotten: list[str] = []
    app = build_app(Stub(), verify, web_origin="http://x.test", forget=forgotten.append)
    client = TestClient(app, raise_server_exceptions=False)
    head = {"Authorization": "Bearer tok-a"}
    codes: list[int] = []

    def turns(n: int) -> None:
        for i in range(60):
            codes.append(client.post("/agui", json=body(f"h{n}-{i}", "질문"), headers=head).status_code)

    def deletes() -> None:
        for _ in range(120):
            codes.append(client.delete("/account", headers=head).status_code)

    workers = [threading.Thread(target=turns, args=(n,)) for n in range(4)] + [
        threading.Thread(target=deletes)
    ]
    [w.start() for w in workers]
    [w.join(60) for w in workers]
    assert codes and set(codes) <= {200, 204, 409}, sorted(set(codes))


def test_a_traced_turn_exports_spans_without_numbers_and_still_answers_with_them(agent_deps):
    # [왜] 서버 길도 가린 콜백을 지난다 (계획 6b). 메모리 내보내기라 키·서버·네트워크가 없다
    exporter, key = InMemorySpanExporter(), f"pk-test-{uuid4().hex}"
    tracer = langfuse_trace.build(key, "sk-test", "http://127.0.0.1:9", exporter)
    deps = agent_deps(model=ToolModel(messages=iter([AIMessage("")])))
    graph = build_main_graph(deps, InMemorySaver(), loop="agent", store=InMemoryStore())
    app = build_app(graph, verify, web_origin="http://web.test", forget=print, callbacks=[tracer])
    events = run(TestClient(app), body("t30", "DEMO0001 언제까지?"))
    client = get_client(public_key=key)
    client.flush()
    client.shutdown()
    spans = exporter.get_finished_spans()
    assert spans and all("DEMO0001" not in span.to_json() for span in spans)
    assert any("DEMO0001" in event.get("delta", "") for event in events)  # 화면 답에는 실제 번호
