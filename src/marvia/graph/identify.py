"""식별 서브그래프: 단서 글 → 번호 읽기·가림 → 조회 → 화물별 결과 (설계 4절).

하지 않는 일: 사용자에게 직접 묻기. 애매하면 question에 담아 끝내고, 묻는 일은 메인 그래프만 한다 (설계 6.3).
순서도: START → read → (애매하면 END, 아니면 lookup) → choose → END
조회(lookup)는 따로 컴파일한 서브그래프다: assign → 번호마다 Send("one") → collect (설계 4.3, 계획 3d)
컨테이너 번호는 UNI-PASS로 조회하지 않고 collect가 아는 화물(이 대화, 감시 목록)에서 찾는다 (계획 6a)
"""

from __future__ import annotations

import operator
from collections.abc import Callable
from typing import Annotated, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from marvia.graph.state import IdentifyState
from marvia.identify.mask import mask_text, token_for
from marvia.identify.models import CargoFacts, CargoIdentity, ToolError
from marvia.identify.parse import container_typo, kind_of, read_numbers
from marvia.tools.rules import load_rules
from marvia.tools.unipass import facts_carry_containers, lookup_cargo

# 실행 설정 → 그 사용자의 감시 목록 번호 (graph/tools.py의 watched가 만든다). 컨테이너를 찾을 때만 부른다
Watched = Callable[[RunnableConfig], list[str]]


def read(state: IdentifyState) -> dict:
    """번호를 읽고 가린다. 애매한 덩어리나 확인 숫자가 틀린 컨테이너 모양 번호가 있으면 선택지를 만든다."""
    text = state.get("text", "")
    # [왜] 같은 대화(thread)의 앞 차례 표를 이어 쓴다. 차례가 바뀌어도 같은 번호는 같은 토큰이고,
    #      모델이 기록에서 본 [BL1]을 이번 차례에도 조회할 수 있다 (계획 3d)
    masked, mask_map = mask_text(text, state.get("mask_map"))
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
            for number in read_result.numbers:
                if not container_typo(number.value):
                    numbers.append(number.value)
                    continue
                # [왜] 오타면 조회하기 전에 묻는다. 같은 모양의 B/L일 수도 있어 B/L 조회를 권장안으로 둔다
                #      (계획 6a). 화면 글에는 토큰만 쓴다
                token = token_for(mask_map, number.value, number.kind)
                question = {
                    "kind": "choice",
                    "question": f"{token}은 컨테이너 번호 모양인데 확인 숫자가 맞지 않아요. "
                    "번호를 확인해 주세요",
                    "options": [
                        {"label": token, "description": "B/L 번호로 조회"},
                        {"label": "조회하지 않음", "description": "고친 번호를 직접 적어 주세요"},
                    ],
                    "recommended": 0,
                    "alternatives": [[number.value], []],
                }
    # [왜] 바꾼 칸만 돌려준다. LangGraph가 공책의 그 칸들만 덮어쓰고 나머지 칸(text 등)은 그대로 둔다
    return {"masked_text": masked, "mask_map": mask_map, "numbers": numbers, "question": question}


def identify_number(number: str, mask_map: dict[str, str]) -> dict:
    """번호 하나를 조회해 화물 결과(dict)로 만든다. 실패도 결과로 남긴다. mask_map에 토큰을 더할 수 있다."""
    kind = kind_of(number)
    try:
        result = lookup_cargo(number)
    except (OSError, ValueError) as error:
        # [왜] 번호 하나의 조회 오류가 다른 화물 조회까지 멈추지 않게 실패도 결과로 남긴다 (계획 3d).
        #      오류 글 대신 종류 이름만 둔다. 오류 글에 실제 번호나 파일 경로가 섞일 수 있다
        result = ToolError(code="lookup_failed", message=type(error).__name__, retryable=True)
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
    # [왜] 공책에는 pydantic 객체 대신 기본 dict로 넣는다. Postgres 체크포인트에 그대로 저장하기 쉽다
    return identity.model_dump(mode="json")


def known_cargo(cargos: list[dict], watched: list[str]) -> list[dict]:
    """컨테이너 번호를 맞춰 볼 화물 사실: 이미 조회한 화물(cargos)과 감시 목록 번호(다시 조회)."""
    known = [cargo["facts"] for cargo in cargos if cargo.get("facts")]
    have = {facts["number"] for facts in known}
    for number in watched:
        if number in have:
            continue
        try:
            result = lookup_cargo(number)
        except (OSError, ValueError):
            continue  # [왜] 감시 화물 하나의 조회 오류로 찾기 전체를 멈추지 않는다 (identify_number와 같다)
        if isinstance(result, CargoFacts):
            known.append(result.model_dump(mode="json"))
            have.add(number)
    return known


