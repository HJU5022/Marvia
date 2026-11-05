"""질문이나 화물 단서 하나로 에이전트 전체를 돌려 답과 LLM 사용량을 본다 (계획 3a·3c Task 8). 돈이 든다.

키 두 개(MARVIA_ANTHROPIC_API_KEY, MARVIA_VOYAGE_API_KEY), 로컬 DB, 색인(계획 2 Task 10)이 필요하다.
실행: uv run python scripts/try_agent.py "DEMO0001 언제까지 수입신고 해야 해요?"
      MARVIA_LOOP=agent uv run python scripts/try_agent.py "..."   (도구 루프 길, 계획 3c)
하지 않는 일: 저장(InMemorySaver·InMemoryStore라 끄면 사라진다), 비용 계산(scripts/compare_loops.py가 한다).
"""

import sys

from langchain_core.callbacks import get_usage_metadata_callback
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from marvia.config import Settings
from marvia.db import connect
from marvia.graph.live import agent_deps
from marvia.graph.main import build_main_graph
from marvia.graph.resume import approval_reply
from marvia.identify.mask import unmask

settings = Settings()
config = {"configurable": {"thread_id": "try-agent"}}
# [왜] get_usage_metadata_callback: 이 블록 안의 LLM 호출(RAG 서브그래프 안 포함)의 토큰 수를 모델별로 더한다
with connect(settings.database_url) as conn, get_usage_metadata_callback() as usage:
    graph = build_main_graph(
        agent_deps(settings, conn),
        InMemorySaver(),
        loop=settings.loop,
        store=InMemoryStore(),
        permission_mode=settings.permission_mode,
    )
    # [왜] 인자 없이 돌리면 대표 화물 질문 하나로 돈다 (try_main.py와 같은 방식)
    out = graph.invoke({"text": " ".join(sys.argv[1:]) or "DEMO0001 언제까지 수입신고 해야 해요?"}, config)
    while "__interrupt__" in out:
        value = out["__interrupt__"][0].value
        # [주의] 화면(여기서는 터미널)에 보일 때만 토큰을 실제 번호로 되돌린다
        mask_map = graph.get_state(config).values.get("mask_map", {})
        if "action_requests" in value:
            # 승인 요청 (설계 6.3의 승인 통로): 승인하거나 거절한다
            for request in value["action_requests"]:
                print("승인 요청:", request["name"], unmask(str(request["args"]), mask_map))
                print(unmask(request.get("description", ""), mask_map))
            approve = input("승인(a) / 거절(그 밖): ").strip() == "a"
            decision = (
                {"type": "approve"} if approve else {"type": "reject", "message": "사용자가 거절했어요"}
            )
            # [왜] 모양이 틀린 승인 값은 라이브러리 안에서 오류가 난다. approval_reply가 거절로 바꾼다
            names = [request["name"] for request in value["action_requests"]]
            reply = approval_reply({"decisions": [decision] * len(names)}, len(names), names)
            out = graph.invoke(Command(resume=reply), config)
            continue
        # 선택지 질문 (설계 6.3의 질문 통로): 번호, 직접 입력, 빈 줄(권장안으로 진행)
        print(unmask(value["question"], mask_map))
        for i, option in enumerate(value["options"]):
            mark = " (권장)" if i == value["recommended"] else ""
            print(f"  {i}. {unmask(option['label'], mask_map)}{mark}")
        pick = input("번호를 고르거나 직접 입력, 빈 줄이면 권장안: ").strip()
        reply = {"selected": int(pick)} if pick.isdigit() else {"custom": pick} if pick else {"timeout": True}
        out = graph.invoke(Command(resume=reply), config)
    values = graph.get_state(config).values

print(out["answer"])
print()
if settings.loop == "agent":
    print("할 일:", " / ".join(f"{t['content']}({t['status']})" for t in values.get("todos", [])) or "없음")
    tools = [c["name"] for m in values.get("messages", []) for c in getattr(m, "tool_calls", None) or []]
    print("도구 호출:", ", ".join(tools) or "없음")
else:
    print("할 일:", " → ".join(f"{step['action']}({step['status']})" for step in values.get("plan", [])))
print("LLM 호출(그래프가 센 수):", values.get("llm_calls"), "/ 작성 횟수:", values.get("write_attempts"))
if values.get("verification"):
    print("마지막 검증 위반:", values["verification"])
for model, tokens in usage.usage_metadata.items():
    print(f"{model}: 입력 {tokens['input_tokens']} 토큰, 출력 {tokens['output_tokens']} 토큰")
