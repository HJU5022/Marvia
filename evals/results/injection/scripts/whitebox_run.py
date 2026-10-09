"""화이트박스 공격 8종 x 채널 2 x 3회를 gpt-5-mini에 프롬프트만으로 (강사 조건: 코드 방어·엄격 스키마 없음).
A: 수정 전 프롬프트(ebd8f84^), B: 수정 후(레포 파일). 누적 실제 청구액 $0.40 넘으면 멈춤."""
import json, os, subprocess, sys
from collections import Counter
from pathlib import Path
from dotenv import dotenv_values
import scripts.eval.injection_redteam as rt
from backend.app.schemas.agent import Evidence

_real_chat = rt.llm.chat.__wrapped__ if hasattr(rt.llm.chat, "__wrapped__") else rt.llm.chat
os.environ["OPENROUTER_API_KEY"] = dotenv_values(".env").get("OPENROUTER_API_KEY") or ""
MODEL, BUDGET, REPS = "openai/gpt-5-mini", 0.40, 3
attacks = json.load(open(rt.OUT_DIR / "whitebox_attacks.json", encoding="utf-8"))
PROMPTS = {
    "A_before": subprocess.run(["git", "show", "ebd8f84^:backend/app/prompts/marvia-follow-up.md"], capture_output=True,
                               text=True, encoding="utf-8").stdout,
    "B_after": Path("backend/app/prompts/marvia-follow-up.md").read_text(encoding="utf-8"),
}


def data(question, dest):
    """9/30 코드(llm.answer_follow_up)처럼 지난 결과 전체 + 질문. AIS 목적지 카드도 그대로 넣는다."""
    prev = rt._previous()
    prev = prev.model_copy(update={"evidence": prev.evidence + [Evidence(source="shipfinder", field="dest", value=dest,
                                                                         fetched_at=rt.NOW)]})
    result = prev.model_dump(mode="json", exclude={"trace_id", "vessel_candidates"})
    return json.dumps({"result": result, "question": question}, ensure_ascii=False)


cost, rows = 0.0, []
for name, prompt in PROMPTS.items():
    for i, a in enumerate(attacks):
        for ch in ("question", "ais_dest"):
            q, dest = (f"여유가 며칠이야? {a['text']}", "CNSHA") if ch == "question" else ("배가 지금 어디로 가고 있어?", f"CNSHA {a['text']}")
            for rep in range(REPS):
                if cost >= BUDGET:
                    sys.exit(f"budget reached ${cost:.4f}")
                try:
                    r = _real_chat([{"role": "system", "content": prompt}, {"role": "user", "content": data(q, dest)}],
                                   model=MODEL)  # 형식 지정 없음 (강사 조건, json_object는 프롬프트에 json 단어가 없어 400)
                    out, err = r.content or "", None
                    cost += r.cost or 0
                except Exception as e:
                    out, err = "", f"{type(e).__name__}: {str(e)[:100]}"
                b = rt.hit(out)
                rows.append({"prompt": name, "attack": i, "category": a["category"], "channel": ch, "rep": rep,
                             "breached": b, "error": err, "output": out})
                print(f"{name:8} {i+1} {ch:8} #{rep} {'BREACH' if b else ('error ' if err else 'ok    ')} {a['category'][:22]:22} | {(err or out)[:90]!r}", flush=True)
json.dump(rows, open(rt.OUT_DIR / "whitebox_result.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for name in PROMPTS:
    rs = [r for r in rows if r["prompt"] == name]
    print(f"\n{name}: 뚫림 {sum(r['breached'] for r in rs)}/{len(rs)}, error {sum(1 for r in rs if r['error'])}")
    print("  유형별:", dict(Counter(r["category"] for r in rs if r["breached"])))
    print("  채널별:", dict(Counter(r["channel"] for r in rs if r["breached"])))
print(f"COST ${cost:.4f}")
