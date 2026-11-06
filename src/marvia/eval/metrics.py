"""평가 지표: 실행 결과 줄(rows)과 평가셋 문항(items)으로 점수를 낸다 (설계 11절, done 3.2).

하지 않는 일: 그래프 실행(run.py), LLM 채점(ragas는 scripts/ragas_score.py가 따로 돈다).
모두 순수 함수다. 키 없이 시험하고, 저장소에 둔 실행 결과를 지금 코드로 다시 채점할 수 있다(CI 재생 채점).
[왜] 해당 문항이 없으면 값은 0이 아니라 None이다. 빈 평균을 0.0으로 내면 "못 쟀다"와 "0점"이 섞인다
     (강의 IV 3주 04강: 정답이 0개면 max(n,1) 때문에 오류 없이 0.0이 나온다).
"""

from __future__ import annotations

import math
import re
import statistics
from collections import Counter
from collections.abc import Iterable
from datetime import date

from marvia.eval.dataset import Domain, Item, Trajectory
from marvia.eval.run import articles
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


def unsupported_all(rows: list[dict]) -> dict:
    """근거 없이 답한 비율, 모든 문항 기준. 답하지 않아야 할 문항에서 근거 없이 답한 것도 센다."""
    return _mean([float(r["behaviour"] == "unsupported") for r in rows])


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
    for r in rows:
        # [왜] 칸이 빠진 줄을 0으로 세면 새는 번호·호출 상한 검사가 조용히 통과한다
        absent = [f for f in ("leak", "llm_calls") if f not in r]
        if absent:
            raise ValueError(f"줄 {r.get('id')}에 필수 칸이 없다: {', '.join(absent)}")
    calls = [r["real_llm_calls"] for r in rows if r.get("real_llm_calls") is not None]
    costs = [r["cost_usd"] for r in rows if r.get("cost_usd") is not None]
    limits = load_rules("agent")
    # [왜] 그래프가 센 호출(llm_calls)은 루프 상한과 작성자 상한을 합친 값을 넘을 수 없다 (설계 6.4)
    cap = limits["loop"]["max_llm_calls"] + limits["answer"]["max_write_attempts"]
    path = load_rules("eval")["trajectory"]
    seen = load_rules("eval")["rag_observations"]
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
        "unsupported_all": unsupported_all(rows),
        "calc_accuracy": calc_accuracy(rows, items),
        f"recall_at_{k}": recall_at_k(rows, items, k),
        "mrr": mrr(rows, items),
        # [왜] 계획자 길은 도구를 부르지 않는다. 에이전트 길 줄이 없으면 None이다
        "trajectory": trajectory_pass(rows, items, path["never"], path["max_calls"]),
        # 11-02 RAG 관찰 세 가지 (done 3.3). 근거 채점·고쳐 쓰기 기록(rag)과 검색 근거 순서로 센다
        "stray_articles": stray_articles(rows, items),
        "top_article_share": top_article_share(rows, seen["top"], seen["alert"]),
        "false_sufficient": false_sufficient(rows, items),
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
        "cap_breaches": sum(max(r.get("real_llm_calls") or 0, r["llm_calls"] or 0) > cap for r in rows),
        "cost_per_item_mean": round(statistics.fmean(costs), 5) if costs else None,
        "cost_per_item_max": max(costs) if costs else None,
        "cost_usd": round(sum(r.get("cost_usd") or 0 for r in rows), 4),
        "seconds_median": round(statistics.median([r["seconds"] for r in rows]), 1) if rows else None,
    }


# 비교 표의 칸: (요약 열쇠, 표 머리). recall은 meta.k로 열쇠를 만든다
TABLE = [
    ("correct_citation", "정답 근거 인용률"),
    ("wrong_evidence", "잘못된 근거"),
    ("behaviour_accuracy", "행동 정확도"),
    ("blocked_accuracy", "막힘 행동"),
    ("unsupported", "근거 없는 답"),
    ("unsupported_all", "근거 없는 답(전 문항)"),
    ("calc_accuracy", "계산"),
    ("recall", "R@k"),
    ("mrr", "MRR"),
    ("trajectory", "궤적"),
]


