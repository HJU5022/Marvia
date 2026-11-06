"""같은 질문을 계획자 길과 에이전트 길로 돌려 답 종류·LLM 호출·토큰·비용·시간을 잰다 (계획 3c Task 8).

돈이 든다.

키 두 개, 로컬 DB, 색인이 필요하다. 묻는 질문에는 권장안으로(시간 초과와 같은 값),
승인 요청에는 거절로 답한다.
실행: uv run python scripts/compare_loops.py 결과.json
하지 않는 일: 정답 채점(평가셋은 계획 4). 답 글은 결과 파일에 남겨 사람이 읽는다.
"""

import json
import sys
import time

import psycopg
from langchain_core.callbacks import BaseCallbackHandler, get_usage_metadata_callback
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from marvia.config import Settings
from marvia.db import connect
from marvia.graph.live import agent_deps
from marvia.graph.main import build_main_graph
from marvia.graph.resume import approval_reply
from marvia.tools.rules import load_rules

# 0.1 손 시험(11-06)과 같은 다섯 질문
QUESTIONS = [
    "DEMO0001 언제까지 수입신고 해야 해요?",
    "실리콘 주방매트를 처음 수입할 때 식약처에 무엇을 신고해야 하나요?",
    "수입 화물이 검사대상으로 지정되면 어떤 절차를 거치나요?",
    "같은 제품을 다시 수입하면 정밀검사를 면제받을 수 있나요?",
    "다음 주에 칭다오에서 고추 와요. 어디쯤 왔어요?",
]


class CallCounter(BaseCallbackHandler):
    """채팅 모델 호출을 실제로 센다 (RAG 안의 호출과 작성자 호출 포함)."""

    def __init__(self):
        self.calls = 0

    def on_chat_model_start(self, *args, **kwargs):
        self.calls += 1


def run(graph, text: str, thread: str, counter: CallCounter) -> tuple[dict, list[dict]]:
    """질문 하나를 끝까지 돌린다. 멈추면 권장안·거절로 이어 가고, 멈춘 내용을 함께 돌려준다."""
    config = {"configurable": {"thread_id": thread}, "callbacks": [counter]}
    out = graph.invoke({"text": text}, config)
    pauses = []
    while "__interrupt__" in out:
        value = out["__interrupt__"][0].value
        pauses.append(value)
        if "action_requests" in value:
            count = len(value["action_requests"])
            reply = approval_reply(
                {"decisions": [{"type": "reject", "message": "비교 실행은 저장하지 않는다"}] * count}, count
            )
        else:
            reply = {"timeout": True}
        out = graph.invoke(Command(resume=reply), config)
    return graph.get_state({"configurable": {"thread_id": thread}}).values | {"answer": out["answer"]}, pauses


def kind(answer: str, evidence_count: int, calc: dict) -> str:
    """답 종류: 거절, 부분 답, 정상 답, 근거 없는 답."""
    if answer.startswith("이 질문은 Marvia가 도울 수 있는 범위 밖"):
        return "decline"
    if "끝까지 확인하지 못했어요" in answer:
        return "partial"
    # [왜] 근거도 계산 값도 없이 나간 답은 정상 답으로 세지 않는다 (R-014: 검색이 모두 실패한 뒤의 답)
    return "full" if evidence_count or any(calc.values()) else "no_evidence"


