"""평가 지표: 실행 결과 줄(rows)과 평가셋 문항(items)으로 점수를 낸다 (설계 11절, done 3.2).

하지 않는 일: 그래프 실행(run.py), LLM 채점(ragas는 scripts/ragas_score.py가 따로 돈다).
모두 순수 함수다. 키 없이 시험하고, 저장소에 둔 실행 결과를 지금 코드로 다시 채점할 수 있다(CI 재생 채점).
[왜] 해당 문항이 없으면 값은 0이 아니라 None이다. 빈 평균을 0.0으로 내면 "못 쟀다"와 "0점"이 섞인다
     (강의 IV 3주 04강: 정답이 0개면 max(n,1) 때문에 오류 없이 0.0이 나온다).
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Iterable

from marvia.eval.dataset import Item
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
    """검색 R@k: 근거 묶음(점수 높은 순) 앞 k개가 정답 근거를 몇 개 덮는지의 문항 평균."""
    values = []
    for r in rows:
        gold = items[r["id"]].gold
        if gold:
            top = r["evidence"][:k]
            values.append(sum(any(matches(u, [g]) for u in top) for g in gold) / len(gold))
    return _mean(values)


def mrr(rows: list[dict], items: dict[str, Item]) -> dict:
    """검색 MRR: 근거 묶음에서 처음 나온 정답 근거 순위의 역수(없으면 0)의 문항 평균."""
    values = []
    for r in rows:
        gold = items[r["id"]].gold
        if gold:
            rank = next((i for i, u in enumerate(r["evidence"], 1) if matches(u, gold)), None)
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