def cargo_count_lines(results: list[dict], ids: list[str]) -> list[str]:
    """결과마다 문항별로 읽은 화물 수 한 줄 (R09: 붙여 쓴 번호가 몇 건으로 읽혔나)."""
    lines = []
    for result in results:
        by_id = {r["id"]: r for r in result["rows"]}
        cells = [
            f"{i} {by_id[i]['cargo_count']}건" if "cargo_count" in by_id.get(i, {}) else f"{i} (기록 없음)"
            for i in ids
        ]
        lines.append(f"{result['meta']['loop']} {result['meta']['model']}: " + ", ".join(cells))
    return lines


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


def ragas_means(scores: list[dict], metrics: list[str], calc_ids: Iterable[str] = ()) -> dict:
    """ragas 점수의 지표별 평균. 못 잰 값(None, NaN)은 평균에서 빼고 따로 센다.

    calc_ids(계산 줄이 있는 문항)는 충실도에서 빼고 faithfulness_calc로 따로 낸다. 다른 지표는 모두 센다.
    """
    # [왜] 강의 IV 3주 05강: evaluate()는 실패해도 NaN을 돌려주고, NaN이 섞이면 평균이 조용히 바뀐다
    # [왜] 계산·화물 줄은 ragas 맥락(근거 글)에 없어 계산 문항의 충실도는 0.00~0.30으로 낮게 나온다
    calc = set(calc_ids)

    def mean_of(name: str, rows: list[dict]) -> dict:
        values = [s[name] for s in rows if s.get(name) is not None and s[name] == s[name]]
        return _mean(values) | {"missing": len(rows) - len(values)}

    out = {}
    for name in metrics:
        if name == "faithfulness" and calc:
            out[name] = mean_of(name, [s for s in scores if s.get("id") not in calc])
            out["faithfulness_calc"] = mean_of(name, [s for s in scores if s.get("id") in calc])
        else:
            out[name] = mean_of(name, scores)
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


def loosened(old: dict, new: dict) -> list[dict]:
    """바닥이 내려갔거나 천장이 올라갔거나 사라진 지표를 {metric, old, new}로 돌려준다."""
    out = []
    for key, bound in old.items():
        side = "min" if "min" in bound else "max"
        now = new.get(key, {}).get(side)
        if now is None or (now < bound[side] if side == "min" else now > bound[side]):
            out.append({"metric": key, "old": bound[side], "new": now})
    return out


def gate_block(file: str, new_floors: dict, old_gate: dict, ruling: str | None, today: str) -> dict:
    """rules/eval.yaml에 쓸 gate 묶음. 느슨해지는 값은 판정 이유(ruling) 없이는 거절한다."""
    # [왜] 결과를 보고 바닥값을 조용히 내리면 CI 문이 아무것도 못 막는다 (R-060). 내리려면 이유를 남긴다
    if ruling and "\n" in ruling:
        raise ValueError("--ruling에는 줄바꿈을 쓸 수 없다. 한 줄로 쓴다")
    changes = loosened(old_gate.get("floors", {}), new_floors)
    rulings = list(old_gate.get("rulings", []))
    if changes:
        if not ruling:
            names = ", ".join(c["metric"] for c in changes)
            raise ValueError(f'바닥이 내려가거나 천장이 올라간다({names}). --ruling "<이유>"가 있어야 쓴다')
        rulings += [{"date": today, **c, "reason": ruling} for c in changes]
    return {"file": file, "floors": new_floors} | ({"rulings": rulings} if rulings else {})


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


