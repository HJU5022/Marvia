"""배 판정을 모델이 읽는 길(계획 8c)이 꺼져 있으면 모델이 받는 것은 계획 8c 전과 같다 (CC1, C1).

tests/graph/test_vessel_off.py(계획 8b 끝)는 모델이 받는 메시지 글과 묶은 도구 '이름'의 순서, 화면, 공책을
해시로 묶는다. 이 파일은 그 시험이 못 보는 것만 더한다:
- 묶은 도구마다 이름, 설명, 인자 꼴(TOOLS_FULL_SHA)과 도구 결과 글(TOOL_RESULTS_SHA)
- 검증자를 부르는 자리의 인자와 고정 초안 묶음의 검증 결과(VERIFY_SHA)
- build_main_graph를 부르는 곳이 ** 키워드를 쓰지 않음
- 꺼진 길의 트레이스 가림 결과(SCRUB_SHA)
아래 값은 f208e59(계획 8b 끝)를 git archive로 푼 사본에서 낸 값이다. 값이 달라지면 고치기 전에 무엇이
달라졌는지부터 본다. 평가 지표를 다시 세는 시험(D14)은 tests/eval/test_run_eval_cli.py에 이미 있다.
"""

import ast
import hashlib
import json
import re
from datetime import date
from pathlib import Path

import httpx
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command
from pydantic import Field

from marvia.graph import main as graph_main
from marvia.graph.main import LOOPS, build_main_graph
from marvia.graph.schemas import Draft
from marvia.graph.supervisor import subagents
from marvia.graph.verify import verify
from marvia.trace import scrub
from marvia.watch import WatchDeps

ROOT = Path(__file__).resolve().parents[2]
# 길마다 묶은 도구의 이름, 설명, 인자 꼴(JSON 스키마)
TOOLS_FULL_SHA = "4bcb7110a0eec606059c65acf588c8b0b5b574590af8ec4b8a5b53fe97e91b46"
# 에이전트 길에서 꺼진 길의 도구를 하나씩 부른 차례들에서 모델이 받은 메시지 전체
TOOL_RESULTS_SHA = "e192e55eb4abbd3ff3412243fc04b1699986e8bd46380066915b50c92f378318"
# 고정 초안 묶음에 verify를 돌린 결과 전체
VERIFY_SHA = "75a3934de877e5c460dffead6999f667ca81eb800d077994206fc5df173e3cc8"
# 꺼진 길 세 길의 한 차례 동안 콜백이 받은 값을 하나씩 scrub한 결과
SCRUB_SHA = "ad4582ba86cdb73a20ff5b89a84ae6f04d23a2477515a9fc58777639d505b985"
# 에이전트 길과 수퍼바이저 길이 모델에 묶는 도구 이름 (글자로 적은 목록. make_tools 출력과 견주지 않는다)
AGENT_TOOLS = [
    "ask_user",
    "calc_deadlines",
    "check_reimport",
    "decline",
    "get_provision",
    "lookup_cargo",
    "official_lookup",
    "recall_memory",
    "research",
    "save_item_card",
    "save_preference",
    "search_law",
    "unwatch_cargo",
    "watch_cargo",
    "write_todos",
]
# 수퍼바이저 본체와 서브에이전트(cargo, law, item)가 각각 묶는 도구
SUPERVISOR_TOOLS = [
    ["ask_user", "decline", "handoff", "write_todos"],
    ["calc_deadlines", "get_provision", "lookup_cargo", "unwatch_cargo", "watch_cargo"],
    ["get_provision", "official_lookup", "search_law"],
    ["check_reimport", "get_provision", "recall_memory", "save_item_card", "save_preference"],
]

# 품목 사실: 건고추
CHILI = {
    "category": "농산물·임산물",
    "same": ["생산국", "품명", "수출업소", "포장장소"],
    "different": [],
    "prior_precise": "받음",
    "prior_result": "적합",
    "prior_cert_on": "2026-03-10",
    "flags": [],
}
TWO = [{"label": "부산", "description": "부산항 기준"}, {"label": "인천", "description": "인천항 기준"}]
LAW_PAGE = (
    "<h2>식품위생법</h2>"
    '<input type="hidden" id="lsId" name="lsId" value="001234">'
    '<input type="hidden" id="lsiSeq" value="270001">'
    "<script>var efYd = '20260101';</script>"
)


