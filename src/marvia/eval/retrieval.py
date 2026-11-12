"""검색 전용 측정의 계산 규칙: LLM 없이 검색 단계만 잴 때의 문항 읽기, 순위 만들기, 요약 (설계 11절).

scripts/retrieval_check.py가 쓴다. 검색 호출은 여기서 하지 않고 후보와 리랭커 함수를 받아 계산만 한다.
세는 법 세 가지:
- 단위 기준: 정답 단위(같거나 "." 아래)가 상위 k 안에 있나. marvia.eval.metrics의 R@k·MRR과 같은 규칙이다.
- 조문 기준: 단위를 조·항(별표는 세 마디)으로 묶어 같은 조·항의 호들이 자리를 여럿 차지하지 않게 한 뒤 센다.
- 엄격: 검색 전용 평가셋에서 질문을 쓴 그 단위(source_unit) 하나만 정답으로 본다.
하지 않는 일: 에이전트 실행의 채점(metrics.py), 임베딩 모델 비교, 그래프 켜고 끈 비교(설정은 MARVIA_GRAPH).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

import yaml

from marvia.eval.dataset import load_set
from marvia.eval.metrics import matches
from marvia.graph.rag import rerank_input
from marvia.identify.mask import mask_text
from marvia.rag.models import Evidence

SET_LAYER = "set"  # 평가셋(set_v*.yaml) 문항에 붙이는 층 이름. 검색 전용셋은 문항마다 layer가 있다
ALL = "all"  # 전체 문항 요약의 이름


def load_items(path: Path) -> tuple[list[dict], date, str]:
    """문항 파일을 (문항들, 기준 날짜, 판 이름)으로 읽는다. 문항은 id, layer, query, gold를 갖는다.

    검색 전용 평가셋(items에 query가 있다)은 also_ok, source_unit, importer_question도 그대로 둔다.
    평가셋(set_v*.yaml)은 정답 근거가 있는 문항만 고르고 질문 글을 질의로 쓴다.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if "query" in data["items"][0]:
        return data["items"], date.fromisoformat(str(data["as_of"])), str(data["version"])
    loaded = load_set(path)
    # [주의] 평가셋의 also_ok는 "인용해도 틀리지 않은 단위"일 뿐 검색 정답이 아니라 옮기지 않는다.
    #        질문 속 화물 번호는 가린 토큰으로 바꿔 보낸다(가공값이지만 규칙을 지킨다)
    items = [
        {"id": i.id, "layer": SET_LAYER, "query": mask_text(i.question)[0], "gold": i.gold}
        for i in loaded.items
        if i.gold
    ]
    return items, loaded.as_of, loaded.version


def article_group(unit_id: str) -> str:
    """단위를 조·항으로 묶은 이름. 조문은 첫 마디에 둘째 마디가 "항"이면 거기까지, 별표는 앞 세 마디까지."""
    head, _, path = unit_id.partition("#")
    parts = path.split(".")
    if parts[0].startswith("별표"):
        keep = parts[:3]
    else:
        keep = parts[:2] if len(parts) > 1 and parts[1].endswith("항") else parts[:1]
    return f"{head}#{'.'.join(keep)}"


def capped(ranked: list[str], cap: int) -> list[str]:
    """같은 조·항의 단위를 앞에서부터 cap개까지만 두고 나머지는 원래 순서대로 맨 뒤로 미룬다. 0이면 그대로."""
    if not cap:
        return ranked
    seen: dict[str, int] = {}
    keep, later = [], []
    for unit_id in ranked:
        group = article_group(unit_id)
        seen[group] = seen.get(group, 0) + 1
        (keep if seen[group] <= cap else later).append(unit_id)
    return keep + later


def targets(item: dict, strict: bool) -> list[list[str]]:
    """맞음 조건: 목록마다 하나라도 찾으면 그 목록은 맞음이다. 목록 수가 R@k의 분모다."""
    if strict and item.get("source_unit"):
        return [[item["source_unit"]]]
    if item.get("also_ok"):
        # [왜] also_ok는 하나뿐인 정답의 "이것을 찾아도 맞음"이다. 정답이 여럿이면 짝을 알 수 없다
        assert len(item["gold"]) == 1, item["id"]
        return [item["gold"] + item["also_ok"]]
    return [[gold] for gold in item["gold"]]


def _recall(ranked: list[str], wanted: list[list[str]]) -> float:
    return sum(any(matches(u, alt) for u in ranked) for alt in wanted) / len(wanted)


def _reciprocal_rank(ranked: list[str], wanted: list[list[str]]) -> float:
    flat = [gold for alt in wanted for gold in alt]
    rank = next((n for n, u in enumerate(ranked, 1) if matches(u, flat)), None)
    return 1 / rank if rank else 0.0


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4)


def _unique(ids: list[str]) -> list[str]:
    return list(dict.fromkeys(ids))