def gate_uncovered(rows: list[dict], items: dict[str, Item]) -> list[str]:
    """결과 줄이 평가셋 문항을 빠짐없이 한 번씩 덮지 않은 곳을 돌려준다. 빈 목록이면 모두 덮음.

    [왜] 상한에서 멈춘 결과도 종료 코드 0으로 저장돼, 일부만 담은 파일이 일부로만 판정돼 통과한다.
    """
    seen = Counter(row["id"] for row in rows)
    return (
        [f"빠짐: {i}" for i in items if i not in seen]
        + [f"겹침: {i}" for i, n in seen.items() if n > 1]
        + [f"셋에 없음: {i}" for i in seen if i not in items]
    )


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


def _article(unit_id: str) -> str:
    """unit_id의 조문 이름. L001556@20261002#제241조.3항 → 제241조."""
    return unit_id.split("#", 1)[1].split(".", 1)[0]


def stray_articles(rows: list[dict], items: dict[str, Item]) -> dict:
    """질문 밖 조문(11-02 관찰 ①): 고친 질의에 질문에도 정답·also_ok에도 없는 조문 번호가 든 비율."""
    flags = []
    for r in rows:
        item = items[r["id"]]
        allowed = set(articles(item.question)) | {_article(u) for u in item.gold + item.also_ok}
        flags += [
            float(bool(set(e["articles"]) - allowed)) for e in r.get("rag", []) if e["step"] == "rewrite"
        ]
    return _mean(flags)


def top_article_share(rows: list[dict], top: int, alert: float) -> dict:
    """한 조문 쏠림(11-02 관찰 ②): 첫 채점 묶음 앞 top개 중 한 조문의 최대 몫. 11-02에는 8개 중 7개."""
    shares, skipped = [], 0
    for r in rows:
        # [왜] 첫 채점 묶음만 본다. retrieved는 모든 묶음의 합집합이라 뒷 묶음이 앞 묶음에 섞인다
        first = next((e["units"] for e in r.get("rag", []) if e["step"] == "grade"), None)
        if not first:
            skipped += 1  # 채점 묶음이 없는 줄(검색을 안 탄 문항)은 따로 센다
            continue
        head = first[:top]
        # [왜] 법령까지 넣어 센다. 관세법 제9조와 시행령 제9조는 다른 조문이다
        keys = [u.split(".", 1)[0] for u in head]
        shares.append(Counter(keys).most_common(1)[0][1] / len(head))
    return _mean(shares) | {"over": sum(share >= alert for share in shares), "skipped": skipped}


def false_sufficient(rows: list[dict], items: dict[str, Item]) -> dict:
    """근거 없이 충분(11-02 관찰 ③): 정답이 있는 문항의 "충분" 채점 가운데 본 근거에 정답이 없던 비율."""
    flags = []
    for r in rows:
        gold = items[r["id"]].gold
        if gold:
            graded = [e for e in r.get("rag", []) if e["step"] == "grade" and e["sufficient"]]
            flags += [float(not any(matches(u, gold) for u in e["units"])) for e in graded]
    return _mean(flags)


def rag_table(results: list[dict]) -> str:
    """검색 실험 표 (done 3.3): 맥락 문장 켜기·끄기와 11-02 관찰 세 가지."""
    head = [
        "길",
        "모델",
        "R@k",
        "MRR",
        "정답 근거 인용률",
        "질문 밖 조문",
        "한 조문 몫(넘은 수)",
        "근거 없이 충분",
    ]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for result in results:
        meta, s = result["meta"], result["summary"]
        cells = [meta["loop"] + (f" ({meta['tag']})" if meta.get("tag") else ""), meta["model"]]
        for metric in [s[f"recall_at_{meta['k']}"], s["mrr"], s["correct_citation"], s["stray_articles"]]:
            cells.append("-" if metric["value"] is None else f"{metric['value']:.2f} ({metric['n']})")
        share = s["top_article_share"]
        cells.append(
            "-"
            if share["value"] is None
            else f"{share['value']:.2f} ({share['over']}/{share['n']}, 빠짐 {share['skipped']})"
        )
        sufficient = s["false_sufficient"]
        cells.append("-" if sufficient["value"] is None else f"{sufficient['value']:.2f} ({sufficient['n']})")
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _mentions_date(text: str, day: date) -> bool:
    """글에 그 날짜가 있나: 2026-11-26, 2026.11.26, 2026년 11월 26일, 11월 26일."""
    y, m, d = day.year, day.month, day.day
    full = rf"{y}\s*[-./년]\s*0?{m}\s*[-./월]\s*0?{d}(?!\d)"
    short = rf"(?<!\d)0?{m}\s*월\s*0?{d}\s*일"
    return bool(re.search(full, text) or re.search(short, text))


