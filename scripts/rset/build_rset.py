"""검색 전용 평가셋 rset_v1 만들기. 1단계 sample: 고정 시드로 뽑는다. 2단계 write: 질문을 합쳐 YAML로 쓴다.

실행(레포 루트): uv run python build_rset.py sample <작업 폴더>
                 uv run python build_rset.py write <작업 폴더> <rset_v1.yaml 경로>
LLM·DB·키 없음. 정답은 코드가 정한다(사람이나 모델이 고르지 않는다).
"""

# ruff: noqa: E501
# [왜] 평가셋 머리말과 질의 틀이 긴 줄로 들어 있다. 줄을 나누면 만들어지는 파일의 글자가 달라진다
import json
import random
import re
import sys
from pathlib import Path

import yaml

from marvia.eval.dataset import CORPUS_UNITS, SET_V2_PATH, load_set
from marvia.eval.metrics import matches
from marvia.rag.index import read_units

SEED = 1112
TEMPLATES = [
    "{law} {art} 내용",
    "{law} {art}",
    "{law} {art}에는 무엇이 규정되어 있나요?",
    "{law} {art} 조문 알려줘",
]
MIN_TEXT = 100  # 층 b·c에서 뽑는 단위 본문의 최소 글자 수(너무 짧은 단위는 질문을 쓸 내용이 없다)
ANNEX_QUOTA = {
    "L012500@20260930#별표9": 14,
    "L012500@20260930#별표10": 4,
    "A36852@20260224#별표1": 2,
}  # 54:16:5 비례


def article(unit_id: str) -> str:
    """문서@시행일#첫 마디(제N조, 제N조의M, 별표N)."""
    head, _, path = unit_id.partition("#")
    return f"{head}#{path.split('.')[0]}"


def group(unit_id: str) -> str:
    """M6의 묶는 규칙: 첫 마디 + 둘째 마디가 '항'으로 끝나면 거기까지."""
    head, _, path = unit_id.partition("#")
    parts = path.split(".")
    return f"{head}#{'.'.join(parts[:2] if len(parts) > 1 and parts[1].endswith('항') else parts[:1])}"


def quotas(docs: list[str], sizes: dict[str, int], total: int) -> dict[str, int]:
    """문서마다 고르게 나누고, 남는 몫은 단위가 많은 문서부터 하나씩."""
    base, extra = divmod(total, len(docs))
    big = sorted(docs, key=lambda d: (-sizes[d], d))[:extra]
    return {d: base + (d in big) for d in docs}


def sample(work: Path) -> None:
    units = read_units(CORPUS_UNITS)
    v2_gold = [g for i in load_set(SET_V2_PATH).items for g in i.gold]
    v2_groups, v2_articles = {group(g) for g in v2_gold}, {article(g) for g in v2_gold}
    rng = random.Random(SEED)
    plain = [u for u in units if u.kind != "별표"]
    annex = [u for u in units if u.kind == "별표"]
    assert len(units) == 7412 and len(annex) == 75
    docs = sorted({u.doc_id for u in plain})
    sizes = {d: sum(u.doc_id == d for u in plain) for d in docs}
    by_article: dict[str, list] = {}
    for u in plain:
        by_article.setdefault(article(u.unit_id), []).append(u)

    # 층 a: 조문을 뽑는다. 삭제 조문과 평가셋 v2 정답이 든 조문은 뺀다
    a_items, a_articles = [], set()
    for doc, n in quotas(docs, sizes, 20).items():
        pool = sorted(
            a
            for a, us in by_article.items()
            if us[0].doc_id == doc
            and a not in v2_articles
            and not any("삭제" in u.text and len(u.text) < 60 for u in us)
        )
        for art in rng.sample(pool, n):
            a_articles.add(art)
            a_items.append(
                {
                    "article": art,
                    "law_name": by_article[art][0].law_name,
                    "gold_units": [u.unit_id for u in by_article[art]],
                }
            )
    # 층 b: 단위를 뽑는다. v2 정답과 같은 조·항, 층 a에서 뽑힌 조문, 이미 뽑힌 조·항은 뺀다
    b_items, used = [], set()
    for doc, n in quotas(docs, sizes, 20).items():
        pool = sorted(
            (
                u
                for u in plain
                if u.doc_id == doc
                and len(u.text) >= MIN_TEXT
                and group(u.unit_id) not in v2_groups
                and article(u.unit_id) not in v2_articles
                and article(u.unit_id) not in a_articles
                and not any(matches(u.unit_id, [g]) for g in v2_gold)
            ),
            key=lambda u: u.unit_id,
        )
        picked = []
        for u in rng.sample(pool, len(pool)):
            if article(u.unit_id) not in used:
                used.add(article(u.unit_id))
                picked.append(u)
            if len(picked) == n:
                break
        b_items += picked
    # 층 c: 별표 단위 75개에서 별표별 비례(14:4:2)로 뽑는다
    c_items = []
    for prefix, n in ANNEX_QUOTA.items():
        pool = sorted(
            (u for u in annex if article(u.unit_id) == prefix and len(u.text) >= MIN_TEXT),
            key=lambda u: u.unit_id,
        )
        c_items += rng.sample(pool, n)
    assert len(a_items) == len(b_items) == len(c_items) == 20
    by_id = {u.unit_id: u for u in units}
    rows = []
    for n, it in enumerate(a_items, 1):
        art_name = it["article"].split("#")[1]
        rows.append(
            {
                "id": f"A{n:02d}",
                "layer": "a",
                "query": TEMPLATES[(n - 1) % 4].format(law=it["law_name"], art=art_name),
                "gold": [it["article"]],
                "gold_units": it["gold_units"],
                "template": (n - 1) % 4 + 1,
            }
        )
    for layer, items in (("b", b_items), ("c", c_items)):
        for n, u in enumerate(items, 1):
            gold = group(u.unit_id) if layer == "b" else u.unit_id
            rows.append(
                {
                    "id": f"{layer.upper()}{n:02d}",
                    "layer": layer,
                    "query": None,
                    "gold": [gold],
                    "gold_units": sorted(x for x in by_id if matches(x, [gold])),
                    "source_unit": u.unit_id,
                }
            )
    work.mkdir(parents=True, exist_ok=True)
    (work / "sample.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    writer = [
        {
            "key": r["id"],
            "law_name": by_id[r["source_unit"]].law_name,
            "heading": by_id[r["source_unit"]].heading,
            "text": by_id[r["source_unit"]].text,
        }
        for r in rows
        if r["layer"] != "a"
    ]
    (work / "for_writer.json").write_text(json.dumps(writer, ensure_ascii=False, indent=1), encoding="utf-8")
    print({k: sum(r["layer"] == k for r in rows) for k in "abc"}, "writer", len(writer))


