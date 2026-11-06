"""ragas로 답의 근거 충실도와 근거 묶음의 정밀도·재현율을 잰다 (done 3.2).

맥락: faithfulness는 인용한 조문+작성자가 본 계산·화물 줄(cited+calc),
     context precision·recall은 RAG 순위 앞쪽 글.
지표: faithfulness, context precision(reference 기준), context recall.

돈이 든다(채점 모델 호출). 실행 전에 --dry-run으로 어림 비용을 본다.
[주의] 이 스크립트는 따로 된 환경에서 돈다. ragas 0.4.3은 langchain-community 0.4.2에서 import부터 실패하고
       0.4.1로 고정하면 돈다(11-06 실측). 우리 의존성에 넣지 않으려고 marvia를 import하지 않고 YAML만 읽는다.
실행 (Docker, 저장소 루트에서):
  uv run --no-project --with ragas==0.4.3 --with langchain-community==0.4.1 --with anthropic==2.3.0 \
    --with pyyaml python scripts/ragas_score.py <run_eval의 .raw.json> --out <점수.json> \\
    --commit <실행 커밋> [--dry-run]
키는 환경 변수 MARVIA_ANTHROPIC_API_KEY로만 받는다(.env를 읽지 않는다).
채점 모델은 rules/eval.yaml judge.model이고 답을 쓴 모델과 다르다
(v1 평가 결정: 채점 모델은 서비스 모델과 달라야 한다).
입력은 모두 가린 글이다(질문·초안은 run_eval이 가린 글로 남긴다). 실제 번호는 채점 모델에 가지 않는다.
하지 않는 일: 요약과 사람 일치율(scripts/run_eval.py agree가 점수 파일을 읽는다).
"""

import argparse
import asyncio
import json
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(name: str) -> dict:
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))


NEW_FIELDS = ("cited_texts", "calc_lines", "ranked_texts")


def samples(raw: list[dict], references: dict[str, str]) -> list[dict]:
    """채점할 문항: 정답 글(reference)이 있고, 초안이 화면에 나간 답(answer·guide)인 것."""
    # [왜] 옛 raw(contexts만 있는 것)로 조용히 대신 재면 점수 뜻이 달라진다. 이유를 대고 멈춘다
    old = [r["id"] for r in raw if "question" in r and not all(f in r for f in NEW_FIELDS)]
    if old:
        raise SystemExit(
            f"옛 raw 파일이다({', '.join(old[:3])} 등). {'·'.join(NEW_FIELDS)}가 없다. "
            "run_eval run으로 다시 만든다"
        )
    return [
        r | {"reference": references[r["id"]]}
        for r in raw
        if references.get(r["id"]) and r.get("behaviour") in ("answer", "guide")
    ]


def not_scored(raw: list[dict], references: dict[str, str], todo: list[dict]) -> list[tuple[str, str]]:
    """정답 글이 있는데 채점하지 않은 문항과 이유(행동 이름). 모르게 빠지는 문항이 없게 찍는다."""
    done = {s["id"] for s in todo}
    behaviour = {r["id"]: r.get("behaviour", "error") for r in raw}
    return [(i, behaviour.get(i, "raw에 없음")) for i, text in references.items() if text and i not in done]


def contexts_for(sample: dict) -> dict[str, list[str]]:
    """지표마다 넘길 글. 충실도는 인용한 조문+계산·화물 줄, 정밀도·재현율은 RAG 순위."""
    return {
        "faithfulness": sample["cited_texts"] + sample["calc_lines"],
        "context_precision": sample["ranked_texts"],
        "context_recall": sample["ranked_texts"],
    }


