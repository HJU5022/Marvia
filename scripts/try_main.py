"""메인 그래프가 멈췄다가 내 답으로 이어 가는 것을 터미널에서 본다.

실행: uv run python scripts/try_main.py MOCK12345678TEST87654321
하지 않는 일: 저장. 메모리 서랍(InMemorySaver)이라 프로그램을 끄면 대화가 사라진다 (Postgres는 Task 8).
LLM과 법령 검색도 부르지 않는다. 계획자·작성자 자리에 고정 답을 넣어 키 없이 흐름(멈춤·재개)만 본다.
"""

import sys

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from marvia.graph.main import AgentDeps, build_main_graph
from marvia.graph.rag import RagDeps
from marvia.graph.schemas import Draft, Plan, Step


def unused(*args):
    """계획자가 법령 검색·품목 사실 뽑기를 고르지 않으므로 불리지 않는 자리."""
    raise RuntimeError("try_main.py는 법령 검색·품목 사실 뽑기를 하지 않는다")


OFFLINE = Draft(answer="(작성자 LLM 없이 돌린 시험 답)", citations=[], next_options=[], forwarder_message="")
WRITE_NOW = Plan(steps=[Step(action="write", query="", reason="시험")])
deps = AgentDeps(
    rag=RagDeps(analyze=unused, search=unused, rerank=unused, grade=unused, rewrite=unused),
    plan=lambda prompt: WRITE_NOW,
    item=unused,  # 계획자가 품목 사실 뽑기도 고르지 않는다
    write=lambda prompt: OFFLINE,
)
graph = build_main_graph(deps, InMemorySaver())
# [왜] thread_id는 서류 번호다. 멈춘 대화를 다시 찾을 때 같은 번호를 써야 한다
config = {"configurable": {"thread_id": "try"}}
out = graph.invoke({"text": " ".join(sys.argv[1:]) or "MOCK12345678TEST87654321"}, config)
# 멈췄으면 결과에 __interrupt__가 들어 있다. 답을 받아 재개하고, 또 멈추면 다시 묻는다
while "__interrupt__" in out:
    question = out["__interrupt__"][0].value
    print(question["question"])
    for i, option in enumerate(question["options"]):
        mark = " (권장)" if i == question["recommended"] else ""
        print(f"  {i}. {option['label']}{mark}")
    pick = input("번호를 고르거나 직접 입력: ").strip()
    reply = {"selected": int(pick)} if pick.isdigit() else {"custom": pick}
    out = graph.invoke(Command(resume=reply), config)  # 같은 thread_id로 재개
print(out["answer"])
