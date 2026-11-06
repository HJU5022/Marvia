"""질문이나 화물 단서 하나로 에이전트 전체를 돌려 답과 LLM 사용량을 본다 (계획 3a·3c Task 8). 돈이 든다.

키 세 개(MARVIA_ANTHROPIC_API_KEY, MARVIA_VOYAGE_API_KEY, 저장 데이터 암호화 MARVIA_DATA_KEY), 로컬 DB,
색인(계획 2 Task 10)이 필요하다.
실행: uv run python scripts/try_agent.py "DEMO0001 언제까지 수입신고 해야 해요?"
      MARVIA_LOOP=agent uv run python scripts/try_agent.py "..."   (도구 루프 길, 계획 3c)
      MARVIA_LOOP=agent uv run python scripts/try_agent.py --thread t1 "그 화물 납부 기한은?"
        (같은 --thread로 다시 돌리면 앞 차례 기록과 가림 표를 이어 쓴다, 계획 3d)
      MARVIA_LOOP=agent uv run python scripts/try_agent.py --image bl.png "이 화물 지금 어디야?"
        (사진은 이 컴퓨터에서 OCR로 읽고 번호 덩어리만 질문 앞에 붙인다. Docker 안에서 돌린다)
대화 기록(암호화)과 장기 기억은 로컬 Postgres에 남는다(live_memory).
하지 않는 일: 비용 계산(scripts/compare_loops.py).
"""

import argparse
import sys

import psycopg
from langchain_core.callbacks import get_usage_metadata_callback
from langgraph.types import Command

from marvia.config import Settings
from marvia.db import connect, read_pool
from marvia.graph.live import agent_deps, live_memory
from marvia.graph.main import build_main_graph
from marvia.graph.resume import approval_reply
from marvia.identify.mask import unmask
from marvia.identify.ocr import photo_clues, read_image
from marvia.watch import watch_keys

parser = argparse.ArgumentParser(description="에이전트를 한 차례 돌린다")
parser.add_argument("question", nargs="*", help="질문 (없으면 대표 화물 질문)")
parser.add_argument("--thread", default="try-agent", help="대화 id. 같은 값이면 앞 차례를 이어 간다")
parser.add_argument("--user", default="local", help="장기 기억을 나누는 사용자 id")
parser.add_argument("--image", help="서류 사진 경로. 이 컴퓨터에서 읽어 번호 덩어리만 질문 앞에 붙인다")
args = parser.parse_args()
# [왜] 인자 없이 돌리면 대표 화물 질문 하나로 돈다 (try_main.py와 같은 방식)
text = " ".join(args.question) or "DEMO0001 언제까지 수입신고 해야 해요?"
if args.image:
    # [주의] 사진은 밖으로 보내지 않는다. 사진 글의 상호·주소도 넘기지 않고 번호 덩어리만 붙인다 (설계 4.2)
    text = f"{photo_clues(read_image(args.image))} {text}"

settings = Settings()
try:
    watch_keys(settings.data_key.get_secret_value())
except ValueError:
    # [왜] 이 키가 대화 기록과 감시 표의 실제 번호를 암호화한다. 없거나 틀리면 DB에 닿기 전에 멈춘다
    # [주의] 키 값은 출력하지 않는다
    print("MARVIA_DATA_KEY가 없거나 올바른 키가 아닙니다. .env를 확인한 뒤 다시 실행하세요.")
    sys.exit(1)
config = {"configurable": {"thread_id": args.thread, "user_id": args.user}}
# [왜] get_usage_metadata_callback: 이 블록 안의 LLM 호출(RAG 서브그래프 안 포함)의 토큰 수를 모델별로 더한다
with (
    connect(settings.database_url),  # [왜] 표가 없으면 만든다(마이그레이션). 읽기는 아래 풀로 한다
    read_pool(settings.database_url) as pool,
    # [왜] 감시 목록은 따로 autocommit 연결을 쓴다. 다른 도구가 검색 연결을 되돌려도 감시 줄이 남는다 (R-041)
    psycopg.connect(settings.database_url, autocommit=True) as watch_conn,
    live_memory(settings.database_url, settings.data_key.get_secret_value()) as (saver, store),
    get_usage_metadata_callback() as usage,
):
    graph = build_main_graph(
        agent_deps(settings, pool, watch_conn),
        saver,
        loop=settings.loop,
        store=store,
        permission_mode=settings.permission_mode,
    )
    out = graph.invoke({"text": text}, config)
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
    messages = values.get("messages", [])
    # [왜] 기록은 차례를 넘어 이어진다. 이번 차례 질문(마지막 사람 메시지) 뒤의 호출만 센다
    last = max((i for i, m in enumerate(messages) if m.type == "human"), default=-1)
    tools = [c["name"] for m in messages[last + 1 :] for c in getattr(m, "tool_calls", None) or []]
    print("도구 호출:", ", ".join(tools) or "없음")
else:
    print("할 일:", " → ".join(f"{step['action']}({step['status']})" for step in values.get("plan", [])))
print("LLM 호출(그래프가 센 수):", values.get("llm_calls"), "/ 작성 횟수:", values.get("write_attempts"))
if values.get("verification"):
    print("마지막 검증 위반:", values["verification"])
for model, tokens in usage.usage_metadata.items():
    print(f"{model}: 입력 {tokens['input_tokens']} 토큰, 출력 {tokens['output_tokens']} 토큰")