HEADER = """# 검색 전용 평가셋 rset_v1 (초안, 정답 독립 확인 전)
# 쓰임: LLM 없이 검색 단계(벡터, 키워드, RRF, 리랭커, 그래프, 임베딩 모델)를 견준다. 답 채점용이 아니다.
# 만든 방법: 스크립트로 뽑았다(시드 1112, corpus/units 7,412단위, 기준 커밋 da2200c). 정답은 코드가 정했다.
#   층 a (20): 조문 지목 질의. 문서 9개에서 조문을 고루 뽑아(큰 문서 둘은 3개, 나머지 2개) 질의 틀 4가지를 돌려 가며 채웠다.
#              틀: 1 "{법령} {조} 내용", 2 "{법령} {조}", 3 "{법령} {조}에는 무엇이 규정되어 있나요?", 4 "{법령} {조} 조문 알려줘"
#              정답(gold)은 그 조문 전체(조 접두어). gold_units는 그 조문의 단위 전부다.
#   층 b (20): 자연어 질문. 문서 9개에서 본문 100자 이상인 단위를 같은 배분으로 뽑고, 본문만 보고 모델(sonnet)이 질문을 썼다.
#              검색 결과는 보여 주지 않았다. 정답은 그 단위와 같은 조·항(호·목 포함).
#   층 c (20): 별표 질의. 별표 단위 75개에서 별표별 비례(별표 9: 14, 별표 10: 4, 보세화물 고시 별표 1: 2)로 뽑아 같은 방법으로 질문을 썼다.
#              정답은 그 단위 하나(아래 단위가 있으면 포함).
# 층 b·c의 정답은 "답이 든 단위"다(source_unit = 질문을 쓴 본문의 단위). 다른 조문이나 별표를 가리키기만 하는 조문을 정답으로 두지 않는다.
# 정답 맞춤 규칙: 레포의 matches (같거나 "." 아래 단위). 조문 기준 지표는 조·항으로 묶는다(scripts/retrieval_check.py).
# 뺀 것: 평가셋 v2의 정답 12문항과 같은 조문(층 a·b), 삭제 조문, 층 a에서 뽑힌 조문(층 b).
# 한계:
#   - 층 b·c의 질문은 정답 본문을 보고 썼다. 본문 낱말이 질문에 그대로 들어가 키워드·벡터 검색에 유리하게 치우친다.
#   - 정답은 뽑힌 단위 하나(또는 한 조·항)뿐이다. 같은 내용을 담은 다른 조문이 검색돼도 오답으로 센다.
#   - 층 a는 조문 번호를 질의에 그대로 넣는 꼴이라 키워드 검색에 유리하다(그것을 보려는 층이다).
#   - 층마다 20문항이다. 한 문항이 층 값 0.05, 전체 값 0.0167을 움직인다.
#   - 화물 번호는 없다(가공 번호도 없음).
"""


def write(work: Path, out: Path) -> None:
    rows = json.loads((work / "sample.json").read_text(encoding="utf-8"))
    questions = json.loads((work / "questions.json").read_text(encoding="utf-8"))
    units = {u.unit_id: u for u in read_units(CORPUS_UNITS)}
    bad = []
    for r in rows:
        if r["layer"] == "a":
            r["method"] = f"조문 지목 틀 {r.pop('template')}, 시드 {SEED}"
            continue
        q = str(questions[r["id"]]).strip()
        law = units[r["source_unit"]].law_name
        # [왜] 조문 번호, 별표 번호, 법령 이름, 긴 숫자(번호류)가 질문에 들어가면 안 된다
        if re.search(r"제\s*\d+\s*조|별표\s*\d|\d{6,}", q) or law in q or not q:
            bad.append((r["id"], q))
        r["query"] = q
        r["method"] = f"본문을 보고 모델(sonnet)이 쓴 질문, 시드 {SEED}"
    assert not bad, bad
    assert len(rows) == 60 and len({r["query"] for r in rows}) == 60
    for r in rows:
        assert all(u in units for u in r["gold_units"]) and r["gold_units"], r["id"]
        assert all(any(matches(u, [g]) for g in r["gold"]) for u in r["gold_units"]), r["id"]
    body = yaml.safe_dump(
        {"version": "rset_v1-draft", "as_of": "2026-11-06", "seed": SEED, "items": rows},
        allow_unicode=True,
        sort_keys=False,
        width=200,
    )
    out.write_text(HEADER + body, encoding="utf-8")
    print("쓴 문항", len(rows), out)


if __name__ == "__main__":
    if sys.argv[1] == "sample":
        sample(Path(sys.argv[2]))
    else:
        write(Path(sys.argv[2]), Path(sys.argv[3]))
