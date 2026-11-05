"""에이전트 길(계획 3c) 시험. 가짜 도구 호출 모델로 키 없이 돈다."""

import anthropic
import httpx
import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from marvia.graph.main import build_main_graph
from marvia.graph.schemas import Draft
from marvia.tools.rules import load_rules

CITING = Draft(
    answer="관세법 제241조에 따라 반입일부터 30일 이내에 수입신고해야 해요.",
    citations=["L001556@20261002#제241조.3항"],
    next_options=[],
    forwarder_message="",
)

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
    """정해 둔 AIMessage를 차례로 내는 가짜 모델. bind_tools는 자기를 그대로 돌려준다."""

    def bind_tools(self, tools, **kwargs):
        return self


class BrokenModel(ToolModel):
    """부르면 API 오류를 내는 가짜 모델."""

    def _generate(self, *args, **kwargs):
        raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.test"))


def say(*calls: tuple[str, dict], text: str = "") -> AIMessage:
    """도구 호출을 담은 AIMessage. calls가 없으면 루프를 끝내는 답이다."""
    return AIMessage(
        content=text, tool_calls=[{"name": n, "args": a, "id": f"c{i}-{n}"} for i, (n, a) in enumerate(calls)]
    )


def model(*messages: AIMessage) -> ToolModel:
    return ToolModel(messages=iter(messages))


