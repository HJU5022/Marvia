"""메인 그래프: 사용자 메시지가 처음 들어가는 가장 바깥 순서도 (설계 6절).

순서도: START → start → identify(서브그래프) → (질문 있으면 ask → lookup) → plan
        plan → (진행 중인 할 일) search_law | extract_item | calc → plan ... / 할 일 없음·write → write
        → verify → 위반 없음: respond / 위반·횟수 남음: write / 그 밖: finish → END
        LLM 호출 수·남은 단계가 한도에 닿거나 LLM이 실패하면 plan·write 다음에 finish (설계 6.4)
에이전트 길(loop="agent", 계획 3c): identify 다음 brief → agent(도구 루프, graph/agent.py)
        → 멈춤: finish / 도메인 밖: decline / 그 밖: write → verify → respond | finish
        (작성·검증은 계획자 길과 같다)
하지 않는 일: 노드 재시도(LLM은 SDK가 재시도한다), 차례를 넘는 대화 기록·장기 기억 읽기(계획 3d).
LLM·RAG는 AgentDeps로 받는다. 테스트는 가짜 함수·가짜 모델을 넣어 키 없이 돈다.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import httpx
import psycopg
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, RemoveMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.types import interrupt

from marvia.graph.agent import build_agent
from marvia.graph.answer import cargo_lines, decline_answer, final_answer, partial_answer
from marvia.graph.identify import build_identify_graph, lookup
from marvia.graph.rag import RagDeps, build_rag_graph, evidence_block
from marvia.graph.schemas import Draft, Plan
from marvia.graph.state import MarviaState, merge_evidence
from marvia.graph.tools import cargo_deadlines, error_name, make_tools
from marvia.graph.verify import verify
from marvia.identify.mask import unmask
from marvia.identify.parse import read_numbers
from marvia.llm import LLMFailed
from marvia.prompts import render
from marvia.tools.reimport import ItemFacts, reimport_check
from marvia.tools.rules import load_rules


# [왜] 바깥 기능(LLM·RAG)을 함수로 받아 둔다. RagDeps와 같은 방식이다
@dataclass(frozen=True)
class AgentDeps:
    """메인 그래프가 쓰는 바깥 기능 묶음. 실제 값은 marvia.graph.live.agent_deps가 만든다(Task 8)."""

    rag: RagDeps  # RAG 서브그래프의 바깥 기능 (계획 2)
    plan: Callable[[str], Plan]  # 프롬프트 → 남은 할 일
    item: Callable[[str], ItemFacts]  # 프롬프트 → 사용자가 말한 품목 사실
    write: Callable[[str], Draft]  # 프롬프트 → 답 초안
    today: Callable[[], date] = date.today  # [왜] 함수로 받아야 테스트가 날짜를 고정할 수 있다
    model: BaseChatModel | None = None  # 에이전트 길의 도구 호출 모델 (계획 3c). 계획자 길은 쓰지 않는다


def start(state: MarviaState) -> dict:
    """새 차례를 시작한다. 같은 대화(thread)의 지난 차례 근거·초안·횟수를 비운다."""
    # [왜] checkpointer는 thread마다 공책을 이어 쓴다. 비우지 않으면 지난 질문의 근거와 초안이 섞인다
    return {
        # [왜] 지난 차례 답(실제 번호를 되돌린 글)이 이번 차례가 멈췄을 때 결과에 남지 않게 비운다
        "answer": "",
        "plan": [],
        "evidence": [],
        "gaps": [],
        "item": {},
        "calc": {},
        "draft": {},
        "verification": [],
        "write_attempts": 0,
        "llm_calls": 0,
        "failed_tools": [],
        # 에이전트 길 칸 (계획 3c)
        # [왜] REMOVE_ALL_MESSAGES: 지난 차례 메시지를 모두 지운다. 차례를 넘는 기억은 계획 3d
        "messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES)],
        "todos": [],
        "assumptions": [],
        "stopped": "",
        "out_of_scope": False,
    }


def ask(state: MarviaState) -> dict:
    """사용자에게 선택지를 묻고, 답으로 조회할 번호를 정한다 (설계 6.3)."""
    question = state.get("question") or {}
    # [주의] 재개하면 이 노드가 처음부터 다시 돈다. 그래서 interrupt 앞에는 외부 조회 같은 일을 두지 않는다
    # [왜] 화면에 보낼 칸만 고른다. alternatives에는 실제 번호가 들어 있다
    reply = interrupt({k: question[k] for k in ("kind", "question", "options", "recommended")}) or {}
    # 처음 실행: 위 줄에서 멈춘다. 재개: interrupt()가 사용자의 답(Command의 resume 값)을 돌려준다
    if reply.get("custom"):
        # 사용자가 선택지 대신 직접 번호를 적은 경우. 같은 번호 읽기 규칙으로 읽는다
        chosen = [n.value for _, r in read_numbers(reply["custom"]) for n in r.numbers]
    else:
        # 선택지 번호를 골랐거나 아무것도 안 골랐으면 권장안
        chosen = question["alternatives"][reply.get("selected", question["recommended"])]
    return {"numbers": state.get("numbers", []) + chosen, "question": None}


# 실패하면 이번 차례를 부분 답으로 끝내는 LLM 노드
LLM_NODES = ("plan", "extract_item", "write")


def _failure(state: MarviaState, tool: str, error: Exception) -> dict:
    """실패한 도구를 failed_tools에 더한 칸. 오류 종류 이름만 남긴다."""
    # [주의] 오류 글은 넣지 않는다. 접속 주소나 요청 글이 섞일 수 있다 (error_name)
    return {"failed_tools": state.get("failed_tools", []) + [{"tool": tool, "message": error_name(error)}]}


def _llm_failed(state: MarviaState) -> bool:
    """이번 차례에 계획자·품목 사실·작성자 LLM이 실패했나."""
    return any(t["tool"] in LLM_NODES for t in state.get("failed_tools", []))


def _current_step(state: MarviaState) -> dict | None:
    """진행 중인 할 일. 없으면 None."""
    return next((step for step in state.get("plan", []) if step["status"] == "in_progress"), None)


def respond(state: MarviaState) -> dict:
    """검증을 통과한 초안으로 답을 만들고, 화면에 보내기 직전에 실제 번호로 되돌린다."""
    text = final_answer(
        state.get("draft", {}),
        state.get("cargos", []),
        state.get("evidence", []),
        state.get("assumptions", []),
    )
    # [왜] 답이 나왔으면 진행 중이던 할 일은 끝난 것이다. 화면에 진행 중 표시가 남지 않게 한다
    todos = [
        todo | {"status": "completed"} if todo["status"] == "in_progress" else todo
        for todo in state.get("todos", [])
    ]
    return {"answer": unmask(text, state.get("mask_map", {})), "todos": todos}


def finish(state: MarviaState) -> dict:
    """부분 답을 낸다 (설계 6.4). 검증을 넘지 못한 초안은 쓰지 않는다."""
    # [왜] 멈춘 차례에는 끝나지 않은 일을 진행 중으로 남기지 않는다. 끝낸 것이 아니라 pending으로 돌린다
    todos = [
        todo | {"status": "pending"} if todo["status"] == "in_progress" else todo
        for todo in state.get("todos", [])
    ]
    text = partial_answer(
        state.get("cargos", []),
        state.get("calc", {}),
        state.get("evidence", []),
        state.get("gaps", []),
        state.get("failed_tools", []),
        state.get("assumptions", []),
    )
    return {"answer": unmask(text, state.get("mask_map", {})), "todos": todos}


def decline(state: MarviaState) -> dict:
    """도메인 밖 질문: 코드가 쓴 정중한 거절과 할 수 있는 일을 답으로 낸다 (설계 1절)."""
    return {"answer": decline_answer()}


def _after_agent(state: MarviaState) -> str:
    """갈림길: 멈췄으면 finish, 도메인 밖이고 모은 것이 없으면 decline, 아니면 write."""
    if state.get("stopped"):
        return "finish"
    # [왜] 도메인 안 질문이 섞여 근거·계산을 모았으면 거절하지 않고 답한다(애매하면 답하는 쪽)
    if state.get("out_of_scope") and not state.get("evidence") and not state.get("calc"):
        return "decline"
    return "write"


def build_main_graph(
    deps: AgentDeps, checkpointer=None, *, loop: str = "planner", store=None, permission_mode: str = "ask"
):
    """메인 순서도를 조립한다. checkpointer가 있어야 interrupt로 멈췄다가 이어 갈 수 있다.

    loop: "planner"(계획 3a의 고정 계획자) 또는 "agent"(계획 3c의 도구 루프).
    store: 장기 기억 저장소(LangGraph Store).
    permission_mode: "ask"면 저장 같은 부작용 앞에서 승인을 받고,
    "auto"면 always_ask 도구만 묻는다 (설계 6.3).
    """
    cfg = load_rules("agent")
    rag_graph = build_rag_graph(deps.rag)  # [왜] 한 번만 만들고 search_law가 부를 때마다 다시 쓴다

    def plan(state: MarviaState) -> dict:
        """계획자: 지금까지 한 일과 모은 것을 보고 남은 할 일을 다시 정한다 (설계 6.1)."""
        if _llm_failed(state):
            return {}  # [왜] 품목 사실 LLM이 이미 실패했다. 계획자를 또 부르지 않고 route가 finish로 보낸다
        # [왜] 방금 끝난 일(in_progress)은 done으로 남기고 아직 안 한 일(pending)은 버린다.
        #      남은 일은 계획자가 새로 낸다
        done = [step | {"status": "done"} for step in state.get("plan", []) if step["status"] != "pending"]
        prompt = render(
            "plan",
            today=deps.today().isoformat(),
            question=state.get("masked_text", ""),
            cargos="\n".join(cargo_lines(state.get("cargos", []))),
            # [왜] 계획자에게는 근거 본문 대신 unit_id와 제목만 준다. 무엇을 이미 찾았는지만 알면 된다
            evidence="\n".join(f"[{e['unit_id']}] {e['heading']}" for e in state.get("evidence", [])),
            gaps="\n".join(state.get("gaps", [])),
            calc=json.dumps(state.get("calc", {}), ensure_ascii=False),
            item=json.dumps(state.get("item", {}), ensure_ascii=False),
            done="\n".join(f"{step['action']}: {step['query']}" for step in done),
            failed="\n".join(f"{t['tool']}: {t['message']}" for t in state.get("failed_tools", [])),
        )
        try:
            new = deps.plan(prompt)
        except LLMFailed as error:
            return {"plan": done, **_failure(state, "plan", error)}
        steps = [step.model_dump() | {"status": "pending"} for step in new.steps]
        if steps:
            steps[0]["status"] = "in_progress"  # [왜] 진행 중은 한 번에 하나 (설계 6.2)
        return {"plan": done + steps, "llm_calls": state.get("llm_calls", 0) + 1}

    def route(state: MarviaState) -> str:
        """갈림길: 한도에 닿았거나 LLM이 실패했으면 finish. 아니면 진행 중인 할 일 노드, 없으면 write."""
        loop = cfg["loop"]
        if (
            _llm_failed(state)
            or state.get("llm_calls", 0) >= loop["max_llm_calls"]
            # [왜] 남은 단계가 모자라면 GraphRecursionError로 멈추기 전에 부분 답으로 간다 (설계 6.4)
            or state.get("remaining_steps", loop["min_remaining_steps"]) < loop["min_remaining_steps"]
        ):
            return "finish"
        step = _current_step(state)
        return step["action"] if step else "write"

    def search_law(state: MarviaState) -> dict:
        """법령 검색: 진행 중인 할 일의 질의로 RAG 서브그래프를 돌려 근거를 모은다 (설계 5.4)."""
        step = _current_step(state) or {}
        query = step.get("query") or state.get("masked_text", "")  # 질의가 비었으면 가린 질문 그대로
        # [왜] RAG 공책(RagState)은 메인 공책과 칸이 달라 노드 안에서 따로 부른다 (LangGraph 문서의 방식)
        try:
            out = rag_graph.invoke({"question": query, "as_of": deps.today()})
        except (httpx.HTTPError, psycopg.Error, LLMFailed) as error:
            # [왜] 검색 실패(Voyage·DB·RAG 안의 LLM)는 차례 전체를 멈추지 않는다.
            #      기록만 하고 계획자가 다음 길을 고른다 (설계 결정 4의 ①)
            # [왜] RAG는 늘 질의 분석 LLM부터 부른다. 어디서 실패했든 그 호출 하나는 일어났다
            return {**_failure(state, "search_law", error), "llm_calls": state.get("llm_calls", 0) + 1}
        missing = "" if out.get("sufficient") else out.get("missing", "")
        gaps = state.get("gaps", []) + ([missing] if missing else [])  # [왜] 빈 문장은 남기지 않는다
        return {
            "evidence": merge_evidence(
                state.get("evidence", []), out.get("evidence", []), cfg["answer"]["max_evidence"]
            ),
            "gaps": gaps,
            # [왜] 질의 분석 1 + 채점 (고쳐 쓰기 + 1) + 고쳐 쓰기 = 2 + 2 × 고쳐 쓰기.
            #      검색 결과가 비면 채점을 건너뛰어 실제로는 더 적다. 상한으로 세어 호출 수 한도에만 쓴다
            "llm_calls": state.get("llm_calls", 0) + 2 + 2 * out.get("rewrites", 0),
        }

    def extract_item(state: MarviaState) -> dict:
        """품목 사실: 사용자가 말한 재수입 품목 사실을 정해진 모양으로 뽑는다 (reimport_check의 입력)."""
        prompt = render(
            "item_facts",
            question=state.get("masked_text", ""),
            # [왜] 사유 이름만으로는 뜻이 모자라다(수입 최소량이 몇 kg인지 등). yaml 이름표를 함께 준다
            flags="\n".join(f"- {flag}: {item}" for flag, item in load_rules("reimport")["forced"].items()),
        )
        try:
            facts = deps.item(prompt)
        except LLMFailed as error:
            return _failure(state, "extract_item", error)
        return {"item": facts.model_dump(mode="json"), "llm_calls": state.get("llm_calls", 0) + 1}

    def calc(state: MarviaState) -> dict:
        """계산: 화물 단계로 기한을, 품목 사실로 재수입 검사 판정을 낸다 (설계 7.1). LLM은 부르지 않는다."""
        today = deps.today()
        result: dict = {"deadlines": cargo_deadlines(state.get("cargos", []), today)}
        item = state.get("item")
        if item:
            result["reimport"] = reimport_check(ItemFacts.model_validate(item), today).model_dump(mode="json")
        return {"calc": result}

    def write(state: MarviaState) -> dict:
        """작성자: 가린 질문·화물 줄·계산·근거로 답 초안을 쓴다. 지난 위반이 있으면 함께 넘긴다."""
        prompt = render(
            "write",
            today=deps.today().isoformat(),
            # [주의] 원문(text)이 아니라 가린 글만 넘긴다. 실제 번호는 LLM에 가지 않는다
            question=state.get("masked_text", ""),
            cargos="\n".join(cargo_lines(state.get("cargos", []))),
            # [왜] ensure_ascii=False: 한글을 \uXXXX로 바꾸지 않아야 LLM이 읽는다
            calc=json.dumps(state.get("calc", {}), ensure_ascii=False),
            evidence=evidence_block(state.get("evidence", [])),
            gaps="\n".join(state.get("gaps", [])),
            violations="\n".join(state.get("verification", [])),
        )
        try:
            draft = deps.write(prompt)
        except LLMFailed as error:
            return _failure(state, "write", error)
        return {
            "draft": draft.model_dump(),
            "write_attempts": state.get("write_attempts", 0) + 1,
            "llm_calls": state.get("llm_calls", 0) + 1,
        }

    def check(state: MarviaState) -> dict:
        """검증자: 초안을 코드 규칙으로 검사한다."""
        violations = verify(
            Draft.model_validate(state.get("draft", {})),
            state.get("evidence", []),
            state.get("calc", {}),
            state.get("cargos", []),
            state.get("mask_map", {}),
            deps.today(),
        )
        return {"verification": violations}

    def after_write(state: MarviaState) -> str:
        """갈림길: 작성자 LLM이 실패했으면 finish, 아니면 verify."""
        return "finish" if _llm_failed(state) else "verify"

    def brief(state: MarviaState) -> dict:
        """에이전트 길: 이번 차례 질문(가린 글)과 화물 줄을 루프의 첫 메시지로 만든다."""
        text = render(
            "agent_turn",
            today=deps.today().isoformat(),
            cargos="\n".join(cargo_lines(state.get("cargos", []))),
            question=state.get("masked_text", ""),
        )
        return {"messages": [HumanMessage(text)]}

    def after_verify(state: MarviaState) -> str:
        """갈림길: 통과면 respond, 위반인데 횟수가 남았으면 write, 아니면 finish."""
        if not state.get("verification"):
            return "respond"
        if state.get("write_attempts", 0) < cfg["answer"]["max_write_attempts"]:
            return "write"
        return "finish"

    graph = StateGraph(MarviaState)
    graph.add_node("start", start)
    # [왜] 컴파일한 서브그래프도 노드 하나처럼 넣을 수 있다. 공책 칸 이름이 같아서 그대로 주고받는다
    graph.add_node("identify", build_identify_graph())
    graph.add_node("ask", ask)
    graph.add_node("lookup", lookup)  # 식별 서브그래프의 조회 노드를 다시 쓴다
    graph.add_node("write", write)
    graph.add_node("verify", check)
    graph.add_node("respond", respond)
    graph.add_node("finish", finish)
    graph.add_edge(START, "start")
    graph.add_edge("start", "identify")
    # [왜] 식별 뒤 첫 일: 계획자 길은 plan, 에이전트 길은 brief
    first = "brief" if loop == "agent" else "plan"
    graph.add_conditional_edges(
        "identify", lambda state: "ask" if state.get("question") else first, ["ask", first]
    )
    graph.add_edge("ask", "lookup")
    graph.add_edge("lookup", first)
    if loop == "agent":
        if deps.model is None:
            raise ValueError("에이전트 길에는 AgentDeps.model(도구 호출 모델)이 있어야 합니다")
        agent = build_agent(deps.model, make_tools(rag_graph, deps.today), permission_mode)
        graph.add_node("brief", brief)
        graph.add_node(
            "agent", agent
        )  # [왜] create_agent가 만든 그래프도 서브그래프 노드다. 같은 이름 칸을 주고받는다
        graph.add_node("decline", decline)
        graph.add_edge("brief", "agent")
        graph.add_conditional_edges("agent", _after_agent, ["write", "decline", "finish"])
        graph.add_edge("decline", END)
    else:
        graph.add_node("plan", plan)
        graph.add_node("search_law", search_law)
        graph.add_node("extract_item", extract_item)
        graph.add_node("calc", calc)
        # [왜] 셋째 인자에 갈 수 있는 곳을 모두 적는다. 그림(get_graph)에 화살표가 빠지지 않는다
        graph.add_conditional_edges("plan", route, ["search_law", "extract_item", "calc", "write", "finish"])
        # [왜] 한 일을 보고 계획자가 다시 정한다. 이 세 화살표가 계획자 루프다
        graph.add_edge("search_law", "plan")
        graph.add_edge("extract_item", "plan")
        graph.add_edge("calc", "plan")
    graph.add_conditional_edges("write", after_write, ["verify", "finish"])
    graph.add_conditional_edges("verify", after_verify, ["respond", "write", "finish"])
    graph.add_edge("respond", END)
    graph.add_edge("finish", END)
    # [왜] with_config로 그래프에 recursion_limit을 붙여 둔다. invoke 때 config를 넘기면 그 값이 이긴다
    limit = cfg["loop"]["agent_recursion_limit" if loop == "agent" else "recursion_limit"]
    return graph.compile(checkpointer=checkpointer, store=store).with_config(recursion_limit=limit)
