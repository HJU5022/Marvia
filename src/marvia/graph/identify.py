"""식별 서브그래프: 단서 글 → 번호 읽기·가림 → 조회 → 화물별 결과 (설계 4절).

하지 않는 일: 사용자에게 직접 묻기. 애매하면 question에 담아 끝내고, 묻는 일은 메인 그래프만 한다 (설계 6.3).
순서도: START → read → (애매하면 END, 아니면 lookup) → END
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from marvia.graph.state import IdentifyState
from marvia.identify.mask import mask_text, token_for
from marvia.identify.models import CargoFacts, CargoIdentity
from marvia.identify.parse import kind_of, read_numbers
from marvia.tools.unipass_replay import lookup_cargo


def read(state: IdentifyState) -> dict:
    """번호를 읽고 가린다. 애매한 덩어리가 있으면 선택지 질문을 만든다."""
    text = state.get("text", "")
    masked, mask_map = mask_text(text)
    numbers: list[str] = []
    question = None
    for _, read_result in read_numbers(text):
        if read_result.ambiguous:
            # [주의] 계획 1은 애매한 덩어리를 한 번에 하나만 묻는다. 여럿이면 마지막 것만 남는다
            question = {
                "kind": "choice",
                "question": f"'{read_result.raw}'를 어떻게 읽을까요?",
                # 선택지마다 화면에 보일 이름과 설명
                "options": [
                    {"label": " + ".join(alt), "description": f"{len(alt)}건으로 조회"}
                    for alt in read_result.alternatives
                ],
                "recommended": 0,  # [왜] 권장안을 맨 앞에 둔다 (Codex·DeepSeek 방식, 설계 결정 4)
                "alternatives": read_result.alternatives,  # 고른 번호로 실제 번호를 꺼내는 데 쓴다
            }
        else:
            numbers += [n.value for n in read_result.numbers]
    # [왜] 바꾼 칸만 돌려준다. LangGraph가 공책의 그 칸들만 덮어쓰고 나머지 칸(text 등)은 그대로 둔다
    return {"masked_text": masked, "mask_map": mask_map, "numbers": numbers, "question": question}


def lookup(state: IdentifyState) -> dict:
    """확정한 번호를 하나씩 조회해 화물별 결과로 만든다. 실패도 결과로 남긴다."""
    # [왜] 공책의 dict를 직접 고치지 않고 복사해서 고친다. 노드는 바꾼 값을 돌려주는 방식으로만 공책을 바꾼다
    mask_map = dict(state.get("mask_map", {}))
    cargos = []
    for number in state.get("numbers", []):
        kind = kind_of(number)
        result = lookup_cargo(number)
        found = isinstance(result, CargoFacts)  # 성공이면 CargoFacts, 실패면 ToolError
        identity = CargoIdentity(
            # [왜] 사용자가 선택지로 고른 번호는 원문 가림 때 없던 번호라 여기서 이름표를 새로 받을 수 있다
            token=token_for(mask_map, number, kind),
            kind=kind,
            cargo_no=number if kind == "cargo_no" else None,
            bl_no=number if kind == "bl" else None,
            mrn=result.mrn if found else None,
            vessel=result.vessel_name if found else None,
            confidence="confirmed" if found else "unknown",
            facts=result if found else None,
            error=None if found else result,
        )
        # [왜] 공책에는 pydantic 객체 대신 기본 dict로 넣는다. Task 8에서 Postgres에 그대로 저장하기 쉽다
        cargos.append(identity.model_dump(mode="json"))
    return {"cargos": cargos, "mask_map": mask_map}


def _after_read(state: IdentifyState) -> str:
    """갈림길: 물을 것이 있으면 끝내고, 없으면 조회로 간다."""
    return END if state.get("question") else "lookup"


def build_identify_graph():
    """식별 순서도를 조립해 실행 기계로 만든다."""
    graph = StateGraph(IdentifyState)  # 공책 모양을 알려 준다
    graph.add_node("read", read)  # 작업자 등록
    graph.add_node("lookup", lookup)
    graph.add_edge(START, "read")  # 화살표: 시작하면 read
    # 갈림길: read가 끝나면 _after_read가 고른 곳으로 간다. 셋째 인자는 갈 수 있는 곳 목록(그림 그리기용)
    graph.add_conditional_edges("read", _after_read, ["lookup", END])
    graph.add_edge("lookup", END)
    # [왜] compile은 순서도가 올바른지(끊긴 화살표 등) 검사하고 .invoke()로 돌릴 수 있는 객체를 만든다
    return graph.compile()
