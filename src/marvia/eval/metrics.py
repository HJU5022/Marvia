"""평가 지표: 실행 결과 줄(rows)과 평가셋 문항(items)으로 점수를 낸다 (설계 11절, done 3.2).

하지 않는 일: 그래프 실행(run.py), LLM 채점(ragas는 scripts/ragas_score.py가 따로 돈다).
모두 순수 함수다. 키 없이 시험하고, 저장소에 둔 실행 결과를 지금 코드로 다시 채점할 수 있다(CI 재생 채점).
[왜] 해당 문항이 없으면 값은 0이 아니라 None이다. 빈 평균을 0.0으로 내면 "못 쟀다"와 "0점"이 섞인다
     (강의 IV 3주 04강: 정답이 0개면 max(n,1) 때문에 오류 없이 0.0이 나온다).
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Iterable

from marvia.eval.dataset import Item, Trajectory
from marvia.tools.rules import load_rules


def matches(unit_id: str, golds: Iterable[str]) -> bool:
    """unit_id가 정답 목록의 어느 하나와 같거나 그 아래 단위인가."""
    # [왜] "." 뒤만 아래 단위로 본다. 제241조.3항은 제241조 아래지만 제241조의2는 다른 조문이다
    return any(unit_id == gold or unit_id.startswith(gold + ".") for gold in golds)


def _mean(values: list[float]) -> dict:
    """평균과 문항 수. 문항이 없으면 값은 None."""
    return {"value": round(statistics.fmean(values), 4) if values else None, "n": len(values)}


def calc_ok(row: dict, item: Item) -> bool | None:
    """코드 계산이 정답과 같은가. 정답 계산이 없는 문항은 None."""
    if item.calc is None:
        return None
    calc = row.get("calc") or {}
    got = {(d["name"], d["due"]) for d in calc.get("deadlines", [])}
    # [왜] 기한은 정답에 적은 것이 모두 있으면 맞다. 화물이 여럿이면 다른 기한이 더 있을 수 있다
    want = {(d.name, d.due.isoformat()) for d in item.calc.deadlines}
    reimport_ok = item.calc.reimport is None or calc.get("reimport") == item.calc.reimport
    return want <= got and reimport_ok


def behaviour_ok(row: dict, item: Item) -> bool:
    """행동이 맞는가. 답을 냈고 정답 계산이 있으면 계산도 같아야 맞다."""
    if row["behaviour"] not in item.behaviour:
        return False
    return row["behaviour"] != "answer" or calc_ok(row, item) is not False


def correct_citation(rows: list[dict], items: dict[str, Item]) -> dict:
    """정답 근거 인용률: 정답 근거가 있는 문항 가운데 답의 인용에 정답 근거가 하나라도 있는 비율."""
    hits = [
        float(any(matches(c, items[r["id"]].gold) for c in r["cited"])) for r in rows if items[r["id"]].gold
    ]
    return _mean(hits)


def wrong_evidence(rows: list[dict], items: dict[str, Item]) -> dict:
    """잘못된 근거 비율: 채점하는 문항의 인용 가운데 정답도 also_ok도 아닌 인용의 비율.

    단위는 인용(n = 인용 수)이다. 한 줄에서 같은 unit_id를 여러 번 인용해도 한 번만 센다.
    채점하는 문항은 정답 근거가 있는 문항과 비관련 문항(인용하면 모두 틀림)이다.
    정답 없는 관련 문항(화물 상태, 번호 없음)의 인용은 세지 않는다.
    """
    flags = []
    for r in rows:
        item = items[r["id"]]
        if item.gold or item.group == "unrelated":
            flags += [float(not matches(c, item.gold + item.also_ok)) for c in set(r["cited"])]
    return _mean(flags)


def behaviour_accuracy(rows: list[dict], items: dict[str, Item], group: str | None = None) -> dict:
    """행동 정확도. group을 주면 그 갈래(blocked면 막힘 행동 정확도)만 본다."""
    picked = [r for r in rows if group is None or items[r["id"]].group == group]
    return _mean([float(behaviour_ok(r, items[r["id"]])) for r in picked])


def unsupported(rows: list[dict], items: dict[str, Item]) -> dict:
    """근거 없이 답한 비율: 답해야 하는 문항(맞는 행동에 answer) 가운데 근거·계산·화물 없이 답한 비율."""
    picked = [r for r in rows if "answer" in items[r["id"]].behaviour]
    return _mean([float(r["behaviour"] == "unsupported") for r in picked])


def recall_at_k(rows: list[dict], items: dict[str, Item], k: int) -> dict:
    """검색 R@k: RAG 순위(row.retrieved) 앞 k개가 정답 근거를 몇 개 덮는지의 문항 평균."""
    values = []
    for r in rows:
        gold = items[r["id"]].gold
        if gold:
            top = r["retrieved"][:k]
            values.append(sum(any(matches(u, [g]) for u in top) for g in gold) / len(gold))
    return _mean(values)


def mrr(rows: list[dict], items: dict[str, Item]) -> dict:
    """검색 MRR: RAG 순위에서 처음 나온 정답 근거 순위의 역수(없으면 0)의 문항 평균."""
    values = []
    for r in rows:
        gold = items[r["id"]].gold
        if gold:
            rank = next((i for i, u in enumerate(r["retrieved"], 1) if matches(u, gold)), None)
            values.append(1 / rank if rank else 0.0)
    return _mean(values)


def calc_accuracy(rows: list[dict], items: dict[str, Item]) -> dict:
    """계산 정확도: 정답 계산이 있는 문항 가운데 코드 계산 칸이 정답과 같은 비율."""
    flags = [calc_ok(r, items[r["id"]]) for r in rows]
    return _mean([float(f) for f in flags if f is not None])


def summarize(rows: list[dict], items: dict[str, Item], k: int) -> dict:
    """실행 한 번(길 하나 × 모델 하나)의 요약. 저장소에 남기는 숫자다."""
    calls = [r["real_llm_calls"] for r in rows if r.get("real_llm_calls") is not None]
    costs = [r["cost_usd"] for r in rows if r.get("cost_usd") is not None]
    limits = load_rules("agent")
    # [왜] 그래프가 센 호출(llm_calls)은 루프 상한과 작성자 상한을 합친 값을 넘을 수 없다 (설계 6.4)
    cap = limits["loop"]["max_llm_calls"] + limits["answer"]["max_write_attempts"]
    path = load_rules("eval")["trajectory"]
    return {
        "n": len(rows),
        "errors": sum(bool(r.get("error")) for r in rows),
        "leaks": sum(bool(r.get("leak")) for r in rows),
        "behaviours": dict(Counter(r["behaviour"] for r in rows)),
        "correct_citation": correct_citation(rows, items),
        "wrong_evidence": wrong_evidence(rows, items),
        "behaviour_accuracy": behaviour_accuracy(rows, items),
        "blocked_accuracy": behaviour_accuracy(rows, items, "blocked"),
        "unrelated_accuracy": behaviour_accuracy(rows, items, "unrelated"),
        "unsupported": unsupported(rows, items),
        "calc_accuracy": calc_accuracy(rows, items),
        f"recall_at_{k}": recall_at_k(rows, items, k),
        "mrr": mrr(rows, items),
        # [왜] 계획자 길은 도구를 부르지 않는다. 에이전트 길 줄이 없으면 None이다
        "trajectory": trajectory_pass(rows, items, path["never"], path["max_calls"]),
        "llm_calls_median": statistics.median(calls) if calls else None,
        "llm_calls_max": max(calls) if calls else None,
        # [왜] 두 길을 같은 통계로 잰다(R-040). 근거 있는 답 비율 = 내용 있는 답을 낸 줄(answer, unsupported)
        #      가운데 인용이나 코드 계산이 있는 줄. unsupported를 분모에 넣어야 비율이 부풀지 않는다.
        #      거절·되물음·포워더 안내(guide, 번호 없이 맞는 행동)는 뺀다
        "evidence_backed": _mean(
            [
                float(bool(r["cited"] or any((r.get("calc") or {}).values())))
                for r in rows
                if r["behaviour"] in ("answer", "unsupported")
            ]
        ),
        "cap_breaches": sum((r.get("llm_calls") or 0) > cap for r in rows),
        "cost_per_item_mean": round(statistics.fmean(costs), 5) if costs else None,
        "cost_per_item_max": max(costs) if costs else None,
        "cost_usd": round(sum(r.get("cost_usd") or 0 for r in rows), 4),
        "seconds_median": statistics.median([r["seconds"] for r in rows]) if rows else None,
    }


# 비교 표의 칸: (요약 열쇠, 표 머리). recall은 meta.k로 열쇠를 만든다
TABLE = [
    ("correct_citation", "정답 근거 인용률"),
    ("wrong_evidence", "잘못된 근거"),
    ("behaviour_accuracy", "행동 정확도"),
    ("blocked_accuracy", "막힘 행동"),
    ("unsupported", "근거 없는 답"),
    ("calc_accuracy", "계산"),
    ("recall", "R@k"),
    ("mrr", "MRR"),
    ("trajectory", "궤적"),
]


def compare_table(results: list[dict]) -> str:
    """실행 결과 파일들(길 × 모델)의 요약을 마크다운 표 하나로 만든다 (done 3.7 모델 비교표)."""
    head = (
        ["길", "모델"]
        + [name for _, name in TABLE]
        + ["근거 있는 답", "LLM 호출 중앙값·최대", "상한 넘음", "비용 합·문항당 최대($)", "시간 중앙값(초)"]
        + ["오류", "새는 번호"]
    )
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for result in results:
        meta, summary = result["meta"], result["summary"]
        cells = [meta["loop"] + (f" ({meta['tag']})" if meta.get("tag") else ""), meta["model"]]
        for key, _ in TABLE:
            metric = summary[f"recall_at_{meta['k']}" if key == "recall" else key]
            cells.append("-" if metric["value"] is None else f"{metric['value']:.2f} ({metric['n']})")
        backed = summary["evidence_backed"]
        cells.append("-" if backed["value"] is None else f"{backed['value']:.2f} ({backed['n']})")
        cells += [f"{summary['llm_calls_median']}·{summary['llm_calls_max']}", summary["cap_breaches"]]
        cells += [f"{summary['cost_usd']}·{summary['cost_per_item_max']}", summary["seconds_median"]]
        cells += [summary["errors"], summary["leaks"]]
        lines.append("| " + " | ".join(str(cell) for cell in cells) + " |")
    return "\n".join(lines)


def bucket(score: float, cuts: list[float]) -> float:
    """0~1 점수를 사람 채점과 같은 세 칸(1, 0.5, 0)으로 나눈다. cuts는 [1의 하한, 0.5의 하한]이다."""
    return 1.0 if score >= cuts[0] else 0.5 if score >= cuts[1] else 0.0


def agreement(human: dict[str, float], judge: dict[str, float | None], cuts: list[float]) -> dict:
    """사람 채점과 LLM 채점(ragas faithfulness)이 같은 칸에 든 문항의 비율."""
    # [왜] 설계 11절: LLM 채점은 사람 채점 10건과 일치율을 확인한 뒤에 쓴다
    pairs = [(h, judge[i]) for i, h in human.items() if judge.get(i) is not None]
    same = [float(bucket(j, cuts) == h) for h, j in pairs if j is not None]
    diff = [abs(h - j) for h, j in pairs if j is not None]
    return {
        "value": round(statistics.fmean(same), 4) if same else None,
        "n": len(same),
        "mean_abs_diff": round(statistics.fmean(diff), 4) if diff else None,
    }


def ragas_means(scores: list[dict], metrics: list[str]) -> dict:
    """ragas 점수의 지표별 평균. 못 잰 값(None, NaN)은 평균에서 빼고 따로 센다."""
    # [왜] 강의 IV 3주 05강: evaluate()는 실패해도 NaN을 돌려주고, NaN이 섞이면 평균이 조용히 바뀐다
    out = {}
    for name in metrics:
        values = [s[name] for s in scores if s.get(name) is not None and s[name] == s[name]]
        out[name] = _mean(values) | {"missing": len(scores) - len(values)}
    return out


def human_faithful(grades: dict) -> dict[str, float]:
    """사람 채점 파일의 faithful 칸. 비었거나 1, 0.5, 0이 아닌 문항이 있으면 이름을 대고 멈춘다."""
    bad = sorted(i for i, g in grades.items() if g.get("faithful") not in (0, 0.5, 1))
    if bad:
        raise ValueError(f"사람 채점 faithful이 비었거나 1, 0.5, 0이 아니다: {', '.join(bad)}")
    return {i: float(g["faithful"]) for i, g in grades.items()}


def unscored(human: dict[str, float], judge: dict[str, float | None]) -> list[str]:
    """사람 채점은 있는데 LLM 채점 값이 없는(못 쟀거나 NaN) 문항."""
    # [왜] 일부만 견준 일치율로 '사람 일치 확인'을 달면 안 된다: 사람 채점 문항을 모두 견줄 때만 확인으로 친다
    return sorted(i for i in human if judge.get(i) is None or judge[i] != judge[i])


# CI 문이 보는 지표. 높을수록 좋은 것은 바닥값(min), 낮을수록 좋은 것은 천장값(max)을 둔다
HIGHER = ["correct_citation", "behaviour_accuracy", "blocked_accuracy", "calc_accuracy", "mrr", "trajectory"]
LOWER = ["wrong_evidence", "unsupported"]


def _cents(value: float) -> float:
    """값 × 100을 소수 여섯째 자리에서 반올림한다."""
    # [왜] 0.1 + 0.05가 0.15000000000000002가 되어 올림이 한 칸 더 가지 않게 한다
    return round(value * 100, 6)


def floors(summary: dict, k: int) -> dict:
    """기준 실행의 요약으로 CI 문의 바닥·천장값을 만든다. 오류, 새는 번호, 호출 상한 넘음은 늘 0이다."""
    out: dict = {"errors": {"max": 0}, "leaks": {"max": 0}, "cap_breaches": {"max": 0}}
    for key in HIGHER + [f"recall_at_{k}"]:
        metric = summary[key]
        if metric["value"] is not None:
            # [왜] 실제 모델 실행은 같은 코드에서도 한 문항쯤 흔들린다. 한 문항만큼(1/n) 아래까지 통과시킨다
            out[key] = {"min": max(0.0, math.floor(_cents(metric["value"] - 1 / metric["n"])) / 100)}
    for key in LOWER:
        metric = summary[key]
        if metric["value"] is not None:
            out[key] = {"max": min(1.0, math.ceil(_cents(metric["value"] + 1 / metric["n"])) / 100)}
    return out


def gate_violations(summary: dict, bounds: dict) -> list[str]:
    """요약이 바닥·천장값을 어긴 지표를 한 줄씩 돌려준다. 빈 목록이면 통과. 못 잰 지표도 어긴 것으로 본다."""
    out = []
    for key, bound in bounds.items():
        metric = summary.get(key)
        value = metric["value"] if isinstance(metric, dict) else metric
        if value is None:
            out.append(f"{key}: 재지 못했다")
        elif "min" in bound and value < bound["min"]:
            out.append(f"{key}: {value} < 바닥 {bound['min']}")
        elif "max" in bound and value > bound["max"]:
            out.append(f"{key}: {value} > 천장 {bound['max']}")
    return out


# 바닥값 묶음에 늘 있어야 하는 칸. 이 중 하나라도 빠지면 평가 문이 그 지표를 안 본 채 통과한다
REQUIRED_BOUNDS = {"errors": 0, "leaks": 0, "cap_breaches": 0}


def gate_missing(bounds: dict) -> list[str]:
    """바닥값 묶음에서 빠졌거나 천장이 0이 아닌 필수 칸을 돌려준다. 빈 묶음이면 필수 칸이 모두 나온다."""
    return [key for key, cap in REQUIRED_BOUNDS.items() if bounds.get(key) != {"max": cap}]


def trajectory_violations(tools: list[str], spec: Trajectory, never: list[str], max_calls: int) -> list[str]:
    """에이전트 길의 도구 호출 순서가 문항 조건을 어긴 곳을 한 줄씩 돌려준다 (done 3.4). 빈 목록이면 통과.

    입력: tools=부른 도구 이름(부른 순서), spec=문항 조건, never=모든 문항에서 부르면 안 되는 도구,
          max_calls=문항에 상한이 없을 때의 도구 호출 수 상한.
    """
    out = [f"불러야 함: {need}" for need in spec.must if not set(need.split("|")) & set(tools)]
    out += [f"부르면 안 됨: {name}" for name in spec.must_not + never if name in tools]
    for first, then in spec.order:
        if first in tools and then in tools and tools.index(then) < tools.index(first):
            out.append(f"순서: {first} 다음에 {then}")
    cap = spec.max_calls or max_calls
    if len(tools) > cap:
        out.append(f"호출 {len(tools)}번 > 상한 {cap}")
    return out


def trajectory_pass(rows: list[dict], items: dict[str, Item], never: list[str], max_calls: int) -> dict:
    """궤적 통과율: 에이전트 길에서 오류 없이 끝난 문항 가운데 도구 호출 조건을 모두 지킨 비율."""
    picked = [r for r in rows if r.get("loop") == "agent" and not r.get("error")]
    flags = [
        not trajectory_violations(r["tools"], items[r["id"]].trajectory, never, max_calls) for r in picked
    ]
    return _mean([float(f) for f in flags])
