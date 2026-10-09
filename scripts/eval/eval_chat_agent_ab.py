"""채팅 에이전트 지시문(marvia-chat-agent) A/B 평가 (새 지시문은 진짜 모델로 비교한 뒤 Langfuse에 올린다).

    python -m scripts.eval.eval_chat_agent_ab run    --variant old=경로 --variant new=경로 --runs 2 --workers 8 --out 결과폴더
    python -m scripts.eval.eval_chat_agent_ab report --base old --cand new --out 결과폴더      # 결과폴더/RESULT.md를 만든다

무엇을 재나
  services/chat/chat.handle()을 그대로 부른다 (에이전트 도구 루프·코드 검사·고정 문구까지 실제 경로). LLM은 .env의 LLM_MODEL로 진짜 호출한다.
  바꿔 끼우는 것은 지시문 글(llm.get_prompt를 이 프로세스 안에서만 바꾼다. Langfuse는 부르지 않는다)과 아래 외부 호출뿐이다.

바꿔 끼우는 것 (외부 쿼터를 쓰지 않으려고, 변형 사이에 같은 값이 나오게 하려고)
  - 화물 조회(run_agent): UNI-PASS·ShipFinder·판정 LLM을 부르지 않고 가공 응답을 준다. B/L은 TESTBL로 시작하는 모의값이다
  - 해수부 입항 예정 목록과 항구 고르기: 가공 목록과 낱말 표
  - MCP 읽기 전용 도구(배 후보·위치·일정·거리): 가공 응답
  - 로그인·DB: 가짜 사용자와 메모리 지켜보기 함수 (배 찾기·넣기·빼기 포함). 카카오 보내기 함수는 없다: send_kakao는 "도구를 골랐는가"까지만 본다
  - 기억 뽑기(memory)는 끈다
  - Langfuse·DB 환경변수는 지운다: 트레이스·기억·사용량을 어디에도 쓰지 않는다

결과
  결과폴더/runs/<변형>.jsonl 에 한 실행당 한 줄 (도구, 답 종류, 답 글, 검사 위반, 지연, 토큰). 답 글에는 모의 데이터와 모델 출력이 있으므로
  레포가 아니라 스크래치 폴더에만 쓴다. 키·B/L 실제 값은 어디에도 쓰지 않는다.
"""
from __future__ import annotations

import argparse
import contextvars
import csv
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")  # 키는 읽기만 하고 출력하지 않는다
# 트레이스·DB에 아무것도 쓰지 않도록 이 프로세스 환경에서 뺀다 (.env 파일은 그대로)
for _name in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_BASE_URL", "DATABASE_URL"):
    os.environ.pop(_name, None)
os.environ["CHAT_AGENT"] = "on"

from backend.app.observability import langfuse as lf  # noqa: E402
from backend.app.schemas.agent import AgentRequest, EtaInfo, VesselInfo  # noqa: E402
from backend.app.services.judge import bl_parse  # noqa: E402
from backend.app.services import llm
from backend.app.services.chat import chat as svc  # noqa: E402
from backend.app.services.chat import models as chat_models

CASES_PATH = ROOT / "scripts" / "eval" / "eval_chat_agent_cases.jsonl"
KST = timezone(timedelta(hours=9))
NOW = datetime.now(timezone.utc)

# ── Vertex 실험: 비용 장부와 예산 상한 ─────────────────────
# 단가: Google Cloud Vertex AI 생성형 AI 가격표(https://cloud.google.com/vertex-ai/generative-ai/pricing, Standard, Global 엔드포인트,
# 2026-10-07 확인). 단위 USD / 1M 토큰: (입력, 캐시된 입력, 출력). 생각(thinking) 토큰은 출력 단가로 받는다.
PRICES = {
    "gemini-3.5-flash-lite": (0.30, 0.03, 2.50), "gemini-3.5-flash": (1.50, 0.15, 9.00),
    "gemini-2.5-flash-lite": (0.10, 0.01, 0.40), "gemini-2.5-flash": (0.30, 0.03, 2.50),
}
KRW_PER_USD = 1450
BUDGET_KRW = 244_500
STOP_KRW = 195_600  # 예산의 80%. 장부 합계(상한값)가 이 값에 닿으면 새 호출을 시작하지 않는다
LEDGER = ROOT / "experiments" / "vertex_1008" / "ledger.csv"
LEDGER_FIELDS = ["time", "label", "model", "thinking", "variant", "runs", "jobs_done", "llm_calls", "prompt_tokens", "cached_tokens",
                 "completion_tokens", "usd_est", "usd_upper", "krw_est", "krw_upper", "cum_krw_upper"]


