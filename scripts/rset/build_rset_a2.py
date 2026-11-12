"""따로 둔 조문 지목 표본 rset_a2 만들기 (조문 지목 조회를 넣기 전에 뽑아 둔다). LLM·DB·키 없음. 정답은 코드가 정한다.

실행(레포 루트): PYTHONPATH=<build_rset.py가 있는 폴더> uv run python build_rset_a2.py <rset_v1.yaml> <rset_a2.yaml>
rset_v1의 층 a와 같은 스크립트 함수(article, quotas, TEMPLATES), 같은 배분, 같은 질의 틀을 쓴다. 시드만 1113.
"""

# ruff: noqa: E501
# [왜] 평가셋 머리말과 질의 틀이 긴 줄로 들어 있다. 줄을 나누면 만들어지는 파일의 글자가 달라진다
import random
import sys
from pathlib import Path

import yaml
from build_rset import TEMPLATES, article, quotas

from marvia.eval.dataset import CORPUS_UNITS, SET_V2_PATH, load_set
from marvia.rag.index import read_units

SEED = 1113
SUFFIX_DOCS = 3  # "제N조의M" 조문을 하나씩 먼저 뽑을 문서 수(배분이 큰 문서부터)

v1 = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))
used = {article(g) for i in v1["items"] if i["layer"] in ("a", "b") for g in i["gold"]}
used |= {article(i["source_unit"]) for i in v1["items"] if i["layer"] == "b"}
used |= {article(g) for i in load_set(SET_V2_PATH).items for g in i.gold}
units = [u for u in read_units(CORPUS_UNITS) if u.kind != "별표"]
by_article: dict[str, list] = {}
for u in units:
    by_article.setdefault(article(u.unit_id), []).append(u)
docs = sorted({u.doc_id for u in units})
sizes = {d: sum(u.doc_id == d for u in units) for d in docs}
quota = quotas(docs, sizes, 20)
suffix_docs = sorted(docs, key=lambda d: (-quota[d], -sizes[d], d))[:SUFFIX_DOCS]
rng = random.Random(SEED)
rows = []
for doc, n in quota.items():
    pool = sorted(
        a
        for a, us in by_article.items()
        if us[0].doc_id == doc
        and a not in used
        and not any("삭제" in u.text and len(u.text) < 60 for u in us)
    )
    picked = []
    if doc in suffix_docs:
        # [왜] "제N조의M" 꼴이 적어도 3개 들어가게, 배분이 큰 문서 셋은 첫 조문을 그 꼴에서 뽑는다
        picked.append(rng.choice([a for a in pool if "의" in a.split("#")[1]]))
    picked += rng.sample([a for a in pool if a not in picked], n - len(picked))
    for art in picked:
        rows.append(
            {
                "article": art,
                "law_name": by_article[art][0].law_name,
                "gold_units": [u.unit_id for u in by_article[art]],
            }
        )
assert len(rows) == 20 and len({r["article"] for r in rows}) == 20
items = []
for n, r in enumerate(rows, 1):
    art_name = r["article"].split("#")[1]
    items.append(
        {
            "id": f"N{n:02d}",
            "layer": "a2",
            "query": TEMPLATES[(n - 1) % 4].format(law=r["law_name"], art=art_name),
            "gold": [r["article"]],
            "gold_units": r["gold_units"],
            "method": f"조문 지목 틀 {(n - 1) % 4 + 1}, 시드 {SEED}",
        }
    )
# 표본 대조(전수): 정답 단위가 그 조문의 단위 전부이고, 뺀 조문이 없고, 질의가 틀과 법령 이름·조 번호로만 이뤄졌는가
every = {u.unit_id: u for u in units}
for it in items:
    art = it["gold"][0]
    assert art not in used, it["id"]
    assert it["gold_units"] == [u for u in every if article(u) == art], it["id"]
    law, name = every[it["gold_units"][0]].law_name, art.split("#")[1]
    assert it["query"] in [t.format(law=law, art=name) for t in TEMPLATES], it["id"]
    assert all(every[u].doc_id == art.split("@")[0] for u in it["gold_units"]), it["id"]
n_suffix = sum("의" in it["gold"][0].split("#")[1] for it in items)
assert n_suffix >= 3
HEADER = f"""# 검색 전용 평가셋 rset_a2: 따로 둔 조문 지목 표본 20문항 (조문 지목 조회를 넣기 전에 뽑아 동결)
# 쓰임: 조문 지목 조회(rules/rag.yaml search.named_article)의 효과를 rset_v1 층 a와 따로 확인한다. rset_v1 층 a는 결함을 찾는 데 쓴 문항이다.
# 만든 방법: 스크립트로 뽑았다(시드 {SEED}, corpus/units 7,412단위). rset_v1 층 a와 같은 함수·같은 배분(큰 문서 둘 3개, 나머지 2개)·같은 질의 틀 4가지.
#   틀: 1 "{{법령}} {{조}} 내용", 2 "{{법령}} {{조}}", 3 "{{법령}} {{조}}에는 무엇이 규정되어 있나요?", 4 "{{법령}} {{조}} 조문 알려줘"
#   뺀 것: rset_v1 층 a·b에 쓰인 조문, 평가셋 v2 정답 조문, 삭제 조문.
#   "제N조의M" 규칙: 배분이 큰 문서 셋({", ".join(suffix_docs)})은 첫 조문을 "제N조의M" 꼴에서 뽑고 나머지는 전체에서 뽑는다. 그래서 적어도 3개가 들어간다(이 판은 {n_suffix}개).
# 정답(gold)은 조 접두어 하나, gold_units는 그 조문의 단위 전부. 맞춤 규칙은 레포의 matches (같거나 "." 아래 단위).
# 확인: 스크립트가 20문항 전부를 코드로 대조했다(정답 단위 = 그 조문의 단위 전부, 뺀 조문 없음, 질의 = 틀 + 법령 이름 + 조 번호).
# 한계: 20문항이라 한 문항이 0.05를 움직인다. 질의 틀이 rset_v1 층 a와 같아 다른 말씨의 조문 지목 질의는 대표하지 않는다. 화물 번호 없음.
"""
out = Path(sys.argv[2])
out.write_text(
    HEADER
    + yaml.safe_dump(
        {"version": "rset_a2", "as_of": "2026-11-06", "seed": SEED, "items": items},
        allow_unicode=True,
        sort_keys=False,
        width=200,
    ),
    encoding="utf-8",
)
print("쓴 문항", len(items), "제N조의M", n_suffix, "문서", suffix_docs)
for it in items:
    print(it["id"], it["query"], len(it["gold_units"]))
