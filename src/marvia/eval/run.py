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
from collections.abc import Sequence
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
from marvia.graph.answer import NOT_FOUND_LEAD, PARTIAL_LEAD, cargo_lines
from marvia.graph.main import AgentDeps, build_main_graph
from marvia.graph.resume import approval_reply
from marvia.identify.mask import mask_text
from marvia.llm import CLIFailed
from marvia.rag.models import Evidence
from marvia.tools.rules import load_rules
from marvia.watch import WatchDeps

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
        self.cli_failures: list[str] = []

    def on_chat_model_start(self, serialized, messages, **kwargs) -> None:
        self.calls += 1
        # [왜] 실행이 끝난 뒤 가림 표의 실제 번호가 어떤 LLM 입력에라도 있었는지 본다 (설계 12절)
        self.inputs.append(str(messages))

    def on_llm_error(self, error, **kwargs) -> None:
        # [왜] 그래프는 모델 실패를 부분 답으로 바꾼다. `claude -p` 실패(사용량 한도, 시간 초과)는 모델의
        #      행동이 아니라 측정 실패라, 줄의 error에 남겨 그 실행을 무효로 만든다 (run_problems)
        if isinstance(error, CLIFailed):
            self.cli_failures.append(f"CLIFailed: {error}")


def eval_deps(
    deps: AgentDeps, item: Item, today: date, log: list[dict], seen: dict[str, str] | None = None
) -> AgentDeps:
    """평가 실행용 AgentDeps. 감시 목록은 DB 없는 가짜로 묶고, 날짜를 고정한다."""
    # [왜] 감시 도구가 묶여야 watch_cargo를 막는 궤적 검사(rules/eval.yaml never)가 실제로 걸린다
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

    def watched(find):
        """검색 함수를 감싼다: fault 문항이면 끊고, 그래프 후보 수와 본 글을 적는다."""

        def run(query: str, as_of: date) -> list[Evidence]:
            if item.fault == "search":
                raise httpx.ConnectError("평가 실행이 검색을 일부러 끊었다")
            found = find(query, as_of)
            # [왜] 그래프가 실제로 후보를 더했는지 문항마다 센다. 실행 유효성 검사가 본다 (계획 3b).
            #      [주의] direct 길(search)은 리랭커 앞 후보 수이고, MCP 길(ranked)은 리랭커 뒤 상위 n개
            #      안의 그래프 후보 수다. 유효성 규칙(설정 B에서 > 0)은 둘 다 이 수(graph_added)를 쓴다.
            #      retrieval_check의 "graph" 칸은 늘 리랭커 뒤 수다
            log.append({"step": "search", "graph": sum(e.origin == "graph" for e in found)})
            if seen is not None:
                # [왜] RAG는 시도마다 근거를 갈아 끼운다. 본 글을 그때그때 잡아 둔다 (raw에만 쓴다)
                for e in found:
                    seen.setdefault(e.unit_id, e.text)
            return found

        return run

    def provision(label: str, as_of: date) -> list[Evidence]:
        if item.fault == "search":
            raise psycopg.OperationalError("평가 실행이 조문 조회를 일부러 끊었다")
        assert real_provision is not None
        return real_provision(label, as_of)

    return replace(
        deps,
        rag=replace(
            rag,
            grade=grade,
            rewrite=rewrite,
            search=watched(rag.search),
            ranked=watched(rag.ranked) if rag.ranked else None,
        ),
        provision=provision if real_provision else None,
        today=lambda: today,
        web=None,  # [왜] 평가 결과가 바깥 사이트에 기대면 안 된다. official_lookup은 묶이지 않는다
        watch=WatchDeps(
            add=lambda user, number, stage: None, news=lambda user: [], ack=lambda user, ids: None
        ),
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
    values = graph.get_state({"configurable": {"thread_id": thread}}).values
    # [왜] 답(answer)은 체크포인트에 저장하지 않는 칸이라 get_state에 없다 (R-035).
    #      마지막 invoke 결과에서 읽는다
    return values | {"answer": out.get("answer", "")}, pauses


def behaviour(values: dict, pauses: list[dict], *, not_found: bool = True) -> str:
    """답 모양으로 행동을 정한다 (dataset.Behaviour). 앞의 조건이 먼저다.

    not_found=False면 찾지 못함 규칙 없이 정한다. v1 기준의 행동(behaviour_base)이다.
    """
    answer = values.get("answer", "")
    draft = values.get("draft") or {}
    if any(p.get("kind") == "choice" for p in pauses):
        return "choice"
    if load_rules("agent")["scope"]["decline"] in answer:
        return "decline"
    if PARTIAL_LEAD in answer:
        return "partial"
    if not_found and NOT_FOUND_LEAD in answer:
        return "not_found"
    if draft.get("forwarder_message"):
        return "guide"
    found = any(cargo.get("facts") for cargo in values.get("cargos", []))
    if draft.get("citations") or any((values.get("calc") or {}).values()) or found:
        return "answer"
    return "unsupported"


def llm_meta(llm_via: str) -> dict:
    """결과 meta에 남길 LLM 길과 CLI 판 번호. [왜] CLI로 잰 실행은 API로 잰 실행과 조건이 달라 섞지 않는다."""
    if llm_via != "cli":
        return {"llm_via": llm_via, "llm_cli": None}
    from marvia.cli_model import cli_version  # [왜] API 길은 이 모듈이 필요 없다

    return {"llm_via": llm_via, "llm_cli": cli_version()}


def graph_setting_problem(wanted: str, actual: str) -> str | None:
    """실행 인자(--graph)와 실제 설정(Settings.graph)이 다르면 멈출 까닭. 같으면 None."""
    # [왜] MARVIA_GRAPH가 Docker 안까지 안 넘어가면 "켬" 실행이 꺼진 채 돌고 그래프 규칙은 건너뛰어진다
    return None if wanted == actual else f"--graph {wanted}인데 실제 설정(MARVIA_GRAPH)은 {actual}다"


def run_problems(
    meta: dict, rows: list[dict], summary: dict, faults: set[str], uncovered: list[str] | None = None
) -> list[str]:
    """세기 전에 보는 실행 유효성 (계획 3b 사전 등록). 문제가 있으면 그 실행은 세지 않고 다시 돈다."""
    problems = []
    if uncovered:  # [왜] 상한에서 끊기거나 일부 문항만 돈 실행은 세지 않는다 (metrics.gate_uncovered)
        problems.append(f"평가셋 문항을 다 덮지 못했다: {', '.join(uncovered)}")
    if not meta.get("annex_units"):
        problems.append("DB에 별표 단위가 없다 (scripts/index_corpus.py)")
    if meta.get("graph") == "on":
        graph = meta.get("graph_meta") or {}
        if not graph.get("sha"):
            problems.append("그래프 메타(sha)가 없다 (scripts/build_graph.py)")
        else:
            if graph["sha"] != meta.get("units_sha256"):
                problems.append("그래프가 지금 단위 파일로 만든 것이 아니다 (sha 다름)")
            # [왜] 단위 파일이 같아도 품목 파일이나 간선을 만드는 코드가 바뀌면 그래프는 지금 결과가 아니다.
            #      메타에 이 값이 없는 옛 적재도 지금 결과로 볼 수 없다 (계획 3b 최종 검토 I-2)
            if graph.get("items_sha") != meta.get("items_sha256"):
                problems.append("그래프가 지금 품목 파일로 만든 것이 아니다 (items.yaml sha 다름)")
            if graph.get("refers") != meta.get("refers_expected"):
                problems.append(
                    f"그래프 참조 간선 수가 지금 코드 결과와 다르다 "
                    f"(그래프 {graph.get('refers')}, 코드 {meta.get('refers_expected')})"
                )
        if not sum(r.get("graph_added", 0) for r in rows):
            problems.append("그래프 켬인데 그래프가 더한 후보가 0이다")
    # [왜] 칸이 없는 결과도 무효다. 어떤 모드로 돌았는지 모르면 실제 API를 불렀는지 알 수 없다
    if meta.get("unipass_mode") != "replay":
        problems.append("UNI-PASS 재생 모드가 아니다 (meta.unipass_mode)")
    for key in ("errors", "leaks", "cap_breaches"):
        if summary.get(key):
            problems.append(f"{key} {summary[key]}")
    # [왜] fault 문항(B02)은 검색을 일부러 끊어 실패가 정답이다. 나머지 문항의 검색 길 실패만 센다.
    #      LLM 호출 한도에 닿은 차례("agent: …")는 행동 결과라 여기서 세지 않는다
    search_failed = sorted(
        r["id"]
        for r in rows
        if r["id"] not in faults
        and any(f.startswith(("search_law:", "get_provision:")) for f in r.get("failed", []))
    )
    if search_failed:
        problems.append(f"검색 길이 실패한 문항: {', '.join(search_failed)}")
    return problems


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
        # [왜] v1 채점으로도 같은 줄을 세려고 찾지 못함 규칙 없는 분류를 함께 남긴다
        "behaviour_base": behaviour(values, pauses, not_found=False),
        # [왜] 인용은 검증을 지난 답에만 있다. 부분 답의 "찾은 근거"는 인용이 아니다
        "cited": list(draft.get("citations", [])) if kind in ("answer", "guide", "not_found") else [],
        "evidence": [e["unit_id"] for e in values.get("evidence", [])],  # 점수 높은 순 (merge_evidence)
        # [왜] R@k·MRR은 RAG 순위로 잰다. 묶음은 get_provision 근거(점수 1.0)가 앞선다
        "retrieved": list(dict.fromkeys(u for e in log if e["step"] == "grade" for u in e["units"])),
        "graph_added": sum(e["graph"] for e in log if e["step"] == "search"),
        "calc": {
            "deadlines": [{"name": d["name"], "due": d["due"]} for d in calc.get("deadlines", [])],
            "reimport": (calc.get("reimport") or {}).get("verdict"),
        },
        # [왜] 붙여 쓴 번호를 몇 건으로 읽었나(R09)와 찾은 단계. 번호는 남기지 않는다
        "cargo_count": len(values.get("cargos", [])),
        "stages": [c["facts"]["stage"] for c in values.get("cargos", []) if c.get("facts")],
        "tools": [c["name"] for m in messages for c in getattr(m, "tool_calls", None) or []],
        "plan": [step["action"] for step in values.get("plan", [])] if loop == "planner" else [],
        "llm_calls": values.get("llm_calls"),
        "failed": [f"{t['tool']}: {t['message']}" for t in values.get("failed_tools", [])],
        "leak": any(n in text for n in numbers for text in watch.inputs),
    }


