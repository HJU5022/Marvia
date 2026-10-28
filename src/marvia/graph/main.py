"""메인 그래프(계획 1판): 사용자 메시지가 처음 들어가는 가장 바깥 순서도 (설계 6절).

순서도: START → identify(서브그래프) → (질문 있으면 ask → lookup) → answer → END
하지 않는 일: 계획 세우기·법령 검색·LLM 답 쓰기. 계획자(LLM)와 RAG는 계획 2, 작성자는 계획 3에서 들어온다.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from marvia.graph.identify import build_identify_graph, lookup
from marvia.graph.state import MarviaState
from marvia.identify.mask import unmask
from marvia.identify.parse import read_numbers

# 번호를 하나도 못 찾았을 때의 안내 (설계 4.1 단서 등급 ③). 포워더용 문장은 계획 3에서 LLM이 쓴다
NO_NUMBER_GUIDE = (
    "번호를 찾지 못했어요. B/L 번호나 화물관리번호를 알려 주시면 바로 찾아볼게요. "
    "포워더에게 받은 메시지를 그대로 붙여 넣으셔도 됩니다."
)


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


def answer(state: MarviaState) -> dict:
    """화물별 상태를 고정 문장으로 만든다. 계획 3에서 작성자(LLM)로 바뀐다."""
    cargos = state.get("cargos", [])
    if not cargos:
        return {"answer": NO_NUMBER_GUIDE}
    # [왜] 붙여 쓴 번호를 나눴으면 "몇 건으로 읽었는지" 먼저 보여 준다 (설계 결정 7: 읽은 대로 보여 준다)
    lines = [f"{len(cargos)}건으로 읽었어요."] if len(cargos) > 1 else []
    for cargo in cargos:
        if cargo["facts"]:
            lines.append(f"{cargo['token']}: {cargo['facts']['stage']} ({cargo['facts']['port']})")
        else:
            lines.append(f"{cargo['token']}: 조회하지 못했어요 ({cargo['error']['message']})")
    # [왜] 문장은 이름표([BL1])로 만들고, 화면에 보내기 직전에만 실제 번호로 되돌린다
    return {"answer": unmask("\n".join(lines), state.get("mask_map", {}))}


def _after_identify(state: MarviaState) -> str:
    """갈림길: 물을 것이 있으면 ask, 없으면 바로 answer."""
    return "ask" if state.get("question") else "answer"


def build_main_graph(checkpointer=None):
    """메인 순서도를 조립한다. checkpointer가 있어야 interrupt로 멈췄다가 이어 갈 수 있다."""
    graph = StateGraph(MarviaState)
    # [왜] 컴파일한 서브그래프도 노드 하나처럼 넣을 수 있다. 공책 칸 이름이 같아서 그대로 주고받는다
    graph.add_node("identify", build_identify_graph())
    graph.add_node("ask", ask)
    graph.add_node("lookup", lookup)  # 식별 서브그래프의 조회 노드를 다시 쓴다
    graph.add_node("answer", answer)
    graph.add_edge(START, "identify")
    graph.add_conditional_edges("identify", _after_identify, ["ask", "answer"])
    graph.add_edge("ask", "lookup")
    graph.add_edge("lookup", "answer")
    graph.add_edge("answer", END)
    return graph.compile(checkpointer=checkpointer)