def cfg(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def agent_graph(agent_deps, *messages, store=None, permission_mode="ask", **changes):
    deps = agent_deps(model=model(*messages), **changes)
    return build_main_graph(deps, InMemorySaver(), loop="agent", store=store, permission_mode=permission_mode)


def all_text(values: dict) -> str:
    """에이전트 메시지의 글과 도구 호출 인자를 한 글로 모은다 (번호가 새는지 볼 때)."""
    parts = []
    for message in values.get("messages", []):
        parts.append(str(message.content))
        parts += [str(call["args"]) for call in getattr(message, "tool_calls", None) or []]
    return "\n".join(parts)


def test_agent_searches_then_writer_answers(agent_deps):
    graph = agent_graph(
        agent_deps, say(("search_law", {"query": "수입신고 기한"})), say(), write=lambda p: CITING
    )
    out = graph.invoke({"text": "수입신고는 언제까지 해요?"}, cfg("a1"))
    values = graph.get_state(cfg("a1")).values
    assert "관세법 > 제9장 통관 > 제241조" in out["answer"]  # 인용은 코드가 붙인다
    assert [e["unit_id"] for e in values["evidence"]] == ["L001556@20261002#제241조.3항"]
    # 모델 2 + RAG 2(질의 분석·채점) + 작성자 1
    assert values["llm_calls"] == 5


def test_agent_path_needs_a_model(agent_deps):
    with pytest.raises(ValueError, match="AgentDeps.model"):
        build_main_graph(agent_deps(), InMemorySaver(), loop="agent")


def test_parallel_searches_merge_into_one_bundle(agent_deps):
    calls = (("search_law", {"query": "수입신고 기한"}), ("search_law", {"query": "반입신고"}))
    graph = agent_graph(agent_deps, say(*calls), say(), write=lambda p: CITING)
    graph.invoke({"text": "수입신고는 언제까지 해요?"}, cfg("a2"))
    values = graph.get_state(cfg("a2")).values
    assert len(values["evidence"]) == 1  # 같은 조문은 하나로 합친다
    assert values["llm_calls"] == 2 + 4 + 1


def test_same_query_is_not_searched_twice(agent_deps, fake_rag):
    seen = []
    rag = fake_rag()
    counting = type(rag)(**{**rag.__dict__, "search": lambda q, d: seen.append(q) or rag.search(q, d)})
    query = {"query": "수입신고 기한"}
    graph = agent_graph(
        agent_deps,
        say(("search_law", query)),
        say(("search_law", query)),
        say(),
        rag=counting,
        write=lambda p: CITING,
    )
    graph.invoke({"text": "수입신고는 언제까지 해요?"}, cfg("a3"))
    assert len(seen) == 1


def test_search_failure_is_recorded_and_loop_goes_on(agent_deps, fake_rag):
    rag = fake_rag(fail=httpx.ConnectError("연결 안 됨"))
    graph = agent_graph(agent_deps, say(("search_law", {"query": "수입신고 기한"})), say(), rag=rag)
    out = graph.invoke({"text": "수입신고는 언제까지 해요?"}, cfg("a4"))
    values = graph.get_state(cfg("a4")).values
    assert values["failed_tools"] == [{"tool": "search_law", "message": "ConnectError"}]
    assert "시험 답이에요." in out["answer"]


def test_deadlines_come_from_code_and_numbers_stay_masked(agent_deps):
    graph = agent_graph(agent_deps, say(("calc_deadlines", {})), say())
    out = graph.invoke({"text": "DEMO0001 언제까지 수입신고 해야 해요?"}, cfg("a5"))
    values = graph.get_state(cfg("a5")).values
    assert values["calc"]["deadlines"][0]["name"] == "수입신고 기한"
    assert "DEMO0001" not in all_text(values)  # 모델이 본 글과 도구 인자에는 토큰만 있다
    assert "DEMO0001" in out["answer"]  # 화면에 보낼 때만 되돌린다


def test_reimport_facts_go_straight_to_the_code_check(agent_deps):
    graph = agent_graph(agent_deps, say(("check_reimport", {"facts": CHILI})), say())
    graph.invoke({"text": "건고추를 다시 들여와요"}, cfg("a6"))
    values = graph.get_state(cfg("a6")).values
    assert values["calc"]["reimport"]["verdict"] == "서류검사 요건 충족"
    assert values["item"]["category"] == "농산물·임산물"


def test_two_reimport_checks_in_one_step_do_not_crash(agent_deps):
    # [왜] 병렬로 부른 두 도구가 같은 칸(item)에 쓰면 reducer가 있어야 한다
    other = CHILI | {"prior_precise": "안 받음"}
    graph = agent_graph(
        agent_deps, say(("check_reimport", {"facts": CHILI}), ("check_reimport", {"facts": other})), say()
    )
    graph.invoke({"text": "건고추 두 가지를 다시 들여와요"}, cfg("a6b"))
    values = graph.get_state(cfg("a6b")).values
    assert values["item"]["prior_precise"] in ("받음", "안 받음")


def test_lookup_cargo_tool_uses_tokens_only(agent_deps):
    # DEMO0001은 B/L 모양이라 토큰이 [BL1]이다
    graph = agent_graph(agent_deps, say(("lookup_cargo", {"tokens": ["[BL1]", "[BL9]"]})), say())
    graph.invoke({"text": "DEMO0001 다시 봐 줘"}, cfg("a7"))
    values = graph.get_state(cfg("a7")).values
    tool_text = [m.content for m in values["messages"] if m.type == "tool"][0]
    assert "[BL9]: 모르는 토큰이에요" in tool_text and "DEMO0001" not in tool_text
    assert "[BL1]: 반입신고" in tool_text
    assert [c["token"] for c in values["cargos"]] == ["[BL1]"]  # 같은 토큰은 바꾸고 늘리지 않는다


def test_llm_cap_is_kept_exactly_and_ends_in_partial_answer(agent_deps, fake_rag):
    seen = []
    rag = fake_rag()
    counting = type(rag)(**{**rag.__dict__, "search": lambda q, d: seen.append(q) or rag.search(q, d)})
    # [왜] 늘 새 질의로 검색하는 모델: 검색 상한과 LLM 호출 상한이 모두 닿는다
    endless = [say(("search_law", {"query": f"질의 {i}"})) for i in range(40)]
    graph = agent_graph(agent_deps, *endless, rag=counting)
    out = graph.invoke({"text": "수입신고는 언제까지 해요?"}, cfg("a8"))
    values = graph.get_state(cfg("a8")).values
    cap = load_rules("agent")["loop"]["max_llm_calls"]
    assert len(seen) == load_rules("agent")["loop"]["max_searches"]
    assert values["llm_calls"] == cap  # 상한을 넘지 않는다
    assert values["stopped"] == "llm_calls"
    assert "끝까지 확인하지 못했어요" in out["answer"] and f"LLM 호출 한도({cap}회)" in out["answer"]


def test_search_is_refused_when_the_budget_would_pass_the_cap(agent_deps, fake_rag):
    seen = []
    rag = fake_rag(sufficient=False)
    counting = type(rag)(**{**rag.__dict__, "search": lambda q, d: seen.append(q) or rag.search(q, d)})
    endless = [say(("search_law", {"query": f"질의 {i}"})) for i in range(40)]
    graph = agent_graph(agent_deps, *endless, rag=counting)
    graph.invoke({"text": "수입신고는 언제까지 해요?"}, cfg("a8b"))
    values = graph.get_state(cfg("a8b")).values
    cap = load_rules("agent")["loop"]["max_llm_calls"]
    # [왜] 검색 한 번의 최악은 2 + 2 × max_rewrites(=2)로 6. 두 번은 상한 안, 세 번째는 넘어서 거절된다
    # [주의] seen은 RAG 안 검색 호출 수(고쳐 쓰기 포함)다.
    #        한 번 찾기 = 초기 검색 + 고쳐 쓴 검색 2번이라 6 = 두 번 찾기
    assert len(seen) == 3 * 2
    assert values["llm_calls"] == cap
    assert any("LLM 호출 한도가 가까워" in str(m.content) for m in values["messages"] if m.type == "tool")


def test_parallel_searches_never_pass_the_cap(agent_deps, fake_rag):
    rag = fake_rag(sufficient=False)
    calls = tuple(("search_law", {"query": f"병렬 질의 {i}"}) for i in range(5))
    graph = agent_graph(agent_deps, say(*calls), say(), rag=rag)
    graph.invoke({"text": "수입신고는 언제까지 해요?"}, cfg("a8c"))
    values = graph.get_state(cfg("a8c")).values
    cap = load_rules("agent")["loop"]["max_llm_calls"]
    assert values["llm_calls"] <= cap


def test_llm_failure_in_loop_gives_partial_answer(agent_deps):
    deps = agent_deps(model=BrokenModel(messages=iter([])))
    graph = build_main_graph(deps, InMemorySaver(), loop="agent")
    out = graph.invoke({"text": "수입신고는 언제까지 해요?"}, cfg("a9"))
    assert "- agent: APIConnectionError" in out["answer"]
    assert graph.get_state(cfg("a9")).values["stopped"] == "llm_failed"


def test_todo_list_keeps_one_in_progress_and_ends_completed(agent_deps):
    bad = {
        "todos": [
            {"content": "기한 계산", "status": "in_progress"},
            {"content": "조문 찾기", "status": "in_progress"},
        ]
    }
    good = {
        "todos": [
            {"content": "기한 계산", "status": "in_progress"},
            {"content": "조문 찾기", "status": "pending"},
        ]
    }
    graph = agent_graph(agent_deps, say(("write_todos", bad)), say(("write_todos", good)), say())
    graph.invoke({"text": "DEMO0001 언제까지 신고해요?"}, cfg("a10"))
    values = graph.get_state(cfg("a10")).values
    errors = [m for m in values["messages"] if m.type == "tool" and m.status == "error"]
    assert len(errors) == 1  # 진행 중이 둘인 목록은 오류로 돌려준다
    assert [t["status"] for t in values["todos"]] == [
        "completed",
        "pending",
    ]  # 답이 나오면 진행 중은 끝낸다


def test_todo_updates_are_streamed(agent_deps):
    todos = {"todos": [{"content": "기한 계산", "status": "in_progress"}]}
    graph = agent_graph(agent_deps, say(("write_todos", todos)), say())
    # [왜] subgraphs=True: 루프(서브그래프) 안의 갱신도 (이름표, 갱신)으로 흘려보낸다.
    #      화면은 이 갱신으로 할 일 목록을 그린다. start 노드의 빈 todos와 섞이지 않게 루프 안의 갱신만 본다
    stream = graph.stream({"text": "DEMO0001 언제?"}, cfg("a11"), stream_mode="updates", subgraphs=True)
    inside = [update for ns, chunk in stream if ns for update in chunk.values() if update]
    assert any(update.get("todos") == todos["todos"] for update in inside)