def judge_llm(model: str, client):
    """ragas가 쓰는 채점 LLM. Anthropic 클라이언트를 JSON 모드로 감싼다."""
    import instructor
    from ragas.llms.base import InstructorLLM, InstructorModelArgs

    # [왜] ragas 기본(from_anthropic)은 도구 호출 모드라 도구 선택을 강제한다.
    #      강제 도구 선택을 받지 않는 모델이 있어(src/marvia/llm.py 주석) 글 속 JSON 모드로 받는다
    llm = InstructorLLM(
        client=instructor.from_anthropic(client, mode=instructor.Mode.ANTHROPIC_JSON),
        model=model,
        provider="anthropic",
        model_args=InstructorModelArgs(max_tokens=4096),
    )
    # [왜] ragas는 temperature 0.01·top_p 0.1을 함께 보내는데 anthropic 2.3.0의 messages.create에는
    #      두 인자가 없다 (11-06 실측: inspect.signature). 빼지 않으면 첫 호출에서 TypeError가 난다
    for key in ("temperature", "top_p"):
        llm.model_args.pop(key, None)
    return llm


def spent_usd(used: dict, price: dict) -> float:
    """지금까지 센 토큰의 실제 비용(달러)."""
    return (used["in"] * price["input"] + used["out"] * price["output"]) / 1e6


def over_cap(used: dict, price: dict, cap: float) -> bool:
    # [왜] 어림은 [추정]이고 instructor 재시도가 호출을 늘린다. 실제 쓴 돈이 상한에 닿으면 멈춘다
    return spent_usd(used, price) >= cap


async def score(sample: dict, metrics: dict) -> dict:
    """문항 하나를 세 지표로 잰다. 지표 하나가 실패해도 나머지는 남긴다."""
    out = {"id": sample["id"], "loop": sample.get("loop"), "errors": []}
    texts = contexts_for(sample)
    calls = {
        "faithfulness": lambda m: m.ascore(
            user_input=sample["question"], response=sample["draft"], retrieved_contexts=texts["faithfulness"]
        ),
        "context_precision": lambda m: m.ascore(
            user_input=sample["question"],
            reference=sample["reference"],
            retrieved_contexts=texts["context_precision"],
        ),
        "context_recall": lambda m: m.ascore(
            user_input=sample["question"],
            reference=sample["reference"],
            retrieved_contexts=texts["context_recall"],
        ),
    }
    for name, call in calls.items():
        if not texts[name]:
            # [왜] 빈 맥락: 충실도(근거 없는 답)와 재현율(찾은 것 없음)은 0점. 판정 호출 없이 넣는다.
            #      정밀도는 분모가 없어 정의되지 않으니 못 잰 값으로 둔다 (11-06 판정, 계획 4a 문서 ragas 절)
            zero = name != "context_precision"
            out[name] = 0.0 if zero else None
            out["errors"].append(f"{name}: no_contexts" + ("=0" if zero else ""))
            continue
        try:
            value = (await call(metrics[name])).value
            # [왜] ragas는 실패해도 NaN을 돌려줄 수 있다. NaN은 None으로 남겨 평균에서 뺀다 (강의 IV 3주 05강)
            out[name] = None if value is None or value != value else float(value)
        except Exception as error:  # [왜] 한 지표의 실패로 돈을 낸 나머지 점수를 잃지 않는다
            out[name] = None
            out["errors"].append(f"{name}: {type(error).__name__}")
    return out


def provenance(judge: dict, commit: str | None) -> dict:
    """점수 파일 meta에 둘 표시: 사람 일치 미확인 말, 원래 실행의 커밋. 답 글은 넣지 않는다."""
    # [왜] 점수만 보는 사람에게 사람 일치가 확인되지 않았다는 것과 어느 실행의 점수인지가 보여야 한다
    # [주의] 원본(.raw.json)은 줄 목록이라 meta가 없다. 커밋은 --commit으로 받고, 없으면 미상으로 남긴다
    return {"label": judge["unchecked_label"], "commit": commit or "미상"}