def _sha(value) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _spec(tool) -> list:
    """묶인 도구 하나의 이름, 설명, 인자 꼴. 딕셔너리로 바뀐 도구도 받는다."""
    if isinstance(tool, BaseTool):
        schema = tool.tool_call_schema
        shape = schema.model_json_schema() if hasattr(schema, "model_json_schema") else schema
        return [tool.name, tool.description, shape]
    return [tool.get("name"), tool.get("description"), tool.get("input_schema") or tool.get("parameters")]


class Rec(GenericFakeChatModel):
    """가짜 모델이 묶은 도구(이름, 설명, 인자 꼴)와 호출마다 받은 메시지 전체를 적는다."""

    bound: list = Field(default_factory=list)
    calls: list = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        self.bound.append([_spec(t) for t in tools])
        return self

    def _generate(self, messages, *args, **kwargs):
        self.calls.append(
            [
                [m.type, m.content, getattr(m, "name", None), _calls_of(m)]
                for m in messages
                if isinstance(m, BaseMessage)
            ]
        )
        return super()._generate(messages, *args, **kwargs)


def _calls_of(message) -> list:
    return [(c["name"], c["args"]) for c in getattr(message, "tool_calls", None) or []]


def _say(*calls: tuple[str, dict], text: str = "") -> AIMessage:
    return AIMessage(
        content=text, tool_calls=[{"name": n, "args": a, "id": f"c{i}-{n}"} for i, (n, a) in enumerate(calls)]
    )


def _web() -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=LAW_PAGE)))


def _watch() -> WatchDeps:
    return WatchDeps(
        add=lambda *row: None, news=lambda user: [], ack=lambda user, ids: None, remove=lambda *a: 1
    )


def _stable(value):
    """실행마다 달라지는 값(조회 시각, id)을 고정 글로 바꾼다."""
    if isinstance(value, dict):
        return {
            k: ("X" if k in ("fetched_at", "id", "tool_call_id") else _stable(v)) for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_stable(v) for v in value]
    return value


def _cfg(thread: str, callbacks=None) -> dict:
    return {"configurable": {"thread_id": thread}, "callbacks": callbacks or []}


def _agent(agent_deps, model, loop: str = "agent", **changes):
    deps = agent_deps(model=model, web=_web(), watch=_watch(), **changes)
    return build_main_graph(deps, InMemorySaver(), loop=loop, store=InMemoryStore())


def _approve(count: int = 1) -> Command:
    return Command(resume={"decisions": [{"type": "approve"}] * count})


# --- 도구 인자 꼴 ---


def _handoffs() -> tuple:
    """수퍼바이저가 서브에이전트마다 한 번씩 넘기는 대본. 서브에이전트가 묶는 도구도 적히게 한다."""
    out: list = []
    for name in subagents():
        out += [_say(("handoff", {"to": name, "task": "시험"})), AIMessage("")]
    return tuple(out)


def _bound_by_loop(agent_deps) -> dict:
    seen = {}
    for loop in LOOPS:
        script = (*(_handoffs() if loop == "supervisor" else ()), _say(), _say(), _say(), _say())
        model = Rec(messages=iter(script))
        graph = _agent(agent_deps, model, loop)
        graph.invoke({"text": "DEMO0001 수입신고는 언제까지 해요?"}, _cfg(f"tools-{loop}"))
        seen[loop] = model.bound
    return seen


def test_the_tools_bound_on_each_off_path_keep_their_names_descriptions_and_argument_shapes(agent_deps):
    # [왜] 11-16 R-149, R-155. test_vessel_off.py의 MODEL_SHA는 도구 '이름'만 본다. 설명 한 글자나
    #      선택 인자 하나가 바뀌어도 모델의 선택이 달라진다. web과 watch를 넣어 도구 전부를 묶는다
    seen = _bound_by_loop(agent_deps)
    assert seen["planner"] == []  # 계획자 길은 모델에 도구를 묶지 않는다
    names = sorted({spec[0] for bound in seen["agent"] for spec in bound})
    assert names == sorted(AGENT_TOOLS)
    assert sorted({tuple(sorted(spec[0] for spec in bound)) for bound in seen["supervisor"]}) == sorted(
        tuple(names) for names in SUPERVISOR_TOOLS
    )
    assert _sha(seen) == TOOLS_FULL_SHA


