"""메인 그래프: 사용자 메시지가 처음 들어가는 가장 바깥 순서도 (설계 6절).

순서도: START → start → identify(서브그래프) → (질문 있으면 ask → lookup) → plan
        plan → (진행 중인 할 일) search_law | extract_item | calc → plan ... / 할 일 없음·write → write
        → verify → 위반 없음: respond / 위반·횟수 남음: write / 그 밖: finish → END
        LLM 호출 수·남은 단계가 한도에 닿거나 LLM이 실패하면 plan·write 다음에 finish (설계 6.4)
에이전트 길(loop="agent", 계획 3c): identify 다음 brief → agent(도구 루프, graph/agent.py)
        → 멈춤: finish / 도메인 밖: decline / 그 밖: write → verify → respond | finish
        (작성·검증은 계획자 길과 같다)
수퍼바이저 길(loop="supervisor", 계획 7b): identify 다음 brief → supervisor(graph/supervisor.py) → router
        → 넘길 곳이 있으면 그 서브에이전트(cargo | law | item) → supervisor ...
        → 없으면 에이전트 길과 같은 갈림길(finish / decline / write)
        에이전트 길의 대화 기록(messages)은 차례를 넘어 이어지고, 답(가린 글)이 기록 끝에 붙는다 (계획 3d).
        기록이 길면 brief가 앞부분을 요약하고, 요약 LLM이 실패하면 brief 다음에 finish
하지 않는 일: 노드 재시도(LLM은 SDK가 재시도한다).
LLM·RAG는 AgentDeps로 받는다. 테스트는 가짜 함수·가짜 모델을 넣어 키 없이 돈다.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import date

import httpx
import psycopg
from langchain.agents import AgentState
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt

from marvia.graph.agent import MODEL_ERRORS, build_agent, build_summary
from marvia.graph.answer import cargo_lines, decline_answer, final_answer, partial_answer, with_news
from marvia.graph.identify import build_identify_graph, build_lookup_graph
from marvia.graph.rag import RagDeps, build_rag_graph, evidence_block
from marvia.graph.schemas import Draft, Plan
from marvia.graph.state import MarviaState, merge_evidence
from marvia.graph.supervisor import build_sub, build_supervisor, refused_handoff, sub_node, subagents
from marvia.graph.tools import (
    cargo_deadlines,
    error_name,
    flag_labels,
    make_tools,
    search_calls,
    user_of,
    watched,
    worst_search_calls,
)
from marvia.graph.verify import verify
from marvia.identify.mask import token_for, unmask
from marvia.identify.parse import kind_of, read_numbers
from marvia.llm import LLMFailed
from marvia.prompts import render
from marvia.rag.models import Evidence, SearchFailed
from marvia.tools.reimport import ItemFacts, reimport_check
from marvia.tools.rules import load_rules
from marvia.watch import WatchDeps


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
    # 조문 이름표 → 코퍼스 단위 (LLM 없는 직접 조회, 에이전트 길의 get_provision). 없으면 그 도구도 없다
    provision: Callable[[str, date], list[Evidence]] | None = None
    # 공식 사이트 조회용 HTTP 클라이언트 (에이전트 길의 official_lookup, 계획 3d). 없으면 그 도구도 없다
    web: httpx.Client | None = None
    watch: WatchDeps | None = None  # 감시 목록 (에이전트 길의 watch_cargo, 계획 3d). 없으면 그 도구도 없다


def start(state: MarviaState) -> dict:
    """새 차례를 시작한다. 같은 대화(thread)의 지난 차례 근거·초안·횟수를 비운다."""
    # [왜] checkpointer는 thread마다 공책을 이어 쓴다. 비우지 않으면 지난 질문의 근거와 초안이 섞인다
    # [주의] 대화 기록(messages)과 가림 표(mask_map)는 비우지 않는다. 차례를 넘는 기억이다 (계획 3d)
    return {
        # [왜] answer는 저장하지 않는 칸이지만, 같은 실행 안에서 이전 값이 이번 결과에 섞이지 않게 비운다
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
        "todos": [],
        "assumptions": [],
        "stopped": "",
        "out_of_scope": False,
        "clarifications": [],
        "official": [],
        # [왜] 지난 차례에 답이 나오지 않아 표시하지 못한 변화는 news 노드가 DB에서 다시 꺼낸다
        "watch_news": [],
        "watch_ids": [],
        "actions": [],
        # 수퍼바이저 길 칸 (계획 7b)
        "route": "",
        "task": "",
        "searched": [],
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
LOOPS = ("planner", "agent", "supervisor")  # MARVIA_LOOP가 받는 이름
# 도구 루프로 도는 길. 대화 기록, 감시 변화, 넉넉한 단계 상한을 함께 쓴다
LOOP_PATHS = ("agent", "supervisor")
# 요약 미들웨어가 요약 글 앞에 붙이는 글 (summarization.py _build_new_messages). brief가 뗀다
SUMMARY_LEAD = "Here is a summary of the conversation to date:\n\n"


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


def _remember(state: MarviaState, text: str) -> dict:
    """에이전트 길이면 이번 차례 답(가린 글)을 대화 기록 끝에 더한다. 다음 차례 모델이 앞의 답을 읽는다."""
    # [왜] 기록은 에이전트 길에만 있다(brief가 차례의 첫 메시지를 넣는다). 계획자 길은 메시지를 쓰지 않는다
    # [주의] 화면에 보낼 글(실제 번호)이 아니라 가린 글을 넣는다. 기록은 다음 차례 LLM에 간다
    # [주의] 부르는 쪽은 바깥 데이터 묶음(화물 줄, 감시 변화, 공식 출처)을 뺀 글을 넘긴다. 그 값은
    #        그 차례의 brief 메시지(<cargo_lines>·<watch_news>)와 official_lookup 결과(<official_source>)에
    #        태그 안으로 이미 있다. "이번 차례에 한 일"은 남긴다. 코드가 쓴 글과 토큰·검사한 값뿐이고,
    #        모르면 다음 차례 모델이 같은 일을 또 하거나 한 일과 반대로 말한다
    return {"messages": [AIMessage(text)]} if state.get("messages") else {}


def respond(state: MarviaState) -> dict:
    """검증을 통과한 초안으로 답을 만들고, 화면에 보내기 직전에 실제 번호로 되돌린다."""
    draft, evidence = state.get("draft", {}), state.get("evidence", [])
    assumptions, actions = state.get("assumptions", []), state.get("actions", [])
    cargos, official = state.get("cargos", []), state.get("official", [])
    body = final_answer(draft, cargos, evidence, assumptions, official, actions)
    text = with_news(state.get("watch_news", []), body)
    kept = final_answer(draft, [], evidence, assumptions, (), actions)  # 기록용: 바깥 데이터 묶음을 뺀 답
    # [왜] 답이 나왔으면 진행 중이던 할 일은 끝난 것이다. 화면에 진행 중 표시가 남지 않게 한다
    todos = [
        todo | {"status": "completed"} if todo["status"] == "in_progress" else todo
        for todo in state.get("todos", [])
    ]
    return {"answer": unmask(text, state.get("mask_map", {})), "todos": todos, **_remember(state, kept)}


def finish(state: MarviaState) -> dict:
    """부분 답을 낸다 (설계 6.4). 검증을 넘지 못한 초안은 쓰지 않는다."""
    todos = _pending_todos(state)
    # 화면 답과 기록용 답이 함께 쓰는 칸: 계산, 근거, 빠진 근거, 실패한 도구, 가정
    shared = (
        state.get("calc", {}),
        state.get("evidence", []),
        state.get("gaps", []),
        state.get("failed_tools", []),
        state.get("assumptions", []),
    )
    # [왜] 승인한 감시를 넣은 뒤 한도에 걸려도 한 일은 보인다
    actions = state.get("actions", [])
    body = partial_answer(state.get("cargos", []), *shared, state.get("official", []), actions)
    text = with_news(state.get("watch_news", []), body)
    kept = partial_answer([], *shared, (), actions)  # 기록용: 바깥 데이터 묶음을 뺀 부분 답
    return {"answer": unmask(text, state.get("mask_map", {})), "todos": todos, **_remember(state, kept)}


def _pending_todos(state: MarviaState) -> list[dict]:
    """멈춘 차례에 끝나지 않은 일을 진행 중으로 남기지 않는다. 끝낸 것이 아니라 pending으로 돌린다."""
    return [
        todo | {"status": "pending"} if todo["status"] == "in_progress" else todo
        for todo in state.get("todos", [])
    ]


def decline(state: MarviaState) -> dict:
    """도메인 밖 질문: 코드가 쓴 정중한 거절과 할 수 있는 일을 답으로 낸다 (설계 1절)."""
    text = with_news(state.get("watch_news", []), decline_answer())
    answer = unmask(text, state.get("mask_map", {}))
    # [왜] 기록에는 감시 변화를 뺀 거절 글만 둔다 (_remember)
    return {"answer": answer, "todos": _pending_todos(state), **_remember(state, decline_answer())}


def _after_agent(state: MarviaState) -> str:
    """갈림길: 멈췄으면 finish, 도메인 밖이고 모은 것이 없으면 decline, 아니면 write."""
    if state.get("stopped"):
        return "finish"
    # [왜] 도메인 안 질문이 섞여 근거·계산을 모았으면 거절하지 않고 답한다(애매하면 답하는 쪽)
    gathered = state.get("evidence") or any(state.get("calc", {}).values())
    if state.get("out_of_scope") and not gathered:
        return "decline"
    # [왜] 검색이 모두 실패해 모은 것이 없으면 작성자를 부르지 않는다. 근거 없는 답 대신
    #      실패한 도구를 보인 부분 답으로 간다 (두 길 비교에서 근거 없는 완전한 답이 나왔다)
    if not gathered and state.get("failed_tools"):
        return "finish"
    return "write"


def build_main_graph(
    deps: AgentDeps, checkpointer=None, *, loop: str = "planner", store=None, permission_mode: str = "ask"
):
    """메인 순서도를 조립한다. checkpointer가 있어야 interrupt로 멈췄다가 이어 갈 수 있다.

    loop: "planner"(계획 3a의 고정 계획자), "agent"(계획 3c의 도구 루프), "supervisor"(계획 7b).
    store: 장기 기억 저장소(LangGraph Store).
    permission_mode: "ask"면 저장 같은 부작용 앞에서 승인을 받고,
    "auto"면 always_ask 도구만 묻는다 (설계 6.3).
    """
    if loop not in LOOPS:
        # [왜] 모르는 이름이 조용히 계획자 길로 떨어지면 다른 길을 돌린 줄 모른다
        raise ValueError(f"loop는 {', '.join(LOOPS)} 가운데 하나여야 합니다: {loop!r}")
    cfg = load_rules("agent")
    rag_graph = build_rag_graph(deps.rag)  # [왜] 한 번만 만들고 search_law가 부를 때마다 다시 쓴다

    def plan(state: MarviaState) -> dict:
        """계획자: 지금까지 한 일과 모은 것을 보고 남은 할 일을 다시 정한다 (설계 6.1)."""
        if _llm_failed(state):
            return {}  # [왜] 품목 사실 LLM이 이미 실패했다. 계획자를 또 부르지 않고 route가 finish로 보낸다
        if state.get("llm_calls", 0) >= cfg["loop"]["max_llm_calls"]:
            # [왜] 검색이나 품목 사실이 한도에 딱 닿거나 넘겼다. 계획자를 한 번 더 부르면 한도를 넘는다.
            #      부르지 않고 route의 한도 검사가 finish로 보낸다
            return {}
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
        # [왜] 한 번 더 최악으로 검색하면 한도를 넘을 때도 검색하지 않는다 (tools.py와 같다)
        if step and step["action"] == "search_law":
            if state.get("llm_calls", 0) + worst_search_calls() > loop["max_llm_calls"]:
                return "finish"
        return step["action"] if step else "write"

    def search_law(state: MarviaState) -> dict:
        """법령 검색: 진행 중인 할 일의 질의로 RAG 서브그래프를 돌려 근거를 모은다 (설계 5.4)."""
        step = _current_step(state) or {}
        query = step.get("query") or state.get("masked_text", "")  # 질의가 비었으면 가린 질문 그대로
        # [왜] RAG 공책(RagState)은 메인 공책과 칸이 달라 노드 안에서 따로 부른다 (LangGraph 문서의 방식)
        try:
            out = rag_graph.invoke({"question": query, "as_of": deps.today()})
        except (httpx.HTTPError, psycopg.Error, LLMFailed, SearchFailed) as error:
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
            # [왜] 호출 수 셈은 tools.search_calls 한 곳에 있다.
            #      검색 결과가 비면 채점을 건너뛰어 실제로는 더 적다. 상한으로 세어 호출 수 한도에만 쓴다
            "llm_calls": state.get("llm_calls", 0) + search_calls(out.get("rewrites", 0)),
        }

    def extract_item(state: MarviaState) -> dict:
        """품목 사실: 사용자가 말한 재수입 품목 사실을 정해진 모양으로 뽑는다 (reimport_check의 입력)."""
        prompt = render(
            "item_facts",
            question=state.get("masked_text", ""),
            # [왜] 사유 이름만으로는 뜻이 모자라다(수입 최소량이 몇 kg인지 등). yaml 이름표를 함께 준다
            flags=flag_labels(),
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

    def depth(config: RunnableConfig) -> str:
        """작성자에게 줄 설명 깊이: 사용자가 승인해 저장한 설정, 없으면 rules의 기본값 (설계 8절 prefs)."""
        saved = store.get(("users", user_of(config), "prefs"), "depth") if store is not None else None
        # [주의] 저장된 값은 예전 데이터다. 허용 목록에 있을 때만 쓴다. 프롬프트의 지시 줄로 들어가기 때문이다
        if saved and saved.value["depth"] in cfg["memory"]["depths"]:
            return saved.value["depth"]
        return cfg["memory"]["default_depth"]

    def write(state: MarviaState, config: RunnableConfig) -> dict:
        """작성자: 가린 질문·화물 줄·계산·근거로 답 초안을 쓴다. 지난 위반이 있으면 함께 넘긴다."""
        prompt = render(
            "write",
            today=deps.today().isoformat(),
            depth=depth(config),
            # [주의] 원문(text)이 아니라 가린 글만 넘긴다. 실제 번호는 LLM에 가지 않는다
            question=state.get("masked_text", ""),
            cargos="\n".join(cargo_lines(state.get("cargos", []))),
            # [왜] ensure_ascii=False: 한글을 \uXXXX로 바꾸지 않아야 LLM이 읽는다
            calc=json.dumps(state.get("calc", {}), ensure_ascii=False),
            evidence=evidence_block(state.get("evidence", [])),
            # [왜] 작성자가 모르면 코드가 쓴 공식 출처 줄 위에 "찾지 못했다"고 쓴다.
            #      인용할 수 없어 주소는 뺀다(코드가 답 아래에 쓴다)
            official="\n".join(f"{s['name']} (시행 {s['effective']})" for s in state.get("official", [])),
            gaps="\n".join(state.get("gaps", [])),
            clarifications="\n".join(state.get("clarifications", [])),
            # [왜] 도구 결과는 messages에만 있어 작성자가 못 본다. 한 일을 모르면 한 일과 반대로 답한다
            actions="\n".join(state.get("actions", [])),
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

    # [왜] 에이전트 길에만 모델이 있다. 계획자 길은 대화 기록을 쓰지 않아 요약도 하지 않는다
    summary = build_summary(deps.model) if deps.model is not None else None

    def brief(state: MarviaState, runtime: Runtime) -> dict:
        """에이전트 길: 기록이 길면 앞부분을 요약하고, 이번 차례 질문(가린 글)과 화물 줄을 메시지로 더한다."""
        update: dict = {"messages": []}
        if summary is not None:
            short = None
            try:
                # [왜] 루프(서브그래프) 안에서 요약하면 부모 공책의 기록은 줄지 않는다(11-06 실측).
                #      부모 노드에서 요약 미들웨어의 before_model 훅을 직접 부른다. 돌려주는 값은
                #      [기록 모두 지우기, 요약 메시지, 남길 최근 메시지]이고 add_messages가 그대로 적용한다
                short = summary.before_model(AgentState(messages=state.get("messages", [])), runtime)
            except MODEL_ERRORS as error:
                # [왜] 요약 LLM이 실패하면 다른 LLM 실패와 같이 부분 답으로 간다 (설계 6.4).
                #      그래도 아래에서 이번 차례 메시지를 기록에 더한다. 질문과 이 차례에 보인 감시 변화
                #      (<watch_news>)를 다음 차례 모델이 알아야 한다. 변화는 답에 보인 뒤 본 것으로 표시돼
                #      다시 나오지 않고, 기록에 남기는 답(_remember)에는 감시 줄이 없다
                update = {"messages": [], "stopped": "llm_failed", **_failure(state, "summary", error)}
            if short:
                # [왜] 라이브러리는 요약을 태그 없는 사용자 말 자리(HumanMessage)에 넣는다. 요약은 도구 결과
                #      (공식 출처 제목, 저장한 기억)를 읽고 쓴 글이라 데이터 태그 안에 다시 싼다 (설계 12절)
                removal, said, *kept = short["messages"]
                # [주의] 글만 바꾼다. 메시지 종류와 라이브러리 표시(additional_kwargs)는 그대로 둔다
                body = render("conversation_summary", summary=str(said.content).removeprefix(SUMMARY_LEAD))
                said = said.model_copy(update={"content": body})
                # [왜] 요약 한 번은 LLM 호출 한 번이다. 이번 차례 상한에 함께 센다
                update = {"messages": [removal, said, *kept], "llm_calls": state.get("llm_calls", 0) + 1}
        text = render(
            "agent_turn",
            today=deps.today().isoformat(),
            cargos="\n".join(cargo_lines(state.get("cargos", []))),
            question=state.get("masked_text", ""),
            news="\n".join(state.get("watch_news", [])),
        )
        return update | {"messages": update["messages"] + [HumanMessage(text)]}

    def news(state: MarviaState, config: RunnableConfig) -> dict:
        """에이전트 길: 감시 중인 화물의 새 변화를 꺼내 이번 차례에 보일 줄(토큰 글)로 둔다 (계획 3d)."""
        if deps.watch is None:
            return {}
        try:
            news_rows = deps.watch.news(user_of(config))
        except psycopg.Error:
            # [왜] 알림은 덤이다. DB 오류로 차례 전체를 죽이지 않고 변화 없이 간다.
            #      꺼내기만 하고 표시하지 않으니 잃는 변화는 없고 다음 차례에 다시 나온다
            return {}
        mask_map = dict(state.get("mask_map", {}))
        # [주의] 변화에는 실제 번호가 있다. 이 대화의 가림 표로 토큰을 받아 토큰 글로만 공책에 둔다
        lines = [
            f"{token_for(mask_map, n['number'], kind_of(n['number']))}: "
            f"{n['old_stage'] or '처음 확인'} → {n['new_stage']}"
            for n in news_rows
        ]
        return {"watch_news": lines, "watch_ids": [n["id"] for n in news_rows], "mask_map": mask_map}

    # [주의] 돌려주는 타입을 Callable로 적지 않는다. 인자 이름(config)이 빠져 add_node 타입 검사가 거절한다
    def shown(node: Callable[[MarviaState], dict]):
        """답을 내는 노드(respond·finish·decline)를 감싸, 그 답에 보인 감시 변화를 본 것으로 표시한다."""

        def run(state: MarviaState, config: RunnableConfig) -> dict:
            update = node(state)
            ids = state.get("watch_ids", [])
            if deps.watch is not None and ids:
                # [왜] 표시하지 못하면 다음 차례에 같은 변화가 다시 보인다. 잃는 것보다 낫다.
                #      DB 오류로 이번 답을 막지 않는다
                with suppress(psycopg.Error):
                    deps.watch.ack(user_of(config), ids)
            return update

        return run

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
    # [왜] 두 길(계획자·에이전트)이 같은 식별을 쓴다. 컨테이너 번호는 감시 목록에서도 찾는다 (계획 6a)
    graph.add_node("identify", build_identify_graph(watched(deps.watch)))
    graph.add_node("ask", ask)
    # 식별 서브그래프와 같은 조회 서브그래프를 다시 쓴다
    # [왜] reuse: ask 앞의 cargos는 이번 차례 식별이 조회한 결과다(물으면 read가 비운다). 그 번호는 다시
    #      조회하지 않는다 (같은 글의 B/L을 컨테이너 선택지 뒤에 또 조회하지 않게)
    graph.add_node("lookup", build_lookup_graph(watched(deps.watch), reuse=True))
    graph.add_node("write", write)
    graph.add_node("verify", check)
    graph.add_node("respond", shown(respond))
    graph.add_node("finish", shown(finish))
    graph.add_edge(START, "start")
    graph.add_edge("start", "identify")
    # [왜] 식별 뒤 첫 일: 계획자 길은 plan, 에이전트 길은 news(감시 변화) → brief
    first = "news" if loop in LOOP_PATHS else "plan"
    graph.add_conditional_edges(
        "identify", lambda state: "ask" if state.get("question") else first, ["ask", first]
    )
    graph.add_edge("ask", "lookup")
    graph.add_edge("lookup", first)
    if loop in LOOP_PATHS:
        if deps.model is None:
            raise ValueError(
                "에이전트 길과 수퍼바이저 길에는 AgentDeps.model(도구 호출 모델)이 있어야 합니다"
            )
        # [왜] 에이전트 길은 루프가 다시 찾으므로 RAG 안 고쳐 쓰기는 줄인다 (agent.yaml loop.rag_rewrites)
        agent_rag = build_rag_graph(deps.rag, max_rewrites=cfg["loop"]["rag_rewrites"])
        graph.add_node("news", news)
        graph.add_node("brief", brief)
        graph.add_edge("news", "brief")
        graph.add_node("decline", shown(decline))
        if loop == "agent":
            tools = make_tools(agent_rag, deps.today, deps.provision, deps.model, deps.web, deps.watch)
            # [왜] create_agent가 만든 그래프도 서브그래프 노드다. 같은 이름 칸을 주고받는다
            graph.add_node("agent", build_agent(deps.model, tools, permission_mode))
        else:
            # [왜] 수퍼바이저 길에는 조사 도구(research)가 없다. model을 넘기지 않으면 만들지 않는다
            tools = make_tools(agent_rag, deps.today, deps.provision, None, deps.web, deps.watch)
            graph.add_node("supervisor", build_supervisor(deps.model, tools))
            ends = ("write", "decline", "finish")

            def router(state: MarviaState) -> Command:
                """수퍼바이저 뒤 갈림길: 넘길 곳이 있으면 그 서브에이전트로, 없으면 에이전트 길의 끝으로."""
                if state.get("stopped"):
                    return Command(goto="finish")
                to = state.get("route")
                if to:
                    return Command(goto=to)
                # [왜] handoff가 넘기지 못했으면(모르는 이름) 모델이 오류 글을 보고 고쳐 부르게 한다
                return Command(goto="supervisor" if refused_handoff(state) else _after_agent(state))

            # [왜] destinations: Command로 가는 곳은 그림(get_graph)에 저절로 나오지 않아 적어 준다
            graph.add_node("router", router, destinations=(*subagents(), "supervisor", *ends))
            graph.add_edge("supervisor", "router")
            for name in subagents():
                # [왜] 한 단계에 서브에이전트 하나만 돈다. 부모 공책 칸이 덮어쓰기라 둘이 함께 쓰면 멈춘다
                graph.add_node(
                    name, sub_node(name, build_sub(deps.model, tools, name, permission_mode), deps.today)
                )
                graph.add_edge(name, "supervisor")
        # [왜] 요약 LLM이 실패해 멈췄으면 루프를 돌리지 않고 부분 답으로 간다
        graph.add_conditional_edges(
            "brief", lambda state: "finish" if state.get("stopped") else loop, [loop, "finish"]
        )
        if loop == "agent":
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
    # [왜] with_config로 그래프에 recursion_limit을 붙여 둔다. invoke 때 config를 넘기면 그 값이 이긴다.
    #      max_concurrency는 한 단계에 함께 도는 작업(Send 갈래, 병렬 도구) 수를 서브그래프까지 막는다
    limit = cfg["loop"]["agent_recursion_limit" if loop in LOOP_PATHS else "recursion_limit"]
    compiled = graph.compile(checkpointer=checkpointer, store=store)
    return compiled.with_config(recursion_limit=limit, max_concurrency=cfg["loop"]["max_concurrency"])
