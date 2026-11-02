"""질문이나 화물 단서 하나로 에이전트 전체를 돌려 답과 LLM 사용량을 본다 (계획 3a Task 8). 돈이 든다.

키 두 개(MARVIA_ANTHROPIC_API_KEY, MARVIA_VOYAGE_API_KEY), 로컬 DB, 색인(계획 2 Task 10)이 필요하다.
실행: uv run python scripts/try_agent.py "DEMO0001 언제까지 수입신고 해야 해요?"
하지 않는 일: 저장(InMemorySaver라 끄면 대화가 사라진다), 비용 계산(토큰 수만 찍는다).
단가는 계획 3a 문서 Task 8의 표를 본다.
"""

import sys

from langchain_core.callbacks import get_usage_metadata_callback
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from marvia.config import Settings
from marvia.db import connect
from marvia.graph.live import agent_deps
from marvia.graph.main import build_main_graph

settings = Settings()
config = {"configurable": {"thread_id": "try-agent"}}
# [왜] get_usage_metadata_callback: 이 블록 안의 LLM 호출(RAG 서브그래프 안 포함)의 토큰 수를 모델별로 더한다
with connect(settings.database_url) as conn, get_usage_metadata_callback() as usage:
    graph = build_main_graph(agent_deps(settings, conn), InMemorySaver())
    # [왜] 인자 없이 돌리면 대표 화물 질문 하나로 돈다 (try_main.py와 같은 방식)
    out = graph.invoke({"text": " ".join(sys.argv[1:]) or "DEMO0001 언제까지 수입신고 해야 해요?"}, config)
    # 멈췄으면 선택지를 보여 주고 답을 받아 재개한다 (scripts/try_main.py와 같은 방식)
    while "__interrupt__" in out:
        question = out["__interrupt__"][0].value
        print(question["question"])
        for i, option in enumerate(question["options"]):
            mark = " (권장)" if i == question["recommended"] else ""
            print(f"  {i}. {option['label']}{mark}")
        pick = input("번호를 고르거나 직접 입력: ").strip()
        reply = {"selected": int(pick)} if pick.isdigit() else {"custom": pick}
        out = graph.invoke(Command(resume=reply), config)
    values = graph.get_state(config).values

print(out["answer"])
print()
print("할 일:", " → ".join(f"{step['action']}({step['status']})" for step in values.get("plan", [])))
print("LLM 호출(그래프가 센 상한):", values.get("llm_calls"), "/ 작성 횟수:", values.get("write_attempts"))
if values.get("verification"):
    print("마지막 검증 위반:", values["verification"])
for model, tokens in usage.usage_metadata.items():
    print(f"{model}: 입력 {tokens['input_tokens']} 토큰, 출력 {tokens['output_tokens']} 토큰")