# --- 도구 결과 글 ---


def _tool_turns(agent_deps, fake_rag) -> dict:
    """꺼진 길의 도구를 하나씩 고정한 가공 인자로 부르는 차례들. 모델이 받은 메시지 전체를 모은다."""
    out = {}
    todos = {"todos": [{"content": "기한 계산", "status": "in_progress"}]}

    def run(name, text, script, resumes=(), **changes):
        model = Rec(messages=iter(script))
        graph = _agent(agent_deps, model, **changes)
        graph.invoke({"text": text}, _cfg(name))
        for resume in resumes:
            graph.invoke(resume, _cfg(name))
        out[name] = _stable(model.calls)

    run(
        "basic",
        "DEMO0001 NOPE0001 수입신고 기한을 알려 주세요",
        (
            _say(("write_todos", todos)),
            _say(("calc_deadlines", {})),
            _say(("lookup_cargo", {"tokens": ["[BL1]", "[BL2]", "[BL9]"]})),
            _say(("search_law", {"query": "수입신고 기한"})),
            _say(("get_provision", {"label": "관세법 제241조제3항"})),
            _say(("get_provision", {"label": "시행규칙 별표 9"})),
            _say(("check_reimport", {"facts": CHILI})),
            _say(),
            _say(),
        ),
    )
    # [왜] 11-16 R-174. 근거가 모자란 갈래의 "빠진 근거:" 줄은 근거가 충분한 RAG로는 나오지 않는다
    run(
        "gap",
        "수입신고 기한이 궁금해요",
        (_say(("search_law", {"query": "수입신고 기한"})), _say(), _say()),
        rag=fake_rag(sufficient=False),
    )
    run(
        "memory",
        "건고추 카드로 기억하고 앞으로 자세히 설명해 줘",
        (
            _say(("check_reimport", {"facts": CHILI})),
            _say(("save_item_card", {"name": "건고추"})),
            _say(("recall_memory", {})),
            _say(("save_preference", {"depth": "자세히"})),
            _say(),
            _say(),
        ),
        (_approve(), _approve()),
    )
    run(
        "ask",
        "장치기간이 궁금해요",
        (_say(("ask_user", {"question": "어느 항구 기준으로 볼까요?", "options": TWO})), _say(), _say()),
        (Command(resume={"selected": 1}),),
    )
    run(
        "official",
        "식품위생법은 언제부터 시행됐어요?",
        (
            _say(("official_lookup", {"law_name": "식품위생법"})),
            _say(("research", {"question": "수입신고 기한을 정한 조문"})),
            _say(("search_law", {"query": "수입신고 기한"})),
            _say(text="관세법 제241조제3항이 30일을 정해요."),
            _say(),
            _say(),
        ),
    )
    run(
        "watch",
        "DEMO0001 계속 지켜봐 줘",
        (
            _say(("watch_cargo", {"token": "[BL1]"}), ("watch_cargo", {"token": "[BL9]"})),
            _say(("unwatch_cargo", {"token": "[BL1]"})),
            _say(),
            _say(),
        ),
        (_approve(2), _approve()),
    )
    run("decline", "오늘 날씨 어때요?", (_say(("decline", {"reason": "날씨 질문"})), _say()))
    return out


def test_the_tool_results_the_model_receives_are_unchanged_when_the_switch_is_off(agent_deps, fake_rag):
    # [왜] 11-16 R-155. 도구 결과 글(cargo_lines, 기한 목록, 검색 결과 줄, 거절 글 등)이 바뀌면 모델이 받는
    #      글이 달라진다. 대본이 부르지 않는 도구의 결과 글까지, 꺼진 길의 도구 전부를 한 번씩 부른다
    turns = _tool_turns(agent_deps, fake_rag)
    sent = " ".join(str(m[1]) for call in turns["basic"] for m in call)
    assert "[BL1]" in sent  # 대본이 실제로 화물 줄을 만들었다
    assert "빠진 근거:" in str(turns["gap"])  # 근거가 모자란 갈래의 줄이 실제로 모델에 갔다
    assert _sha(turns) == TOOL_RESULTS_SHA


# --- 검증자 ---