def container_identity(container: str, mask_map: dict[str, str], known: list[dict]) -> dict:
    """컨테이너 번호를 아는 화물 사실에서 찾는다. 하나면 그 화물, 여럿이면 후보, 없으면 정한 글로 남긴다."""
    found = {facts["number"]: facts for facts in known if container in facts.get("containers", [])}
    token = token_for(mask_map, container, "container")
    if len(found) == 1:
        facts = next(iter(found.values()))
        number = facts["number"]
        # [왜] 토큰은 사용자가 준 단서(컨테이너)의 것이다. 답의 화물 줄도 그 번호로 보인다
        identity = CargoIdentity(
            token=token,
            kind="container",
            cargo_no=number if kind_of(number) == "cargo_no" else None,
            bl_no=number if kind_of(number) == "bl" else None,
            mrn=facts.get("mrn"),
            vessel=facts.get("vessel_name"),
            confidence="confirmed",
            facts=CargoFacts.model_validate(facts),
        )
    else:
        # [주의] 후보 중 하나를 골라 답하지 않는다. 틀리면 다른 화물의 단계를 말한다
        code = "container_many" if found else "container_unknown"
        identity = CargoIdentity(
            token=token,
            kind="container",
            confidence="candidate" if found else "unknown",
            candidates=sorted(found),
            error=ToolError(code=code, message=load_rules("unipass")["messages"][code], retryable=False),
        )
    return identity.model_dump(mode="json")


class LookupState(IdentifyState, total=False):
    """조회 서브그래프의 공책: 식별 칸에 갈래 결과 칸을 더한다. found는 서브그래프 밖으로 내보내지 않는다."""

    # [왜] Send 갈래들이 같은 단계에 함께 쓴다. 합치는 함수가 없으면 InvalidUpdateError가 난다 (강의 13강)
    found: Annotated[list[dict], operator.add]  # {"idx": 처음 순서, "cargo": 화물 결과}


class LookupTask(TypedDict):
    """Send 갈래 하나가 받는 입력. 갈래는 공책 전체가 아니라 이것만 받는다."""

    idx: int  # 처음 번호 순서. 끝난 순서와 상관없이 이 순서로 모은다
    number: str  # 조회할 실제 번호
    mask_map: dict[str, str]  # 이 번호의 토큰이 이미 든 가림 표


def assign(state: IdentifyState) -> dict:
    """조회할 번호마다 토큰을 먼저 정한다."""
    # [왜] 갈래마다 토큰을 만들면 같은 이름표([BL2])가 두 번호에 붙을 수 있다. 나누기 전에 한 곳에서 정한다
    # [왜] 공책의 dict를 직접 고치지 않고 복사해서 고친다. 노드는 바꾼 값을 돌려주는 방식으로만 공책을 바꾼다
    mask_map = dict(state.get("mask_map", {}))
    for number in state.get("numbers", []):
        token_for(mask_map, number, kind_of(number))
    return {"mask_map": mask_map}


def fan_out(state: IdentifyState) -> list[Send] | str:
    """번호마다 갈래(Send) 하나를 보낸다. 컨테이너 번호는 collect가 찾는다. 보낼 것이 없으면 바로 collect."""
    mask_map = state.get("mask_map", {})
    sends = [
        Send("one", {"idx": i, "number": n, "mask_map": mask_map})
        for i, n in enumerate(state.get("numbers", []))
        if kind_of(n) != "container"
    ]
    return sends or "collect"


def one(state: LookupTask) -> dict:
    """갈래 하나: 번호 하나를 조회해 순서 번호와 함께 돌려준다. 실패도 결과다(identify_number)."""
    # [왜] 표 복사본을 넘긴다. 토큰은 assign이 넣어 두어 identify_number가 표를 바꿀 일이 없다
    cargo = identify_number(state["number"], dict(state["mask_map"]))
    return {"found": [{"idx": state["idx"], "cargo": cargo}]}