settings = Settings()
prices = load_rules("pricing")
rows = []
with (
    connect(settings.database_url) as conn,
    # [왜] 감시 목록은 따로 autocommit 연결을 쓴다. 다른 도구가 conn을 되돌려도 감시 줄이 남는다 (R-041)
    psycopg.connect(settings.database_url, autocommit=True) as watch_conn,
):
    for loop in ("planner", "agent"):
        graph = build_main_graph(
            agent_deps(settings, conn, watch_conn), InMemorySaver(), loop=loop, store=InMemoryStore()
        )
        for i, text in enumerate(QUESTIONS):
            started = time.monotonic()
            counter = CallCounter()
            try:
                with get_usage_metadata_callback() as usage:
                    values, pauses = run(graph, text, f"{loop}-{i}", counter)
                tokens = usage.usage_metadata
                # [왜] 가격표(rules/pricing.yaml)에 없는 모델이면 KeyError로 죽지 않고 비용을 None으로 남긴다
                cost = (
                    sum(
                        t["input_tokens"] * prices[m]["input"] / 1e6
                        + t["output_tokens"] * prices[m]["output"] / 1e6
                        for m, t in tokens.items()
                    )
                    if all(m in prices for m in tokens)
                    else None
                )
                messages = values.get("messages", [])
                # [왜] 모델이 본 글·도구 인자·할 일·멈춤 내용에 실제 번호가 있었는지 코드로 확인한다
                #      (fixture 번호는 DEMO 접두어)
                seen = str([[m.content, getattr(m, "tool_calls", None)] for m in messages])
                seen += str(values.get("todos", [])) + str(pauses)
                rows.append(
                    {
                        "loop": loop,
                        "question": text,
                        "kind": kind(
                            values["answer"], len(values.get("evidence", [])), values.get("calc", {})
                        ),
                        "llm_calls": values.get("llm_calls"),
                        "real_llm_calls": counter.calls,
                        "evidence_count": len(values.get("evidence", [])),
                        "calc_keys": [k for k, v in values.get("calc", {}).items() if v],
                        "write_attempts": values.get("write_attempts"),
                        "tokens": {
                            m: {"in": t["input_tokens"], "out": t["output_tokens"]} for m, t in tokens.items()
                        },
                        "cost_usd": None if cost is None else round(cost, 5),
                        "seconds": round(time.monotonic() - started, 1),
                        "pauses": len(pauses),
                        "tool_calls": [
                            c["name"] for m in messages for c in getattr(m, "tool_calls", None) or []
                        ],
                        "todos": values.get("todos", []),
                        "assumptions": values.get("assumptions", []),
                        "failed_tools": values.get("failed_tools", []),
                        "verification": values.get("verification", []),
                        "leak": "DEMO000" in seen,
                        "answer": values["answer"],
                    }
                )
            except Exception as error:  # [왜] 한 질문이 실패해도 돈을 낸 나머지 결과를 잃지 않는다
                rows.append(
                    {
                        "loop": loop,
                        "question": text,
                        "kind": "error",
                        "error": type(error).__name__,
                        "seconds": round(time.monotonic() - started, 1),
                    }
                )
            print(
                loop,
                i,
                rows[-1]["kind"],
                rows[-1].get("llm_calls"),
                rows[-1].get("cost_usd"),
                rows[-1]["seconds"],
            )

summary = {
    loop: {
        "full": sum(r["kind"] == "full" for r in rows if r["loop"] == loop),
        "partial": sum(r["kind"] == "partial" for r in rows if r["loop"] == loop),
        "no_evidence": sum(r["kind"] == "no_evidence" for r in rows if r["loop"] == loop),
        "decline": sum(r["kind"] == "decline" for r in rows if r["loop"] == loop),
        "errors": sum(r["kind"] == "error" for r in rows if r["loop"] == loop),
        "cost_usd": round(sum(r.get("cost_usd") or 0 for r in rows if r["loop"] == loop), 4),
        "llm_calls": [r["llm_calls"] for r in rows if r["loop"] == loop and "llm_calls" in r],
        "real_llm_calls": [r["real_llm_calls"] for r in rows if r["loop"] == loop and "real_llm_calls" in r],
        "max_llm_calls": max(
            (r["llm_calls"] for r in rows if r["loop"] == loop and "llm_calls" in r), default=None
        ),
        "max_cost_usd": max(
            (r["cost_usd"] for r in rows if r["loop"] == loop and r.get("cost_usd") is not None),
            default=None,
        ),
        "leaks": sum(r.get("leak", False) for r in rows if r["loop"] == loop),
    }
    for loop in ("planner", "agent")
}
print(json.dumps(summary, ensure_ascii=False))
with open(sys.argv[1] if len(sys.argv) > 1 else "/dev/stdout", "w", encoding="utf-8") as f:
    json.dump({"summary": summary, "rows": rows}, f, ensure_ascii=False, indent=1)
