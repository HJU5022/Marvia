"""메인 그래프가 멈췄다가 내 답으로 이어 가는 것을 터미널에서 본다.

실행: uv run python scripts/try_main.py MOCK12345678TEST87654321
하지 않는 일: 저장. 메모리 서랍(InMemorySaver)이라 프로그램을 끄면 대화가 사라진다 (Postgres는 Task 8).
"""

import sys

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from marvia.graph.main import build_main_graph

graph = build_main_graph(InMemorySaver())
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