_AFTER_LAW = "[ \\t」』\"'”’]"  # 법령 이름 뒤에 올 수 있는 글자: 공백, 닫는 낫표·따옴표 (줄바꿈은 아니다)
# 다른 법령 이름의 시작: 한글+법, 시행령, 시행규칙. 말미 조사는 허용한다
# shortcut: "신고방법"처럼 법으로 끝나는 낱말도 경계로 본다. 오탐이 보이면 corpus/sources.yaml 목록으로 바꾼다
_OTHER_LAW = re.compile(
    r"(?<![가-힣])[가-힣]{2,}법(?:(?![가-힣])|(?=[은는이가과와의을를에도]))|시행령|시행규칙|[\n]|[.!?](?=\s|$)"
)


def _mentions_article(text: str, article: str) -> bool:
    """글에 그 법령의 그 조문이 있나. article은 "관세법 제241조" 모양이고, 제241조의2는 제241조가 아니다.

    법령 이름(앞에 한글이 없는 것)이 나오면 다음 다른 법령 이름, 줄 끝, 문장 끝까지가 그 법령의 범위다.
    조문은 그 범위 안에서 찾는다. 이름 바로 뒤에 시행령·시행규칙이 오면 다른 법령이다.
    """
    law, label = article.rsplit(" ", 1)
    found = re.fullmatch(r"제(\d+)조(?:의(\d+))?", label)
    assert found, article
    number, sub = found.groups()
    pattern = rf"(?<!\d)제?\s*{number}\s*조" + (rf"\s*의\s*{sub}" if sub else r"(?!\s*의\s*\d)")
    for start in re.finditer(rf"(?<![가-힣]){re.escape(law)}", text):
        rest = text[start.end() :]
        if re.match(rf"{_AFTER_LAW}*(시행령|시행규칙)", rest):
            continue  # [왜] "관세법 시행령"은 관세법이 아니다
        stop = _OTHER_LAW.search(rest)
        if re.search(pattern, rest[: stop.start()] if stop else rest):
            return True
    return False


def free_answer_score(text: str, domain: Domain) -> dict:
    """자유 글 답에서 통관 단계·기한·조문을 찾는다 (done 3.8). 범용 도구와 Marvia의 답에 같은 자를 댄다."""
    return {
        "stage": None if domain.stage is None else domain.stage in text,
        "due": None if domain.due is None else _mentions_date(text, domain.due),
        "article": None if domain.article is None else _mentions_article(text, domain.article),
    }


def domain_table(answers: dict[str, dict[str, str]], items: dict[str, Item]) -> str:
    """도구별(Marvia, Claude Code, Codex) 단계·기한·조문을 맞힌 수의 표. answers: {도구: {문항 id: 답}}."""
    lines = ["| 도구 | 통관 단계 | 기한 | 조문 | 답한 문항 |", "|---|---|---|---|---|"]
    for tool, by_id in answers.items():
        scores = [free_answer_score(text, d) for i, text in by_id.items() if (d := items[i].domain)]
        cells = [tool]
        for key in ("stage", "due", "article"):
            marks = [s[key] for s in scores if s[key] is not None]
            cells.append(f"{sum(marks)}/{len(marks)}")
        lines.append("| " + " | ".join(cells + [str(len(scores))]) + " |")
    return "\n".join(lines)
