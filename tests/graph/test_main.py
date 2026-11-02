from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from marvia.graph.main import build_main_graph
from marvia.graph.schemas import Draft

# 근거 묶음에 없는 unit_id를 인용한 초안. 검증에서 늘 걸린다
BAD = Draft(
    answer="나쁜 답이에요.", citations=["LNOPE@20260101#제1조"], next_options=[], forwarder_message=""
)
FIXED = Draft(answer="고친 답이에요.", citations=[], next_options=[], forwarder_message="")


def cfg(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def recording(prompts: list[str], *drafts: Draft):
    """받은 프롬프트를 prompts에 적고 drafts를 앞에서부터 하나씩 돌려주는 가짜 작성자."""
    left = iter(drafts)

    def write(prompt: str) -> Draft:
        prompts.append(prompt)
        return next(left)

    return write


def test_unambiguous_answers_directly(agent_deps):
    graph = build_main_graph(agent_deps(), InMemorySaver())
    out = graph.invoke({"text": "demo0001 demo0002 어디야?"}, cfg("t1"))
    assert "2건으로 읽었어요." in out["answer"]
    assert "DEMO0002: 수입신고 (부산)" in out["answer"]
    assert "시험 답이에요." in out["answer"]  # 코드가 쓴 화물 줄 아래에 작성자 답


def test_ambiguous_interrupts_then_resumes(agent_deps):
    graph = build_main_graph(agent_deps(), InMemorySaver())
    out = graph.invoke({"text": "MOCK12345678TEST87654321"}, cfg("t2"))
    question = out["__interrupt__"][0].value
    assert question["kind"] == "choice" and question["recommended"] == 0
    out = graph.invoke(Command(resume={"selected": 0}), cfg("t2"))
    assert "MOCK12345678: 입항 (인천)" in out["answer"]
    assert "TEST87654321: 하선신고 (인천)" in out["answer"]


def test_custom_reply(agent_deps):
    graph = build_main_graph(agent_deps(), InMemorySaver())
    graph.invoke({"text": "MOCK12345678TEST87654321"}, cfg("t3"))
    out = graph.invoke(Command(resume={"custom": "MOCK12345678"}), cfg("t3"))
    assert "MOCK12345678" in out["answer"]
    assert "TEST87654321" not in out["answer"]


def test_no_number_guides_user(agent_deps):
    asked = Draft(
        answer="화물을 찾으려면 번호가 필요해요.",
        citations=[],
        next_options=[],
        forwarder_message="이번 고추 화물의 운송 서류 번호를 알려 주세요.",
    )
    graph = build_main_graph(agent_deps(write=lambda prompt: asked), InMemorySaver())
    out = graph.invoke({"text": "다음 주에 칭다오에서 고추 와요"}, cfg("t4"))
    assert "B/L" in out["answer"]  # 코드가 쓰는 포워더 안내 줄


def test_writer_sees_masked_text_only(agent_deps):
    prompts: list[str] = []
    graph = build_main_graph(agent_deps(write=recording(prompts, FIXED)), InMemorySaver())
    graph.invoke({"text": "DEMO0001 언제까지 신고해야 해요?"}, cfg("t5"))
    assert "[BL1] 언제까지 신고해야 해요?" in prompts[0]
    assert "[BL1]: 반입신고 (부산) 2026-10-27" in prompts[0]  # 화물 줄도 토큰으로
    assert "DEMO0001" not in prompts[0]


def test_violation_gets_one_rewrite(agent_deps):
    prompts: list[str] = []
    graph = build_main_graph(agent_deps(write=recording(prompts, BAD, FIXED)), InMemorySaver())
    out = graph.invoke({"text": "DEMO0001 어디야?"}, cfg("t6"))
    assert "고친 답이에요." in out["answer"]
    assert "근거 묶음에 없는 인용: LNOPE@20260101#제1조" in prompts[1]  # 위반을 두 번째 프롬프트에 넘긴다


def test_second_violation_gives_partial_answer(agent_deps):
    graph = build_main_graph(agent_deps(write=lambda prompt: BAD), InMemorySaver())
    out = graph.invoke({"text": "DEMO0001 어디야?"}, cfg("t7"))
    assert "끝까지 확인하지 못했어요" in out["answer"]
    assert "DEMO0001: 반입신고 (부산)" in out["answer"]
    assert "나쁜 답이에요." not in out["answer"]  # 검증을 못 넘은 초안은 쓰지 않는다
    assert graph.get_state(cfg("t7")).values["write_attempts"] == 2


def test_second_turn_starts_clean(agent_deps):
    graph = build_main_graph(agent_deps(), InMemorySaver())
    graph.invoke({"text": "DEMO0001 어디야?"}, cfg("t8"))
    graph.invoke({"text": "DEMO0002 어디야?"}, cfg("t8"))
    values = graph.get_state(cfg("t8")).values
    assert values["write_attempts"] == 1 and values["llm_calls"] == 1