def summarize(rows: list[dict], k: int) -> dict:
    """문항 줄들의 요약. 줄은 문항 칸에 cand(후보 unit_id 전체)와 retrieved(순위)를 더한 것이다."""
    wide = [targets(r, strict=False) for r in rows]
    strict = [targets(r, strict=True) for r in rows]
    # 조문 기준: 정답과 순위를 같은 규칙으로 묶고, 처음 나온 순서를 지켜 중복을 없앤다
    grouped_wanted = [[_unique([article_group(g) for g in alt]) for alt in w] for w in wide]
    grouped_ranked = [_unique([article_group(u) for u in r["retrieved"]]) for r in rows]
    top = [r["retrieved"][:k] for r in rows]
    pairs = list(zip(top, wide, strict=True))
    grouped = [(ranked[:k], wanted) for ranked, wanted in zip(grouped_ranked, grouped_wanted, strict=True)]
    exact = list(zip(top, strict, strict=True))
    return {
        "n": len(rows),
        # 후보 포함률: 리랭커가 보기 전 후보 전체에 정답이 있었나. 여기 없으면 리랭커도 올릴 수 없다
        "cand_recall": _mean([_recall(r["cand"], w) for r, w in zip(rows, wide, strict=True)]),
        "cand_mean": round(sum(len(r["cand"]) for r in rows) / len(rows), 1),
        "unit_r_at_k": _mean([_recall(ranked, w) for ranked, w in pairs]),
        "unit_mrr": _mean([_reciprocal_rank(ranked, w) for ranked, w in pairs]),
        "article_r_at_k": _mean([_recall(ranked, w) for ranked, w in grouped]),
        "article_mrr": _mean([_reciprocal_rank(ranked, w) for ranked, w in grouped]),
        "strict_r_at_k": _mean([_recall(ranked, w) for ranked, w in exact]),
        "strict_mrr": _mean([_reciprocal_rank(ranked, w) for ranked, w in exact]),
    }


def summarize_layers(rows: list[dict], k: int) -> dict[str, dict]:
    """층별 요약과 전체 요약(all). 수입자의 질문이 아닌 문항이 있으면 그것을 뺀 층 b(b_importer)도 낸다."""
    layers = {name: [r for r in rows if r["layer"] == name] for name in sorted({r["layer"] for r in rows})}
    if any(r.get("importer_question") is False for r in rows):
        layers["b_importer"] = [
            r for r in rows if r["layer"] == "b" and r.get("importer_question") is not False
        ]
    layers[ALL] = rows
    return {name: summarize(group, k) for name, group in layers.items() if group}


def rank_item(
    query: str,
    candidates: list[Evidence],
    scores: Callable[[str, list[str]], list[float]],
    *,
    rerank: bool,
    cap: int,
) -> dict:
    """후보를 순위로 만든다: 리랭커를 켜면 점수 내림차순(top_ranked와 같은 정렬), 끄면 후보 순서 그대로.

    cap이 있으면 같은 조·항의 단위를 cap개까지만 앞에 둔다. 돌려주는 순위는 후보 전체다(자르지 않는다).
    """
    ids = [c.unit_id for c in candidates]
    ranked = ids
    if rerank and candidates:
        # [왜] 제품 길(top_ranked)과 같은 글을 리랭커에 넘긴다. 다르면 잰 값이 제품의 값이 아니다
        marks = scores(query, rerank_input(candidates))
        ranked = [u for u, _ in sorted(zip(ids, marks, strict=True), key=lambda pair: pair[1], reverse=True)]
    return {
        "cand": ids,
        "ranked": capped(ranked, cap),
        # [주의] 후보 가운데 그래프가 더한 단위와 조문 직접 조회로 넣은 단위의 수다 (리랭커 앞)
        "graph": sum(c.origin == "graph" for c in candidates),
        "provision": sum(c.origin == "provision" for c in candidates),
    }


Search = Callable[[str, date], list[Evidence]]


def measure(
    items: list[dict],
    as_of: date,
    search: Search,
    scores: Callable[[str, list[str]], list[float]],
    *,
    rerank: bool,
    cap: int,
    ranked: Search | None = None,
) -> list[dict]:
    """문항마다 후보를 찾아 순위를 만든 줄을 돌려준다. 줄에는 문항 칸(질의 글 제외)과 unit_id만 둔다.

    ranked를 주면 순위는 그 함수의 결과다(MCP 길: 서버가 검색과 리랭커를 함께 돈다).
    후보는 search로 따로 본다.
    """
    rows = []
    for item in items:
        found = rank_item(item["query"], search(item["query"], as_of), scores, rerank=rerank, cap=cap)
        if ranked is not None:
            found["ranked"] = [e.unit_id for e in ranked(item["query"], as_of)]
        # [주의] 질의 글과 근거 글은 줄에 두지 않는다. 결과 파일은 저장소에 둘 수 있다
        kept = {key: value for key, value in item.items() if key not in ("query", "method")}
        rows.append(
            kept
            | {
                "cand": found["cand"],
                "retrieved": found["ranked"],
                "graph": found["graph"],
                "provision": found["provision"],
            }
        )
    return rows


def article_scope(via_mcp: bool) -> str:
    """조문 기준 값을 계산한 범위의 이름. 결과 meta에 남긴다.

    candidates: 리랭커가 줄 세운 후보 전체를 조·항으로 묶은 뒤 앞 k개를 본다 (직접 길).
    top_n: 서버가 돌려준 상위 n개만 묶는다 (MCP 길. 서버는 상위 n개만 준다).
    [주의] 범위가 다른 두 결과의 조문 기준 값은 견주지 않는다. 단위 기준 값은 두 길 모두 상위 k다.
    """
    return "top_n" if via_mcp else "candidates"