MASK = {"[BL1]": "DEMO0001", "[BL2]": "NOPE12345678"}
EVIDENCE = [
    {
        "unit_id": "L001556@20261002#제241조.3항",
        "law_name": "관세법",
        "heading": "관세법 > 제9장 통관 > 제241조(수출ㆍ수입 또는 반송의 신고)",
        "effective": "2026-10-02",
        "source_url": "https://www.law.go.kr/test",
        "text": "제241조 ③ 물품을 보세창고에 반입한 자는 반입일부터 30일 이내에 신고해야 한다.",
        "score": 0.9,
    }
]
CALC = {
    "deadlines": [
        {
            "cargo": "[BL1]",
            "name": "수입신고 기한",
            "start_stage": "반입신고",
            "start": "2026-10-27",
            "due": "2026-11-26",
            "days_left": 24,
            "basis": "관세법 제241조제3항",
            "surcharge": None,
        }
    ]
}
CARGOS = [
    {
        "token": "[BL1]",
        "facts": {"stage": "반입신고", "stage_at": "2026-10-27T09:00:00+09:00", "port": "부산"},
        "error": None,
    },
    {
        "token": "[BL2]",
        "facts": None,
        "error": {"code": "not_found", "message": "재생 데이터에 없는 번호입니다", "retryable": False},
    },
]
CITE = ["L001556@20261002#제241조.3항"]
# 고정 초안 묶음(검증자 규칙마다 걸리는 것과 지나가는 것). 저장소 밖 파일은 쓰지 않는다
DRAFTS = [
    ("관세법 제241조에 따라 반입일부터 30일 이내에 수입신고해야 해요.", CITE),
    ("수입신고 기한은 2026-11-26이에요. [BL1]은 24일 남았어요.", CITE),
    ("기한은 11월 26일이에요.", CITE),
    ("기한은 2026-12-31이에요.", CITE),
    ("제999조에 따라요.", CITE),
    ("근거에 없는 인용이에요.", ["L000000@20260101#제1조"]),
    ("인용이 없어요.", []),
    ("통관이 가능합니다.", CITE),
    ("HS 코드는 0904입니다.", CITE),
    ("세액은 120,000원이에요.", CITE),
    ("가산세는 5년 동안 1.5%예요.", CITE),
    ("DEMO0001은 반입신고 단계예요.", CITE),
    ("서류검사 요건을 충족해요.", CITE),
    ("서류검사 요건을 충족하는지는 단정할 수 없어요.", CITE),
    ("[BL1]은 부산에 있어요. 주의하세요. 경계를 넘어요. 부분적으로 맞아요.", CITE),
    ("순항 중이고 확실히 도착해요. 등급은 주의예요. 확신은 부분이에요.", CITE),
]


def test_the_verifier_gives_the_same_result_on_a_fixed_set_of_drafts():
    # [왜] 11-16 R-159. 검증자 함수의 결과가 8c 전과 같음을 묶는다. 판정 값을 받는 새 규칙은 값을 안 주면
    #      아무것도 보지 않아야 한다
    seen = []
    for answer, citations in DRAFTS:
        draft = Draft(
            answer=answer, citations=citations, next_options=["관세사에게 물어보기"], forwarder_message=""
        )
        seen.append(verify(draft, EVIDENCE, CALC, CARGOS, MASK, date(2026, 11, 2)))
    assert any(seen) and not all(seen)
    assert _sha(seen) == VERIFY_SHA


def _drive(agent_deps, loop: str, thread: str) -> None:
    model = Rec(messages=iter((*(_handoffs()[:2] if loop == "supervisor" else ()), _say(), _say(), _say())))
    graph = _agent(agent_deps, model, loop)
    out = graph.invoke({"text": "DEMO0001 DEMO0002 언제까지 수입신고 해요?"}, _cfg(thread))
    assert out["answer"]


def test_the_verifier_is_called_without_verdicts_on_all_three_off_paths(agent_deps, monkeypatch):
    # [왜] 11-16 R-159. 함수의 결과만 묶으면 부르는 자리가 판정 값을 넘겨도 못 본다. 꺼진 길에서 검증자는
    #      새 인자 없이 불린다
    seen = []
    real = graph_main.verify
    monkeypatch.setattr(graph_main, "verify", lambda *a, **k: seen.append((len(a), k)) or real(*a, **k))
    for loop in LOOPS:
        _drive(agent_deps, loop, f"verify-{loop}")
    assert len(seen) >= 3
    for count, kwargs in seen:
        assert count == 6
        assert kwargs.get("verdicts") is None and kwargs.get("user_dates") is None