def model_prices() -> tuple[float, float, float]:
    name = (os.environ.get("LLM_MODEL") or "").split("/")[-1]
    return PRICES[name]  # 단가표에 없는 모델이면 KeyError: 비용을 모르는 채로 돌지 않는다


def call_usd(prompt_tokens, cached_tokens, completion_tokens) -> tuple[float, float]:
    """한 호출의 (추정 비용, 상한 비용) USD. 상한은 캐시 할인을 받지 않았다고 치고 입력 전부를 정가로 계산한다."""
    pin, pcache, pout = model_prices()
    p, c, o = prompt_tokens or 0, cached_tokens or 0, completion_tokens or 0
    return ((p - c) * pin + c * pcache + o * pout) / 1e6, (p * pin + o * pout) / 1e6


def ledger_total_krw() -> float:
    if not LEDGER.exists():
        return 0.0
    return sum(float(r["krw_upper"]) for r in csv.DictReader(LEDGER.open(encoding="utf-8")))


def ledger_append(row: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    new = not LEDGER.exists()
    with LEDGER.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LEDGER_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


# ── 가공 데이터 ──────────────────────────────────────────────

SHIPS = {  # 이름 → (MMSI, 국적, 호출부호, 이전 항구)
    "SAMPLE ORCHID": (440999001, "LR", "DSAM1", "SHANGHAI"), "SAMPLE LOTUS": (440999002, "PA", "DSAM2", "QINGDAO"),
    "SAMPLE MAPLE": (440999003, "KR", "DSAM3", "KOBE"), "SAMPLE PINE": (440999004, "MH", "DSAM4", "SINGAPORE"),
}
PORTS_BY_PLACE = {  # 항구 고르기 대신 쓰는 낱말 표 (소문자 부분 일치)
    ("shanghai", "상하이", "china", "중국"): ["SHANGHAI", "QINGDAO", "NINGBO"],
    ("japan", "일본"): ["KOBE", "YOKOHAMA"], ("singapore", "싱가포르"): ["SINGAPORE"], ("vietnam", "베트남"): ["HOCHIMINH"],
}
PLAN_ROWS = [("SAMPLE ORCHID", "SHANGHAI", 2), ("SAMPLE LOTUS", "QINGDAO", 3), ("SAMPLE MAPLE", "KOBE", 4),
             ("SAMPLE PINE", "SINGAPORE", 5), ("SAMPLE CEDAR", "NINGBO", 3), ("SAMPLE BIRCH", "YOKOHAMA", 6),
             ("SAMPLE ASPEN", "HOCHIMINH", 7), ("SAMPLE ELM", "SHANGHAI", 1)]


def fake_arrivals(days: int) -> list:
    out = []
    for name, port, day in PLAN_ROWS:
        if day > days:
            continue
        mmsi, flag, call_sign, _ = SHIPS.get(name, (0, "PA", "DSAMX", port))
        out.append(SimpleNamespace(ship_name=name, call_sign=call_sign, nationality=flag, ship_kind="풀컨테이너선", previous_port=port,
                                   next_port=None, purpose="양하", facility="신선대", expected_arrival=NOW + timedelta(days=day),
                                   planned_departure=NOW + timedelta(days=day + 1)))
    return out


def fake_match_ports(place: str, available: list[str]) -> list[str]:
    low = place.strip().lower()
    for keys, ports in PORTS_BY_PLACE.items():
        if any(k in low for k in keys):
            return [p for p in available if p in ports]
    return [p for p in available if place.upper() in p.upper()]


def fake_run_agent(req: AgentRequest):
    """화물 조회·화물 질문 가공 응답. 판정 흐름 전체를 대신한다 (B/L은 TESTBL 모의값)."""
    from backend.app.routers.agent import _response

    if req.follow_up_question:
        return _response(status="ok", answer="이 화물은 지금 통관 심사 단계예요. 다음 단계는 수입 신고 수리예요.")
    vessel = VesselInfo(mmsi=440999001, imo=None, name="SAMPLE ORCHID", call_sign="DSAM1", flag="LR", ship_type=70, voyage_no="V123E")
    eta = EtaInfo(ais_eta=NOW + timedelta(days=3), mof_eta=NOW + timedelta(days=3), calc_eta=None, trusted_eta=NOW + timedelta(days=3), distance_nm=300.0)
    return _response(status="ok", verdict="fine", vessel_match="confirmed", days_margin=4, decided_by="rule", vessel=vessel, eta=eta,
                     answer="SAMPLE ORCHID호가 이번 주 금요일 부산 입항 예정이고 여유가 있어 괜찮아요.")


def fake_watch_hooks() -> svc.WatchHooks:
    """로그인한 사용자의 지켜보기 저장소 대신 하는 메모리 함수들 (DB·ShipFinder 없음). 도구가 끝까지 도는지 보려고 켜짐·꺼짐을 그냥 받아 준다."""
    vessel = chat_models.VesselHooks(resolve=lambda call_sign, name: {"mmsi": 440999000}, add=lambda mmsi, *a, **k: {"mmsi": mmsi},
                             remove=lambda mmsi: {"mmsi": mmsi})
    return svc.WatchHooks(tool=lambda bl, on: {"on": on}, state=lambda bl: {"saved": True, "watch": False}, worry=lambda bl: None, vessel=vessel)


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fake_run_tool(name: str, args: dict) -> dict:
    """MCP 읽기 전용 도구 가공 응답. 모양은 도구 응답과 같다 (source·fetched_at 포함)."""
    base = {"source": "shipfinder", "fetched_at": _stamp()}
    if name == "get_vessel_candidates":
        wanted = str(args.get("ship_name") or "").upper()
        found = [{"mmsi": m, "name": n, "flag": f, "dest": "BUSAN", "call_sign": c} for n, (m, f, c, _) in SHIPS.items() if wanted and wanted in n]
        return {**base, "candidates": found}
    if name == "get_live_position":
        return {**base, "mmsi": args.get("mmsi"), "lat": 34.9, "lon": 129.3, "sog": 12.4, "cog": 40.0}
    if name == "get_port_schedule":
        return {"source": "mof", "fetched_at": base["fetched_at"], "ship_name": args.get("ship_name") or "SAMPLE ORCHID", "next_arrival": "2026-10-10 09:00"}
    if name == "estimate_distance":
        return {"source": "searoute", "fetched_at": base["fetched_at"], "distance_nm": 120.5, "calc_hours_at_sog": 9.7}
    return {"error": {"code": "unknown_tool", "message": name, "retryable": False}}


# ── 기록과 바꿔 끼우기 ───────────────────────────────────────

PROMPT_TEXT: contextvars.ContextVar[str | None] = contextvars.ContextVar("prompt_text", default=None)
RECORD: contextvars.ContextVar[dict | None] = contextvars.ContextVar("record", default=None)


def fake_load_memo(user_id: str):
    """로그인 사용자의 메모 대신 하는 가공 값 (DB 없음): 서류(A/N)에서 저장된 포워더와 채팅에서 저장된 수출자. 회사·번호는 모의값이다."""
    def contact(cid, company, role, phone, source):
        return {"id": cid, "section": "about", "kind": "contact", "noted_at": "2026-10-07",
                "fields": {"company": company, "role": role, "phone": phone, "source": source}}
    return [contact("c1", "테스트로지스", "포워더", "051-000-0001", "A/N"), contact("c2", "테스트수출", "수출자", "051-000-0002", "사용자")], {}


def install() -> None:
    """한 번만 부른다. 프로세스 전체에 가공 함수를 끼운다 (실행마다 바꾸지 않는다: 동시에 도는 실행들이 서로 영향을 주지 않게)."""
    orig_get_prompt = llm.get_prompt

    def get_prompt(name: str, label: str = "production"):
        text = PROMPT_TEXT.get()
        if name == llm.CHAT_AGENT_PROMPT and text is not None:
            return lf.Prompt(name=name, text=text, version="ab", source=None)
        return orig_get_prompt(name, label)

    llm.get_prompt = get_prompt
    bl_parse.exists_in_customs = lambda bl: bl.upper().startswith("TESTBL")
    svc._arrivals = fake_arrivals
    svc._load_memo = fake_load_memo
    svc._match_ports_cached = fake_match_ports
    svc.mcp_client.read_only_tools = _tools_once()
    # 기억 뽑기는 DB·LLM을 쓰는 부가 기능이라 끈다 (지시문 평가와 상관없다)
    svc.memory.start_early = lambda *a, **k: None
    svc.memory.remember_chat_later = lambda *a, **k: None
    svc.memory.take_notices = lambda *a, **k: []
    svc.memory.join_early = lambda *a, **k: ""
    svc.memory.lookup_notes = lambda *a, **k: []

    # Vertex 토큰은 처음 쓸 때 만든다. 여러 스레드가 동시에 만들면 토큰이 비어 있는 클라이언트가 생겨서 한 번에 한 스레드만 들어가게 한다
    orig_vertex_client = llm._vertex_client
    vertex_lock = threading.Lock()

    def locked_vertex_client():
        with vertex_lock:
            return orig_vertex_client()

    llm._vertex_client = locked_vertex_client

    orig_agent = llm.chat_agent

    def recorded_agent(*args, feedback=None, **kwargs):
        rec = RECORD.get()
        for attempt in range(6):
            started = time.monotonic()
            try:
                answer = orig_agent(*args, feedback=feedback, **kwargs)
                break
            except llm.LLMError as e:
                if e.kind in ("rate_limited", "overloaded", "timeout", "connection") and attempt < 5:
                    rec["retries"] += 1
                    time.sleep(min(30, 3 * 2 ** attempt))  # 요청 제한은 잠깐 쉬었다 다시 (지수 대기)
                    continue
                rec["errors"].append(e.kind)
                rec.setdefault("error_msgs", []).append(str(e)[:300])  # 키는 들어 있지 않다 (HTTP 상태와 메시지)
                raise
        r = answer.llm
        usd = call_usd(getattr(r, "prompt_tokens", None), getattr(r, "cached_tokens", None), getattr(r, "completion_tokens", None)) \
            if getattr(r, "prompt_tokens", None) is not None else (0.0, 0.0)
        rec["calls"].append({"usd": usd[0], "usd_upper": usd[1],
            "feedback": (feedback or "")[:200] or None, "kind": answer.output.answer_kind, "reply": answer.output.reply,
            "quote": answer.output.skill_quote[:120], "latency_ms": int((time.monotonic() - started) * 1000),
            "prompt_tokens": getattr(r, "prompt_tokens", None), "completion_tokens": getattr(r, "completion_tokens", None),
            "cached_tokens": getattr(r, "cached_tokens", None), "cost": getattr(r, "cost", None), "model": getattr(r, "model", None),
            "tools": [{"name": c["name"], "args": c["arguments"], "error": (c.get("result") or {}).get("error") and
                       ((c["result"]["error"] or {}).get("code") if isinstance(c["result"]["error"], dict) else str(c["result"]["error"]))}
                      for c in answer.tool_calls]})
        return answer

    llm.chat_agent = recorded_agent


def _tools_once():
    try:
        tools = svc.mcp_client.read_only_tools()  # 목록만 받는다 (같은 프로세스 안 MCP 서버, 외부 호출 없음)
    except Exception:  # noqa: BLE001
        tools = []
    return lambda: tools


# ── 한 번 실행 ───────────────────────────────────────────────

def run_once(case: dict, variant: str, prompt_text: str, rep: int) -> dict:
    rec = {"variant": variant, "id": case["id"], "tag": case["tag"], "rep": rep, "message": case["message"], "calls": [], "errors": [],
           "retries": 0,
           "thinking": os.environ.get("VERTEX_THINKING_BUDGET")}
    token_p, token_r = PROMPT_TEXT.set(prompt_text), RECORD.set(rec)
    started = time.monotonic()
    context = AgentRequest(bl_no="TESTBL01", bl_type="HOUSE", session_id="ab") if case.get("has_current_cargo") else None
    try:
        result = svc.handle(case["message"], f"ab-{variant}-{case['id']}-{rep}", context, fake_run_agent, "ab-user", case.get("history") or [],
                            fake_run_tool, fake_watch_hooks(), None, case.get("on_screen"))
        rec["result_kind"], rec["reply"] = result.kind, result.reply
        rec["watch_set"] = bool(result.watch_set or result.watch_vessel_set)
    except Exception as e:  # noqa: BLE001 - 한 문항이 죽어도 전체 평가는 계속한다
        rec["exception"] = f"{type(e).__name__}: {str(e)[:120]}"
    finally:
        PROMPT_TEXT.reset(token_p)
        RECORD.reset(token_r)
    rec["wall_ms"] = int((time.monotonic() - started) * 1000)
    rec["verdict"], rec["reasons"] = judge(case, rec)
    return rec


# ── 채점 ─────────────────────────────────────────────────────

def judge(case: dict, rec: dict) -> tuple[str, list[str]]:
    """pass / fail / code(LLM 없이 코드가 처리) / error(인프라 오류). 이유 목록을 같이 돌려준다."""
    if rec.get("exception") or rec["errors"]:
        return "error", [rec.get("exception") or "llm_error:" + ",".join(rec["errors"])]
    if not rec["calls"]:
        return "code", ["코드가 LLM 없이 처리"]
    ex, reasons = case["expect"], []
    tools = [t for c in rec["calls"] for t in c["tools"]]
    names = {t["name"] for t in tools}
    last = rec["calls"][-1]
    kind, reply = last["kind"], last["reply"] or ""
    if "tools" in ex and not set(ex["tools"]) <= names:
        reasons.append(f"필요한 도구 안 부름: {sorted(set(ex['tools']) - names)}")
    if "tools_any" in ex and not names & set(ex["tools_any"]):
        reasons.append(f"둘 중 하나도 안 부름: {ex['tools_any']}")
    if ex.get("no_tools") and names:
        reasons.append(f"도구를 부르면 안 됨: {sorted(names)}")
    if names & set(ex.get("forbid_tools", [])):
        reasons.append(f"금지 도구 호출: {sorted(names & set(ex['forbid_tools']))}")
    if "kind" in ex and kind not in ex["kind"]:
        reasons.append(f"답 종류 {kind} (기대 {ex['kind']})")
    if kind in ex.get("forbid_kind", []):
        reasons.append(f"금지된 답 종류 {kind}")
    if ex.get("watch_done") and not rec.get("watch_set"):
        reasons.append("지켜보기가 실제로 켜지거나 꺼지지 않음")
    for tool, arg, pattern in ex.get("arg_has", []):
        if not any(t["name"] == tool and re.search(pattern, str((t["args"] or {}).get(arg))) for t in tools):
            reasons.append(f"{tool}.{arg}가 {pattern} 아님")
    for tool, arg, pattern in ex.get("arg_not", []):
        if any(t["name"] == tool and re.search(pattern, str((t["args"] or {}).get(arg))) for t in tools):
            reasons.append(f"{tool}.{arg}에 금지 값")
    for pattern in ex.get("final_has", []):  # 코드가 쓴 고정 문구까지 포함한 화면 답
        if not re.search(pattern, rec.get("reply") or ""):
            reasons.append(f"화면 답에 {pattern} 없음")
    for pattern in ex.get("reply_forbid", []):
        if re.search(pattern, reply):
            reasons.append(f"답에 금지 글 {pattern}")
    if ex.get("no_digits_if_general") and kind == "general" and re.search(r"\d", reply):
        reasons.append("3층 답에 숫자")
    return ("fail" if reasons else "pass"), reasons


# ── 실행 ─────────────────────────────────────────────────────

def load_cases(only: str | None) -> list[dict]:
    cases = [json.loads(line) for line in CASES_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    if only:
        wanted = set(only.split(","))
        cases = [c for c in cases if c["id"] in wanted or c["tag"] in wanted]
    return cases


def cmd_run(args) -> None:
    install()
    out = Path(args.out)
    (out / "runs").mkdir(parents=True, exist_ok=True)
    variants = dict(v.split("=", 1) for v in args.variant)
    texts = {name: Path(path).read_text(encoding="utf-8") for name, path in variants.items()}
    cases = load_cases(args.only)
    lock = threading.Lock()
    jobs, done_keys = [], set()
    for name in variants:
        path = out / "runs" / f"{name}.jsonl"
        if path.exists() and not args.fresh:
            for line in path.read_text(encoding="utf-8").splitlines():
                r = json.loads(line)
                done_keys.add((name, r["id"], r["rep"]))
    for rep in range(args.runs):
        for case in cases:
            for name in variants:
                if (name, case["id"], rep) not in done_keys:
                    jobs.append((case, name, rep))
    start_total = ledger_total_krw()
    print(f"model={os.environ.get('LLM_MODEL')} thinking={os.environ.get('VERTEX_THINKING_BUDGET')} cases={len(cases)} variants={list(variants)} "
          f"jobs={len(jobs)} workers={args.workers} ledger_krw_upper={start_total:.0f}/{STOP_KRW}", flush=True)
    finished = [0]
    spent = {"usd": 0.0, "upper": 0.0}  # 이 실행에서 쓴 돈. 예산 상한 검사에 쓴다
    stopped = [False]
    per_variant: dict[str, dict] = {n: {"jobs": 0, "calls": 0, "p": 0, "c": 0, "o": 0, "usd": 0.0, "upper": 0.0} for n in variants}

    def work(job):
        case, name, rep = job
        with lock:
            if start_total + spent["upper"] * KRW_PER_USD >= STOP_KRW:  # 80%에 닿으면 새 문항을 시작하지 않는다
                if not stopped[0]:
                    print("예산 80% 도달: 남은 문항을 건너뛴다", flush=True)
                stopped[0] = True
                return
        rec = run_once(case, name, texts[name], rep)
        with lock:
            with open(out / "runs" / f"{name}.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            pv = per_variant[name]
            pv["jobs"] += 1
            for c in rec["calls"]:
                pv["calls"] += 1
                pv["p"] += c["prompt_tokens"] or 0
                pv["c"] += c["cached_tokens"] or 0
                pv["o"] += c["completion_tokens"] or 0
                pv["usd"] += c["usd"]
                pv["upper"] += c["usd_upper"]
                spent["usd"] += c["usd"]
                spent["upper"] += c["usd_upper"]
            finished[0] += 1
            if finished[0] % 25 == 0:
                print(f"  {finished[0]}/{len(jobs)} spent_krw_upper={spent['upper'] * KRW_PER_USD:.0f}", flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(work, jobs))
    cum = start_total
    for name, pv in per_variant.items():  # 변형마다 장부에 한 줄
        cum += pv["upper"] * KRW_PER_USD
        ledger_append({"time": _stamp(), "label": args.label or Path(args.out).name, "model": os.environ.get("LLM_MODEL"),
                       "thinking": os.environ.get("VERTEX_THINKING_BUDGET") or "default", "variant": name, "runs": args.runs,
                       "jobs_done": pv["jobs"], "llm_calls": pv["calls"], "prompt_tokens": pv["p"], "cached_tokens": pv["c"],
                       "completion_tokens": pv["o"], "usd_est": f"{pv['usd']:.4f}", "usd_upper": f"{pv['upper']:.4f}",
                       "krw_est": f"{pv['usd'] * KRW_PER_USD:.0f}", "krw_upper": f"{pv['upper'] * KRW_PER_USD:.1f}", "cum_krw_upper": f"{cum:.0f}"})
    print(f"끝: {finished[0]}건, 이 실행 비용 약 {spent['usd'] * KRW_PER_USD:.0f}원(상한 {spent['upper'] * KRW_PER_USD:.0f}원), 장부 누계(상한) {cum:.0f}원", flush=True)


# ── 보고서 ───────────────────────────────────────────────────

def load_runs(out: Path, name: str) -> list[dict]:
    path = out / "runs" / f"{name}.jsonl"
    runs = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []
    cases = {c["id"]: c for c in load_cases(None)}
    for r in runs:  # 문항 기대를 고쳤을 때 다시 돌리지 않고 같은 기록을 현재 기준으로 다시 채점한다
        r["verdict"], r["reasons"] = judge(cases[r["id"]], r)
    return runs


def rate(runs: list[dict]) -> tuple[int, int]:
    scored = [r for r in runs if r["verdict"] in ("pass", "fail")]
    return sum(r["verdict"] == "pass" for r in scored), len(scored)


def pct(p: tuple[int, int]) -> str:
    return f"{p[0]}/{p[1]} ({100 * p[0] / p[1]:.1f}%)" if p[1] else "-"


def describe(r: dict) -> str:
    tools = [f"{t['name']}({json.dumps(t['args'], ensure_ascii=False)[:80]})" + (f"!{t['error']}" if t["error"] else "") for c in r["calls"] for t in c["tools"]]
    last = r["calls"][-1] if r["calls"] else {}
    return (f"[{r['verdict']}] tools={tools or '-'} kind={last.get('kind')} llm_reply={(last.get('reply') or '')[:100]!r} "
            f"final={(r.get('reply') or '')[:100]!r} why={r['reasons']}")


def cmd_report(args) -> None:
    out = Path(args.out)
    base, cand = load_runs(out, args.base), load_runs(out, args.cand)
    cases = {c["id"]: c for c in load_cases(None)}
    pending = "watch_vessel" not in {t["function"]["name"] for t in svc.AGENT_TOOLS}
    lines = [f"# 지시문 A/B 결과: {args.base} vs {args.cand}", "", f"모델: {os.environ.get('LLM_MODEL')} / 문항 {len(cases)}개 / AGENT_TOOLS에 watch_vessel {'없음 (pending code)' if pending else '있음'}", ""]

    def tags(runs):
        t = {}
        for r in runs:
            t.setdefault(r["tag"], []).append(r)
        return t
    lines += ["## 통과율 (코드가 LLM 없이 처리한 실행과 인프라 오류는 분모에서 뺀다)", "", f"| 구분 | {args.base} | {args.cand} |", "|---|---|---|",
              f"| 전체 | {pct(rate(base))} | {pct(rate(cand))} |"]
    bt, ct = tags(base), tags(cand)
    for tag in sorted(set(bt) | set(ct)):
        lines.append(f"| {tag} | {pct(rate(bt.get(tag, [])))} | {pct(rate(ct.get(tag, [])))} |")
    for name, runs in ((args.base, base), (args.cand, cand)):
        counts = {v: sum(r["verdict"] == v for r in runs) for v in ("pass", "fail", "code", "error")}
        lines.append(f"\n{name}: {counts}")
    # 문항별 비교: 같은 문항의 통과 수
    def per_case(runs):
        d = {}
        for r in runs:
            d.setdefault(r["id"], []).append(r)
        return d
    bc, cc = per_case(base), per_case(cand)
    regress, improve, flaky = [], [], []
    for cid in cases:
        b, c = bc.get(cid, []), cc.get(cid, [])
        bp, cp = sum(r["verdict"] == "pass" for r in b), sum(r["verdict"] == "pass" for r in c)
        if any(r["verdict"] in ("pass", "fail") for r in b + c):
            if cp < bp:
                regress.append((cid, b, c, bp, cp))
            elif cp > bp:
                improve.append((cid, b, c, bp, cp))
            for name, rs in ((args.base, b), (args.cand, c)):
                scored = [r["verdict"] for r in rs if r["verdict"] in ("pass", "fail")]
                if len(set(scored)) > 1:
                    flaky.append((name, cid))
    lines += ["", f"## {args.cand}가 {args.base}보다 나쁜 문항 ({len(regress)}개)", ""]
    for cid, b, c, bp, cp in regress:
        lines += [f"### {cid} `{cases[cid]['message']}` (cargo={cases[cid].get('has_current_cargo')}) {args.base} {bp}/{len(b)} -> {args.cand} {cp}/{len(c)}",
                  f"기대: `{json.dumps(cases[cid]['expect'], ensure_ascii=False)}`"]
        lines += [f"- {args.base}: {describe(r)}" for r in b] + [f"- {args.cand}: {describe(r)}" for r in c] + [""]
    lines += [f"## {args.cand}가 더 나은 문항 ({len(improve)}개)", ""] + [f"- {cid} `{cases[cid]['message']}` {bp}->{cp}" for cid, _, _, bp, cp in improve]
    lines += ["", f"## 흔들리는 문항 (같은 변형에서 두 번의 결과가 다름, {len(flaky)}개)", ""] + [f"- {n} {cid} `{cases[cid]['message']}`" for n, cid in flaky]
    both_fail = [cid for cid in cases if bc.get(cid) and cc.get(cid) and all(r["verdict"] == "fail" for r in bc[cid] + cc[cid])]
    lines += ["", f"## 두 변형 모두 실패한 문항 ({len(both_fail)}개, 기대가 틀렸거나 둘 다 약한 곳)", ""]
    for cid in both_fail:
        lines.append(f"- {cid} `{cases[cid]['message']}`: {args.base} {bc[cid][0]['reasons']} / {args.cand} {cc[cid][0]['reasons']}")

    def stats(runs):
        calls = [c for r in runs for c in r["calls"]]
        n = len(calls)
        cost = [c["cost"] for c in calls if c["cost"] is not None]
        avg = lambda xs: sum(xs) / len(xs) if xs else 0  # noqa: E731
        return {"runs": len(runs), "llm_answers": n, "cost": sum(cost) if cost else None,
                "avg_latency_ms_per_answer": avg([c["latency_ms"] for c in calls]),
                "avg_wall_ms_per_run": avg([r["wall_ms"] for r in runs]),
                "avg_prompt_tokens": avg([c["prompt_tokens"] for c in calls if c["prompt_tokens"]]),
                "avg_completion_tokens": avg([c["completion_tokens"] for c in calls if c["completion_tokens"]]),
                "avg_cached_tokens": avg([c["cached_tokens"] for c in calls if c["cached_tokens"]]),
                "retried_by_validation": sum(1 for c in calls if c["feedback"]),
                "rate_limit_retries": sum(r["retries"] for r in runs)}
    lines += ["", "## 비용·지연·토큰 (LLM 답 1회 = chat_agent 호출 1번, 도구 라운드 합산)", "", f"| 항목 | {args.base} | {args.cand} |", "|---|---|---|"]
    sb, sc = stats(base), stats(cand)
    for k in sb:
        fmt = lambda v: "-" if v is None else (f"{v:.4f}" if k == "cost" else f"{v:.0f}" if isinstance(v, float) else str(v))  # noqa: E731
        lines.append(f"| {k} | {fmt(sb[k])} | {fmt(sc[k])} |")
    lines += ["", f"합계 비용 {args.base}+{args.cand}: {((sb['cost'] or 0) + (sc['cost'] or 0)):.4f} (모델이 비용을 주지 않으면 0)"]
    pend = [cid for cid in cases if cases[cid]["tag"] == "watch_vessel"]
    if pending:
        lines += ["", "## pending code: watch_vessel 문항은 도구가 없어 별도 취급", ", ".join(pend)]
    (out / "RESULT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"쓴 곳: {out / 'RESULT.md'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--variant", action="append", required=True, help="이름=지시문 파일 경로 (여러 번)")
    run.add_argument("--runs", type=int, default=2)
    run.add_argument("--workers", type=int, default=8)
    run.add_argument("--out", required=True)
    run.add_argument("--only", help="문항 id나 tag를 쉼표로")
    run.add_argument("--label", help="장부에 적을 이름")
    run.add_argument("--fresh", action="store_true", help="이미 있는 결과를 무시하고 다시 돈다 (파일에 이어 쓴다)")
    rep = sub.add_parser("report")
    rep.add_argument("--base", required=True)
    rep.add_argument("--cand", required=True)
    rep.add_argument("--out", required=True)
    args = parser.parse_args()
    cmd_run(args) if args.cmd == "run" else cmd_report(args)


if __name__ == "__main__":
    main()
