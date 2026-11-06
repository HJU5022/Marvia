"""평가셋 문항 하나를 그래프로 끝까지 돌려 채점에 쓸 줄을 만든다 (done 3.2·3.7).

돈이 드는 실행은 scripts/run_eval.py가 한다.
하지 않는 일: 채점(metrics.py), 그래프 코드 바꾸기. 바깥 기능(AgentDeps)만 감싼다:
오늘 날짜를 평가셋 기준일로 고정하고, RAG의 근거 채점과 질의 고쳐 쓰기 결과를 적고(done 3.3),
문항에 fault가 있으면 검색과 조문 조회를 끊는다.
[주의] 줄(row)에는 파생 값(행동, unit_id, 날짜, 도구 이름, 수)만 둔다. 답 글과 근거 글은 raw로 따로 돌려주고
       저장소에 넣지 않는다 (CLAUDE.md: 실제 API 응답을 저장소에 넣지 않는다).
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import replace
from datetime import date
from pathlib import Path

import httpx
import psycopg
from langchain_core.callbacks import BaseCallbackHandler, get_usage_metadata_callback
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from marvia.eval.dataset import Item
from marvia.graph.answer import PARTIAL_LEAD
from marvia.graph.main import AgentDeps, build_main_graph
from marvia.graph.resume import approval_reply
from marvia.rag.models import Evidence
from marvia.tools.rules import load_rules

# 근거 채점 프롬프트의 근거 줄 머리 [L001556@20261002#제241조.3항] (graph/rag.py evidence_block)
UNIT_ID = re.compile(r"\[([A-Z]\d+@\d{8}#[^\]\s]+)\]")
ARTICLE = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")


def articles(text: str) -> list[str]:
    """글에 나온 조문 번호를 "제248조", "제1조의4" 모양으로 모은다."""
    return [f"제{n}조" + (f"의{sub}" if sub else "") for n, sub in ARTICLE.findall(text)]


class LlmWatch(BaseCallbackHandler):
    """채팅 모델 호출을 실제로 세고 입력 글을 모은다 (RAG 안, 작성자, 조사 서브에이전트 호출 포함)."""

    def __init__(self) -> None:
        self.calls = 0
        self.inputs: list[str] = []

    def on_chat_model_start(self, serialized, messages, **kwargs) -> None:
        self.calls += 1
        # [왜] 실행이 끝난 뒤 가림 표의 실제 번호가 어떤 LLM 입력에라도 있었는지 본다 (설계 12절)
        self.inputs.append(str(messages))


def eval_deps(deps: AgentDeps, item: Item, today: date, log: list[dict]) -> AgentDeps:
    """평가 실행용 AgentDeps. 감시 목록은 끄고(평가는 DB 감시 표를 건드리지 않는다), 날짜를 고정한다."""
    rag = deps.rag
    real_provision = deps.provision

    def grade(prompt: str):
        result = rag.grade(prompt)
        # [왜] 그 채점이 본 근거를 글 없이 이름만 남긴다 (11-02: 별표 없이 "충분"이라 했다)
        log.append({"step": "grade", "sufficient": result.sufficient, "units": UNIT_ID.findall(prompt)})
        return result

    def rewrite(prompt: str):
        result = rag.rewrite(prompt)
        # [주의] 고친 질의(LLM 글)는 남기지 않고 조문 번호만 남긴다 (11-02: 질문과 관계없는 조문이 끼었다)
        log.append({"step": "rewrite", "articles": articles(result.search_query)})
        return result

    def search(query: str, as_of: date) -> list[Evidence]:
        if item.fault == "search":
            raise httpx.ConnectError("평가 실행이 검색을 일부러 끊었다")
        return rag.search(query, as_of)

    def provision(label: str, as_of: date) -> list[Evidence]:
        if item.fault == "search":
            raise psycopg.OperationalError("평가 실행이 조문 조회를 일부러 끊었다")
        assert real_provision is not None
        return real_provision(label, as_of)

    return replace(
        deps,
        rag=replace(rag, grade=grade, rewrite=rewrite, search=search),
        provision=provision if real_provision else None,
        today=lambda: today,
        watch=None,
    )


def drive(graph, item: Item, thread: str, callbacks: list) -> tuple[dict, list[dict]]:
    """문항 하나를 끝까지 돌린다. 질문에는 권장안(시간 초과와 같은 값)으로, 승인 요청에는 거절로 잇는다."""
    config = {"configurable": {"thread_id": thread}, "callbacks": callbacks}
    out = graph.invoke({"text": item.question}, config)
    pauses = []
    while "__interrupt__" in out:
        value = out["__interrupt__"][0].value
        pauses.append(value)
        if "action_requests" in value:
            count = len(value["action_requests"])
            reject = {"type": "reject", "message": "평가 실행은 저장하지 않는다"}
            reply = approval_reply({"decisions": [reject] * count}, count)
        else:
            reply = {"timeout": True}
        out = graph.invoke(Command(resume=reply), config)
    return graph.get_state({"configurable": {"thread_id": thread}}).values, pauses


def behaviour(values: dict, pauses: list[dict]) -> str:
    """답 모양으로 행동을 정한다 (dataset.Behaviour). 앞의 조건이 먼저다."""
    answer = values.get("answer", "")
    draft = values.get("draft") or {}
    if any(p.get("kind") == "choice" for p in pauses):
        return "choice"
    if load_rules("agent")["scope"]["decline"] in answer:
        return "decline"
    if PARTIAL_LEAD in answer:
        return "partial"
    if draft.get("forwarder_message"):
        return "guide"
    found = any(cargo.get("facts") for cargo in values.get("cargos", []))
    if draft.get("citations") or any((values.get("calc") or {}).values()) or found:
        return "answer"
    return "unsupported"


def cost_usd(tokens: dict, prices: dict) -> float | None:
    """모델별 토큰 수 × 단가(rules/pricing.yaml). 가격표에 없는 모델이 있으면 None."""
    if not all(model in prices for model in tokens):
        return None
    return round(
        sum(
            t["in"] * prices[m]["input"] / 1e6 + t["out"] * prices[m]["output"] / 1e6
            for m, t in tokens.items()
        ),
        6,
    )


def observe(values: dict, pauses: list[dict], watch: LlmWatch, loop: str, log: list[dict]) -> dict:
    """끝난 실행의 공책 칸에서 채점에 쓸 파생 값만 뽑는다."""
    draft = values.get("draft") or {}
    kind = behaviour(values, pauses)
    calc = values.get("calc") or {}
    messages = values.get("messages", [])
    numbers = [n for n in values.get("mask_map", {}).values() if n]
    return {
        "behaviour": kind,
        # [왜] 인용은 검증을 지난 답에만 있다. 부분 답의 "찾은 근거"는 인용이 아니다
        "cited": list(draft.get("citations", [])) if kind in ("answer", "guide") else [],
        "evidence": [e["unit_id"] for e in values.get("evidence", [])],  # 점수 높은 순 (merge_evidence)
        # [왜] R@k·MRR은 RAG 순위로 잰다. 묶음은 get_provision 근거(점수 1.0)가 앞선다
        "retrieved": list(dict.fromkeys(u for e in log if e["step"] == "grade" for u in e["units"])),
        "calc": {
            "deadlines": [{"name": d["name"], "due": d["due"]} for d in calc.get("deadlines", [])],
            "reimport": (calc.get("reimport") or {}).get("verdict"),
        },
        "tools": [c["name"] for m in messages for c in getattr(m, "tool_calls", None) or []],
        "plan": [step["action"] for step in values.get("plan", [])] if loop == "planner" else [],
        "llm_calls": values.get("llm_calls"),
        "failed": [f"{t['tool']}: {t['message']}" for t in values.get("failed_tools", [])],
        "leak": any(n in text for n in numbers for text in watch.inputs),
    }


def evaluate_item(
    deps: AgentDeps, item: Item, loop: str, today: date, prices: dict, *, permission_mode: str = "ask"
) -> tuple[dict, dict]:
    """문항 하나를 새 대화로 돌려 (줄, raw)를 돌려준다. 예외가 나도 줄을 남긴다."""
    log: list[dict] = []
    graph = build_main_graph(
        eval_deps(deps, item, today, log),
        InMemorySaver(),
        loop=loop,
        store=InMemoryStore(),
        permission_mode=permission_mode,
    )
    watch = LlmWatch()
    started = time.monotonic()
    row: dict = {"id": item.id, "loop": loop}
    raw: dict = {"id": item.id, "loop": loop}
    usage = None
    try:
        with get_usage_metadata_callback() as usage:
            values, pauses = drive(graph, item, f"eval-{loop}-{item.id}", [watch])
        row |= observe(values, pauses, watch, loop, log)
        row["error"] = None
        draft = values.get("draft") or {}
        top = load_rules("eval")["ragas"]["contexts"]
        # [주의] raw는 저장소에 넣지 않는다 (scripts/run_eval.py가 저장소 밖에 쓴다). 질문·초안은 가린 글이다
        raw |= {
            # [왜] ragas는 화면에 나간 초안만 잰다. 부분 답이면 검증을 넘지 못한 초안은 쓰지 않았다
            "behaviour": row["behaviour"],
            "question": values.get("masked_text", ""),
            "draft": draft.get("answer", ""),
            "answer": values.get("answer", ""),
            "contexts": [e["text"] for e in values.get("evidence", [])[:top]],
        }
    except (
        Exception
    ) as error:  # [왜] 한 문항이 실패해도 돈을 낸 나머지 결과를 잃지 않는다 (compare_loops와 같다)
        row |= {
            "behaviour": "error",
            "cited": [],
            "evidence": [],
            "retrieved": [],
            "calc": {},
            "tools": [],
            "plan": [],
        }
        row |= {"llm_calls": None, "failed": [], "leak": False, "error": type(error).__name__}
    # [왜] 실패한 문항도 그때까지 쓴 토큰은 센다. 돈은 이미 나갔다
    spent = usage.usage_metadata if usage is not None else {}
    tokens = {m: {"in": t["input_tokens"], "out": t["output_tokens"]} for m, t in spent.items()}
    row |= {
        "rag": log,
        "real_llm_calls": watch.calls,
        "tokens": tokens,
        "cost_usd": cost_usd(tokens, prices),
        "seconds": round(time.monotonic() - started, 1),
    }
    return row, raw


def estimate(items: int, loops: list[str], models: list[str], prices: dict) -> list[dict]:
    """돈이 드는 실행 전에 보일 어림 비용. 문항당 토큰은 rules/eval.yaml의 지난 측정값이다."""
    per = load_rules("eval")["estimate"]
    rows = []
    for model in models:
        price = prices.get(model)
        each = (
            None if price is None else (per["input"] * price["input"] + per["output"] * price["output"]) / 1e6
        )
        rows += [
            {
                "loop": loop,
                "model": model,
                "items": items,
                "usd": None if each is None else round(each * items, 3),
            }
            for loop in loops
        ]
    return rows


def preflight(items: int, loops: list[str], models: list[str], prices: dict, max_cost: float) -> list[str]:
    """유료 호출 전에 막을 까닭들. 단가 없는 모델이나 상한을 넘는 어림 비용이면 비어 있지 않다."""
    problems = [f"단가표(rules/pricing.yaml)에 없는 모델: {m}" for m in models if m not in prices]
    if problems:
        return problems
    total = sum(line["usd"] for line in estimate(items, loops, models, prices))
    if total > max_cost:
        problems.append(f"어림 비용 ${total:.3f}가 상한 ${max_cost}를 넘는다")
    return problems


def stop_reason(row: dict) -> str | None:
    """돈이 새는 줄이면 실행을 멈출 까닭. 비용을 못 셌거나 호출이 있는데 토큰이 없으면 상한이 듣지 않는다."""
    if row["cost_usd"] is None:
        return "비용을 셀 수 없다 (단가표에 없는 모델 이름)"
    if row["real_llm_calls"] and not row["tokens"]:
        return "LLM 호출은 있는데 토큰 사용량이 없다"
    return None


def result_name(loop: str, model: str, tag: str) -> str:
    """결과 파일의 이름 줄기. 파일은 <줄기>.json과 <줄기>.raw.json이다."""
    return f"{loop}-{model}" + (f"-{tag}" if tag else "")


def existing_results(out: Path, loops: list[str], models: list[str], tag: str) -> list[Path]:
    """쓸 결과 파일 가운데 이미 있는 것. [왜] 덮어쓰면 돈을 낸 원본을 잃는다 (v1 f073f5e)"""
    names = [result_name(loop, model, tag) for model in models for loop in loops]
    return [
        out / f"{n}{ext}" for n in names for ext in (".json", ".raw.json") if (out / f"{n}{ext}").exists()
    ]


def inside_repo(out: Path) -> bool:
    """결과 폴더가 저장소 안인가. [왜] raw에는 답 글이 있어 저장소에 들어가면 안 된다 (CLAUDE.md)"""
    return out.resolve().is_relative_to(Path(__file__).resolve().parents[3])


def save_result(out: Path, name: str, meta: dict, summary: dict, rows: list[dict], raws: list[dict]) -> None:
    """결과 파일 둘(<이름>.json, <이름>.raw.json)을 통째로 다시 쓴다. 문항마다 불러 멈춰도 남게 한다."""
    result = {"meta": meta, "summary": summary, "rows": rows}
    (out / f"{name}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / f"{name}.raw.json").write_text(json.dumps(raws, ensure_ascii=False, indent=1), encoding="utf-8")