def main() -> None:
    parser = argparse.ArgumentParser(description="ragas 채점")
    parser.add_argument("raw", help="scripts/run_eval.py run이 쓴 .raw.json")
    parser.add_argument("--out", required=True, help="점수 파일. 저장소 밖에 쓴 뒤 점수만 옮긴다")
    parser.add_argument("--commit", help="원래 실행(run_eval run)의 커밋")
    parser.add_argument("--dry-run", action="store_true", help="어림 비용만 찍는다")
    args = parser.parse_args()
    cfg, prices = load("rules/eval.yaml"), load("rules/pricing.yaml")
    judge = cfg["judge"]
    references = {item["id"]: item.get("reference", "") for item in load("eval/set_v1.yaml")["items"]}
    raw = json.loads(Path(args.raw).read_text(encoding="utf-8"))
    todo = samples(raw, references)
    skipped = not_scored(raw, references, todo)
    if skipped:
        print("채점하지 않은 정답 글 문항: " + ", ".join(f"{i}({why})" for i, why in skipped))
    # [왜] faithfulness 2번(주장 뽑기, 판정) + 근거마다 정밀도 1번 + 재현율 1번
    calls = sum(3 + len(s["ranked_texts"]) for s in todo)
    price = prices[judge["model"]]
    each = (
        judge["call_tokens"]["input"] * price["input"] + judge["call_tokens"]["output"] * price["output"]
    ) / 1e6
    print(
        f"채점 {len(todo)}문항, 호출 약 {calls}번, 어림 ${calls * each:.3f} (상한 ${judge['max_cost_usd']})"
    )
    if calls * each > judge["max_cost_usd"]:
        raise SystemExit(
            "어림 비용이 상한을 넘는다. 문항을 줄여 다시 돌린다"
        )  # [왜] 어림 실행도 같은 이유로 실패해 돈 쓰기 전에 보인다
    if args.dry_run:
        raise SystemExit(0)

    import anthropic
    import httpx2
    import ragas
    from ragas.metrics.collections import ContextPrecisionWithReference, ContextRecall, Faithfulness

    used = {"in": 0, "out": 0}

    async def count(response) -> None:
        # [왜] ragas는 토큰 수를 돌려주지 않는다. API 응답의 usage를 직접 더해 실제 비용을 남긴다
        await response.aread()
        usage = response.json().get("usage") or {}
        used["in"] += usage.get("input_tokens", 0)
        used["out"] += usage.get("output_tokens", 0)

    client = anthropic.AsyncAnthropic(
        api_key=os.environ["MARVIA_ANTHROPIC_API_KEY"],
        http_client=httpx2.AsyncClient(event_hooks={"response": [count]}, timeout=120),
    )
    llm = judge_llm(judge["model"], client)
    metrics = {
        "faithfulness": Faithfulness(llm=llm),
        "context_precision": ContextPrecisionWithReference(llm=llm),
        "context_recall": ContextRecall(llm=llm),
    }

    stopped = False

    async def run_all() -> list[dict]:
        nonlocal stopped
        done = []
        for s in todo:  # [왜] 한 번에 하나씩: 요청 한도(429)를 넘지 않는다
            if over_cap(used, price, judge["max_cost_usd"]):
                stopped = True
                break
            done.append(await score(s, metrics))
        return done

    scores = asyncio.run(run_all())
    cost = spent_usd(used, price)
    meta = {
        "judge": judge["model"],
        "ragas": ragas.__version__,
        "anthropic": anthropic.__version__,
        "raw": Path(args.raw).name,
        **provenance(judge, args.commit),
        "contexts": cfg["ragas"]["contexts"],
        "contexts_rule": cfg["ragas"]["contexts_rule"],
        "tokens": used,
        "cost_usd": round(cost, 4),
        "stopped": stopped,
    }
    Path(args.out).write_text(
        json.dumps({"meta": meta, "scores": scores}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(meta, ensure_ascii=False))
    if stopped:
        raise SystemExit(
            f"실제 비용이 상한 ${judge['max_cost_usd']}에 닿아 {len(scores)}/{len(todo)}문항에서 멈췄다"
        )


if __name__ == "__main__":
    main()
