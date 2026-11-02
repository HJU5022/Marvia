"""메인 그래프: 사용자 메시지가 처음 들어가는 가장 바깥 순서도 (설계 6절).

순서도: START → start → identify(서브그래프) → (질문 있으면 ask → lookup) → write → verify
        → 위반 없음: respond / 위반·횟수 남음: write / 그 밖: finish → END
하지 않는 일: 계획 세우기·법령 검색·계산(계획 3a Task 5·6에서 plan·search_law·extract_item·calc로 들어온다).
LLM은 AgentDeps로 받는다. 테스트는 가짜 함수를 넣어 키 없이 돈다.
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
from marvia.graph.rag import evidence_block
from marvia.graph.schemas import Draft
from marvia.graph.state import MarviaState
from marvia.graph.verify import verify
from marvia.identify.mask import unmask
from marvia.identify.parse import read_numbers
from marvia.prompts import render
from marvia.tools.rules import load_rules


# [왜] 바깥 기능(LLM)을 함수로 받아 둔다. RagDeps와 같은 방식이다
@dataclass(frozen=True)
class AgentDeps:
    """메인 그래프가 쓰는 바깥 기능 묶음. 실제 값은 marvia.graph.live.agent_deps가 만든다(Task 8)."""

    write: Callable[[str], Draft]  # 프롬프트 → 답 초안
    today: Callable[[], date] = date.today  # [왜] 함수로 받아야 테스트가 날짜를 고정할 수 있다


def start(state: MarviaState) -> dict:
    """새 차례를 시작한다. 같은 대화(thread)의 지난 차례 근거·초안·횟수를 비운다."""
    # [왜] checkpointer는 thread마다 공책을 이어 쓴다. 비우지 않으면 지난 질문의 근거와 초안이 섞인다
    return {
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
    """갈림길: 물을 것이 있으면 ask, 없으면 write."""
    return "ask" if state.get("question") else "write"


def build_main_graph(deps: AgentDeps, checkpointer=None):
    """메인 순서도를 조립한다. checkpointer가 있어야 interrupt로 멈췄다가 이어 갈 수 있다."""
    cfg = load_rules("agent")

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
    graph.add_node("write", write)
    graph.add_node("verify", check)
    graph.add_node("respond", respond)
    graph.add_node("finish", finish)
    graph.add_edge(START, "start")
    graph.add_edge("start", "identify")
    graph.add_conditional_edges("identify", _after_identify, ["ask", "write"])
    graph.add_edge("ask", "lookup")
    graph.add_edge("lookup", "write")
    graph.add_edge("write", "verify")
    # [왜] 셋째 인자에 갈 수 있는 곳을 모두 적는다. 그림(get_graph)에 화살표가 빠지지 않는다
    graph.add_conditional_edges("verify", after_verify, ["respond", "write", "finish"])
    graph.add_edge("respond", END)
    graph.add_edge("finish", END)
    return graph.compile(checkpointer=checkpointer)