def build_lookup_graph(watched: Watched | None = None):
    """조회 서브그래프: 번호마다 Send로 나눠 함께 조회하고 처음 순서대로 모은다 (설계 4.3).
    watched가 있으면 컨테이너 번호를 감시 목록의 화물에서도 찾는다 (계획 6a)."""

    def collect(state: LookupState, config: RunnableConfig) -> dict:
        """갈래 결과를 처음 번호 순서대로 화물 칸에 둔다. 컨테이너 번호는 아는 화물 사실에서 찾는다."""
        found = {f["idx"]: f["cargo"] for f in state.get("found", [])}
        numbers = state.get("numbers", [])
        containers = {i: n for i, n in enumerate(numbers) if kind_of(n) == "container"}
        if containers:
            # [왜] 갈래 조회가 끝난 뒤에 찾는다. 같은 글에 함께 적은 B/L의 사실도 쓸 수 있다.
            #      state의 cargos는 아직 이번 결과로 바뀌기 전 값(지난 차례·대화의 화물)이다
            cargos = list(found.values()) + state.get("cargos", [])
            # [왜] 실제 모드의 사실에는 컨테이너가 없다. 감시 화물을 다시 조회해도 맞출 수 없으니 읽지 않는다
            watch_numbers = watched(config) if watched and facts_carry_containers() else []
            known = known_cargo(cargos, watch_numbers)
            mask_map = dict(state.get("mask_map", {}))
            for i, number in containers.items():
                found[i] = container_identity(number, mask_map, known)
        # [왜] 갈래가 끝나는 순서는 정해져 있지 않다. 순서 번호로 정렬한다 (강의 13강)
        return {"cargos": [found[i] for i in sorted(found)]}

    # [왜] 들고 나는 모양은 식별 공책으로 둔다. 갈래 결과 칸(found)은 부모에 돌려주지 않는다
    graph = StateGraph(LookupState, input_schema=IdentifyState, output_schema=IdentifyState)
    graph.add_node("assign", assign)
    graph.add_node("one", one)
    graph.add_node("collect", collect)
    graph.add_edge(START, "assign")
    graph.add_conditional_edges("assign", fan_out, ["one", "collect"])
    # [왜] 같은 단계에 보낸 갈래가 모두 끝나야 다음 단계의 collect가 한 번 돈다
    graph.add_edge("one", "collect")
    graph.add_edge("collect", END)
    return graph.compile()


def choose(state: IdentifyState) -> dict:
    """컨테이너에 실린 아는 화물이 여럿이면 어느 화물을 볼지 묻는 선택지를 만든다 (설계 4.1 ②, 6.3)."""
    many = next((c for c in state.get("cargos", []) if c.get("candidates")), None)
    if many is None:
        return {}
    mask_map = dict(state.get("mask_map", {}))
    # [왜] 선택지 글에는 토큰만 쓴다. 화면에 보낼 때 view.interrupt_card가 실제 번호로 되돌린다
    tokens = [token_for(mask_map, number, kind_of(number)) for number in many["candidates"]]
    question = {
        "kind": "choice",
        "question": f"컨테이너 {many['token']}에 실린 화물이 여럿이에요. 어느 화물을 볼까요?",
        "options": [{"label": " + ".join(tokens), "description": f"{len(tokens)}건 모두 조회"}]
        + [{"label": token, "description": "이 화물만 조회"} for token in tokens],
        "recommended": 0,  # [왜] 하나를 짐작하지 않고 모두 보이는 안을 권장한다
        "alternatives": [many["candidates"]] + [[number] for number in many["candidates"]],
    }
    # [왜] 고른 화물을 메인 그래프의 lookup이 조회한다. 컨테이너는 조회할 번호에서 뺀다(두면 후보가 또 나온다)
    container = mask_map[many["token"]]
    numbers = [number for number in state.get("numbers", []) if number != container]
    return {"question": question, "mask_map": mask_map, "numbers": numbers}


def _after_read(state: IdentifyState) -> str:
    """갈림길: 물을 것이 있으면 끝내고, 없으면 조회로 간다."""
    return END if state.get("question") else "lookup"


def build_identify_graph(watched: Watched | None = None):
    """식별 순서도를 조립해 실행 기계로 만든다. watched는 조회 서브그래프에 넘긴다 (계획 6a)."""
    graph = StateGraph(IdentifyState)  # 공책 모양을 알려 준다
    graph.add_node("read", read)  # 작업자 등록
    graph.add_node("lookup", build_lookup_graph(watched))  # [왜] 컴파일한 그래프도 노드 하나로 넣는다
    graph.add_edge(START, "read")  # 화살표: 시작하면 read
    # 갈림길: read가 끝나면 _after_read가 고른 곳으로 간다. 셋째 인자는 갈 수 있는 곳 목록(그림 그리기용)
    graph.add_conditional_edges("read", _after_read, ["lookup", END])
    graph.add_node("choose", choose)
    graph.add_edge("lookup", "choose")
    graph.add_edge("choose", END)
    # [왜] compile은 순서도가 올바른지(끊긴 화살표 등) 검사하고 .invoke()로 돌릴 수 있는 객체를 만든다
    return graph.compile()
