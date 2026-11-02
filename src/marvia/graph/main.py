"""메인 그래프: 사용자 메시지가 처음 들어가는 가장 바깥 순서도 (설계 6절).

순서도: START → start → identify(서브그래프) → (질문 있으면 ask → lookup) → plan
        plan → (진행 중인 할 일) search_law → plan ... / 할 일 없음·write → write → verify
        → 위반 없음: respond / 위반·횟수 남음: write / 그 밖: finish → END
하지 않는 일: 품목 사실·계산(계획 3a Task 6에서 extract_item·calc로 들어온다), 한도·실패 처리(Task 7).
LLM·RAG는 AgentDeps로 받는다. 테스트는 가짜 함수를 넣어 키 없이 돈다.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from marvia.graph.answer import cargo_lines, final_answer, partial_answer
from marvia.graph.identify import build_identify_graph, lookup
from marvia.graph.rag import RagDeps, build_rag_graph, evidence_block
from marvia.graph.schemas import Draft, Plan
from marvia.graph.state import MarviaState
from marvia.graph.verify import verify
from marvia.identify.mask import unmask
from marvia.identify.parse import read_numbers
from marvia.prompts import render
from marvia.tools.rules import load_rules


# [왜] 바깥 기능(LLM·RAG)을 함수로 받아 둔다. RagDeps와 같은 방식이다
@dataclass(frozen=True)
class AgentDeps:
    """메인 그래프가 쓰는 바깥 기능 묶음. 실제 값은 marvia.graph.live.agent_deps가 만든다(Task 8)."""

    rag: RagDeps  # RAG 서브그래프의 바깥 기능 (계획 2)
    plan: Callable[[str], Plan]  # 프롬프트 → 남은 할 일
    write: Callable[[str], Draft]  # 프롬프트 → 답 초안
    today: Callable[[], date] = date.today  # [왜] 함수로 받아야 테스트가 날짜를 고정할 수 있다


def start(state: MarviaState) -> dict:
    """새 차례를 시작한다. 같은 대화(thread)의 지난 차례 근거·초안·횟수를 비운다."""
    # [왜] checkpointer는 thread마다 공책을 이어 쓴다. 비우지 않으면 지난 질문의 근거와 초안이 섞인다
    return {
        "plan": [],
        "evidence": [],
        "gaps": [],
        "calc": {},
        "draft": {},
        "verification": [],
        "write_attempts": 0,
        "llm_calls": 0,
        "failed_tools": [],
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


def merge_evidence(old: list[dict], new: list[dict]) -> list[dict]:
    """근거 묶음을 합친다. 같은 unit_id는 점수가 높은 것 하나만 남기고 점수 높은 순으로 줄 세운다."""
    best: dict[str, dict] = {}
    for item in old + new:
        if item["unit_id"] not in best or item["score"] > best[item["unit_id"]]["score"]:
            best[item["unit_id"]] = item
    return sorted(best.values(), key=lambda item: item["score"], reverse=True)


def _current_step(state: MarviaState) -> dict | None:
    """진행 중인 할 일. 없으면 None."""
    return next((step for step in state.get("plan", []) if step["status"] == "in_progress"), None)


def respond(state: MarviaState) -> dict:
    """검증을 통과한 초안으로 답을 만들고, 화면에 보내기 직전에 실제 번호로 되돌린다."""
    text = final_answer(state.get("draft", {}), state.get("cargos", []), state.get("evidence", []))
    return {"answer": unmask(text, state.get("mask_map", {}))}


def finish(state: MarviaState) -> dict:
    """부분 답을 낸다 (설계 6.4). 검증을 넘지 못한 초안은 쓰지 않는다."""
    text = partial_answer(
        state.get("cargos", []),
        state.get("calc", {}),
        state.get("evidence", []),
        state.get("gaps", []),
        state.get("failed_tools", []),
    )
    return {"answer": unmask(text, state.get("mask_map", {}))}


def _after_identify(state: MarviaState) -> str:
    """갈림길: 물을 것이 있으면 ask, 없으면 plan."""
    return "ask" if state.get("question") else "plan"


def build_main_graph(deps: AgentDeps, checkpointer=None):
    """메인 순서도를 조립한다. checkpointer가 있어야 interrupt로 멈췄다가 이어 갈 수 있다."""
    cfg = load_rules("agent")
    rag_graph = build_rag_graph(deps.rag)  # [왜] 한 번만 만들고 search_law가 부를 때마다 다시 쓴다

    def plan(state: MarviaState) -> dict:
        """계획자: 지금까지 한 일과 모은 것을 보고 남은 할 일을 다시 정한다 (설계 6.1)."""
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
            done="\n".join(f"{step['action']}: {step['query']}" for step in done),
            failed="\n".join(f"{t['tool']}: {t['message']}" for t in state.get("failed_tools", [])),
        )
        steps = [step.model_dump() | {"status": "pending"} for step in deps.plan(prompt).steps]
        if steps:
            steps[0]["status"] = "in_progress"  # [왜] 진행 중은 한 번에 하나 (설계 6.2)
        return {"plan": done + steps, "llm_calls": state.get("llm_calls", 0) + 1}

    def route(state: MarviaState) -> str:
        """갈림길: 진행 중인 할 일의 action 노드로 간다. 할 일이 없으면 write."""
        step = _current_step(state)
        return step["action"] if step else "write"

    def search_law(state: MarviaState) -> dict:
        """법령 검색: 진행 중인 할 일의 질의로 RAG 서브그래프를 돌려 근거를 모은다 (설계 5.4)."""
        step = _current_step(state) or {}
        query = step.get("query") or state.get("masked_text", "")  # 질의가 비었으면 가린 질문 그대로
        # [왜] RAG 공책(RagState)은 메인 공책과 칸이 달라 노드 안에서 따로 부른다 (LangGraph 문서의 방식)
        out = rag_graph.invoke({"question": query, "as_of": deps.today()})
        gaps = state.get("gaps", []) + ([] if out.get("sufficient") else [out.get("missing", "")])
        return {
            "evidence": merge_evidence(state.get("evidence", []), out.get("evidence", [])),
            "gaps": gaps,
            # [왜] 질의 분석 1 + 채점 (고쳐 쓰기 + 1) + 고쳐 쓰기 = 2 + 2 × 고쳐 쓰기.
            #      검색 결과가 비면 채점을 건너뛰어 실제로는 더 적다. 상한으로 세어 호출 수 한도에만 쓴다
            "llm_calls": state.get("llm_calls", 0) + 2 + 2 * out.get("rewrites", 0),
        }

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
        draft = deps.write(prompt)
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
    graph.add_node("plan", plan)
    graph.add_node("search_law", search_law)
    graph.add_node("write", write)
    graph.add_node("verify", check)
    graph.add_node("respond", respond)
    graph.add_node("finish", finish)
    graph.add_edge(START, "start")
    graph.add_edge("start", "identify")
    graph.add_conditional_edges("identify", _after_identify, ["ask", "plan"])
    graph.add_edge("ask", "lookup")
    graph.add_edge("lookup", "plan")
    # [왜] 셋째 인자에 갈 수 있는 곳을 모두 적는다. 그림(get_graph)에 화살표가 빠지지 않는다
    graph.add_conditional_edges("plan", route, ["search_law", "write"])
    graph.add_edge("search_law", "plan")  # [왜] 한 일을 보고 계획자가 다시 정한다. 이 화살표가 계획자 루프다
    graph.add_edge("write", "verify")
    graph.add_conditional_edges("verify", after_verify, ["respond", "write", "finish"])
    graph.add_edge("respond", END)
    graph.add_edge("finish", END)
    return graph.compile(checkpointer=checkpointer)