def ragas_contexts(values: dict, row: dict, top: int, seen: dict[str, str]) -> dict:
    """ragas에 넘길 글 셋. 충실도는 인용한 조문과 작성자가 본 계산·화물 줄, 정밀도·재현율은 RAG 순위."""
    # [왜] 점수 높은 순 앞 8개(옛 contexts)는 인용한 조문도 RAG 순위도 아니라 어긋났다 (R-056)
    texts = seen | {e["unit_id"]: e["text"] for e in values.get("evidence", [])}
    calc = values.get("calc") or {}
    # [주의] 작성자 프롬프트가 받는 가린 글과 같다 (graph/main.py write). 실제 번호는 없다
    calc_lines = cargo_lines(values.get("cargos", [])) + (
        [json.dumps(calc, ensure_ascii=False)] if calc else []
    )
    return {
        "cited_texts": [texts[u] for u in row["cited"] if u in texts],
        "calc_lines": calc_lines,
        "ranked_texts": [texts[u] for u in row["retrieved"] if u in texts][:top],
    }


def evaluate_item(
    deps: AgentDeps,
    item: Item,
    loop: str,
    today: date,
    prices: dict,
    *,
    permission_mode: str = "ask",
    callbacks: Sequence[BaseCallbackHandler] = (),
    llm_via: str = "api",
) -> tuple[dict, dict]:
    """문항 하나를 새 대화로 돌려 (줄, raw)를 돌려준다. 예외가 나도 줄을 남긴다.

    callbacks는 트레이서(trace.tracer_callbacks)다. 비어 있으면 트레이스를 남기지 않는다.
    llm_via는 LLM을 부른 길(Settings.llm_via)이다. cli면 비용을 남기지 않는다.
    """
    log: list[dict] = []
    seen: dict[str, str] = {}
    graph = build_main_graph(
        eval_deps(deps, item, today, log, seen),
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
            values, pauses = drive(graph, item, f"eval-{loop}-{item.id}", [watch, *callbacks])
        row |= observe(values, pauses, watch, loop, log)
        row["error"] = watch.cli_failures[0] if watch.cli_failures else None
        draft = values.get("draft") or {}
        top = load_rules("eval")["ragas"]["contexts"]
        # [주의] raw는 저장소에 넣지 않는다 (scripts/run_eval.py가 저장소 밖에 쓴다). 질문·초안은 가린 글이다
        raw |= {
            # [왜] ragas는 화면에 나간 초안만 잰다. 부분 답이면 검증을 넘지 못한 초안은 쓰지 않았다
            "behaviour": row["behaviour"],
            "question": values.get("masked_text", ""),
            "draft": draft.get("answer", ""),
            "answer": values.get("answer", ""),
            **ragas_contexts(values, row, top, seen),
        }
    except (
        Exception
    ) as error:  # [왜] 한 문항이 실패해도 돈을 낸 나머지 결과를 잃지 않는다 (compare_loops와 같다)
        row |= {
            "behaviour": "error",
            "behaviour_base": "error",
            "cited": [],
            "evidence": [],
            "retrieved": [],
            "calc": {},
            "cargo_count": 0,
            "stages": [],
            "tools": [],
            "plan": [],
        }
        # [왜] 죽은 실행도 그때까지 LLM 입력에 실제 번호가 갔는지 본다.
        #      공책 칸이 없으니 질문에서 번호를 읽는다
        asked = [n for n in mask_text(item.question)[1].values() if n]
        # 체크포인트에 남은 가림 표가 있으면 질문 뒤에 가려진 번호도 센다
        try:
            snap = graph.get_state({"configurable": {"thread_id": f"eval-{loop}-{item.id}"}}).values
            asked += [n for n in (snap.get("mask_map") or {}).values() if n]
        except Exception:  # [왜] 그래프가 처음부터 못 돌았으면 상태가 없다. 질문 번호만으로 본다
            pass
        leak = any(n in text for n in asked for text in watch.inputs)
        row |= {"llm_calls": None, "failed": [], "leak": leak, "error": type(error).__name__}
    # [왜] 실패한 문항도 그때까지 쓴 토큰은 센다. 돈은 이미 나갔다
    spent = usage.usage_metadata if usage is not None else {}
    tokens = {m: {"in": t["input_tokens"], "out": t["output_tokens"]} for m, t in spent.items()}
    row |= {
        "rag": log,
        "real_llm_calls": watch.calls,
        "tokens": tokens,
        "llm_via": llm_via,
        # [왜] 구독으로 부른 호출은 청구액이 없다. 단가로 환산한 값을 비용이라고 남기지 않는다
        "cost_usd": cost_usd(tokens, prices) if llm_via == "api" else None,
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
    # [왜] cli 줄은 비용이 없는 것이 정상이다. 옛 줄에는 llm_via가 없고 그때는 API뿐이었다
    if row["cost_usd"] is None and row.get("llm_via", "api") == "api":
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