# --- build_main_graph 호출 ---


def test_no_build_main_graph_call_hides_a_keyword_behind_double_star():
    # [왜] 11-16 R-153. test_vessel_off.py의 AST 검사는 vessel= 키워드의 이름을 본다. **{"vessel": v}로
    #      이름을 숨기면 그 검사를 피한다. 저장소의 어느 호출도 ** 키워드를 넘기지 않는다
    skipped = {"tests", "node_modules", "graphify-out"}
    hidden = []
    count = 0
    for path in sorted(ROOT.rglob("*.py")):
        parts = path.relative_to(ROOT).parts
        if any(part.startswith(".") or part in skipped for part in parts[:-1]):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and ast.unparse(node.func).split(".")[-1] == "build_main_graph":
                count += 1
                hidden += [str(path.relative_to(ROOT)) for kw in node.keywords if kw.arg is None]
    assert count >= 2 and hidden == []


# --- 트레이스 가림 ---


class Spans(BaseCallbackHandler):
    """Langfuse 콜백이 span으로 받는 값(입력, 출력, 모델 입력과 출력)을 그대로 모은다."""

    def __init__(self):
        self.values: list = []

    def on_chain_start(self, serialized, inputs, **kwargs):
        self.values.append(inputs)

    def on_chain_end(self, outputs, **kwargs):
        self.values.append(outputs)

    def on_tool_start(self, serialized, input_str, **kwargs):
        self.values.append([input_str, kwargs.get("inputs")])

    def on_tool_end(self, output, **kwargs):
        self.values.append(output)

    def on_chat_model_start(self, serialized, messages, **kwargs):
        self.values.append(messages)

    def on_llm_end(self, response, **kwargs):
        self.values.append(response)


def _scrubbed_spans(agent_deps) -> list:
    """꺼진 길 세 길과 도구 대본의 한 차례 동안 콜백이 받은 값을 하나씩 scrub한 글들(순서와 무관하게 정렬)."""
    out: list[str] = []
    for loop in LOOPS:
        spans = Spans()
        model = Rec(
            messages=iter((*(_handoffs()[:2] if loop == "supervisor" else ()), _say(), _say(), _say()))
        )
        graph = _agent(agent_deps, model, loop)
        graph.invoke({"text": "DEMO0001 DEMO0002 언제까지 수입신고 해요?"}, _cfg(f"scrub-{loop}", [spans]))
        out += [json.dumps(scrub(v), ensure_ascii=False, sort_keys=True, default=str) for v in spans.values]
    spans = Spans()
    model = Rec(
        messages=iter(
            (
                _say(("lookup_cargo", {"tokens": ["[BL1]", "[BL9]"]})),
                _say(("check_reimport", {"facts": CHILI})),
                _say(("save_item_card", {"name": "건고추"})),
                _say(),
                _say(),
            )
        )
    )
    graph = _agent(agent_deps, model)
    graph.invoke({"text": "DEMO0001 건고추 카드로 기억해 줘"}, _cfg("scrub-tools", [spans]))
    graph.invoke(_approve(), _cfg("scrub-tools", [spans]))
    out += [json.dumps(scrub(v), ensure_ascii=False, sort_keys=True, default=str) for v in spans.values]
    # [왜] 번호 덩어리를 가릴 때 시각의 시·분·초 꼬리가 남는다. 실행마다 달라지는 그 꼬리를 없앤다
    return sorted(re.sub(r"\[가림\][:\d.+Z-]*", "[가림]", text) for text in out)


def test_the_trace_scrub_of_the_off_paths_is_unchanged(agent_deps):
    # [왜] 11-16 R-168, D17. 8c가 trace._ship_values를 dataclass·pydantic·Command·ToolMessage.artifact까지
    #      걷게 고쳐도 꺼진 길에는 모을 배 값이 없어 출력이 바이트까지 같아야 한다
    texts = _scrubbed_spans(agent_deps)
    assert len(texts) > 40 and any("lookup_cargo" in t for t in texts)
    assert _sha(texts) == SCRUB_SHA
