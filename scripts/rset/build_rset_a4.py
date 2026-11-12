"""항을 지목한 조문 질의 표본 rset_a4 만들기 (시드 1115). LLM·키 없음. unit_id 순서를 읽으려고 로컬 DB만 쓴다.

실행(레포 루트, PYTHONPATH에 build_rset.py가 있는 폴더): uv run python build_rset_a4.py <retrieval-set 폴더> <rset_a4.yaml>
"""

# ruff: noqa: E501
# [왜] 평가셋 머리말과 질의 틀이 긴 줄로 들어 있다. 줄을 나누면 만들어지는 파일의 글자가 달라진다
import random
import re
import sys
from pathlib import Path

import psycopg
import yaml
from build_rset import article, quotas

from marvia.config import Settings
from marvia.eval.dataset import CORPUS_UNITS, SET_V2_PATH, load_set
from marvia.rag.index import read_units

SEED = 1115
STRATA = {"L": 6, "M": 4, "S": 10}  # L 긴 조문·8번째 뒤, M 긴 조문·앞 8 안, S 단위 8개 이하 조문
MAX_UNITS = 8  # 조회가 앞에 두는 단위 수 상한(rules/rag.yaml search.named_article.max_units)과 같은 값
TEMPLATES = [
    "{law} {art} {para} 내용",
    "{law} {art} {para}",
    "{law} {art} {para}에는 무엇이 규정되어 있나요?",
    "{law} {art} {para} 조문 알려줘",
]
BRACKET = {3, 8, 13, 18}  # 법령 이름을 낫표로 싸는 문항 순번
setdir, out = Path(sys.argv[1]), Path(sys.argv[2])

units = [u for u in read_units(CORPUS_UNITS) if u.kind != "별표"]
by_article: dict[str, list] = {}
for u in units:
    by_article.setdefault(article(u.unit_id), []).append(u)
used = {article(g) for i in load_set(SET_V2_PATH).items for g in i.gold}
for name in ("rset_v1", "rset_a2", "rset_a3", "rset_b2"):
    for i in yaml.safe_load((setdir / f"{name}.yaml").read_text(encoding="utf-8"))["items"]:
        if i["layer"] == "c":
            continue
        used |= {article(g) for g in i["gold"]}
        if i.get("source_unit"):
            used.add(article(i["source_unit"]))
# unit_id 순서는 조회 코드(PROVISION_SQL의 ORDER BY unit_id)와 같게 DB에서 읽는다
with psycopg.connect(Settings().database_url) as conn:
    order = [
        r[0]
        for r in conn.execute("SELECT unit_id FROM corpus_units WHERE doc_id <> 'LTEST' ORDER BY unit_id")
    ]
db_order: dict[str, list[str]] = {}
for u in order:
    db_order.setdefault(article(u), []).append(u)

cands = {"L": [], "M": [], "S": []}
for art, us in sorted(by_article.items()):
    if art in used or any("삭제" in u.text and len(u.text) < 60 for u in us):
        continue
    ordered = db_order[art]
    assert sorted(ordered) == sorted(u.unit_id for u in us), art
    paras = sorted(
        {
            u.unit_id.split("#")[1].split(".")[1]
            for u in us
            if len(u.unit_id.split("#")[1].split(".")) > 1
            and re.fullmatch(r"\d+항", u.unit_id.split("#")[1].split(".")[1])
        }
    )
    for p in paras:
        gold = f"{art}.{p}"
        gold_units = [x for x in ordered if x == gold or x.startswith(gold + ".")]
        first = ordered.index(gold_units[0]) + 1
        stratum = "S" if len(ordered) <= MAX_UNITS else ("L" if first > MAX_UNITS else "M")
        cands[stratum].append(
            {
                "article": art,
                "para": p,
                "gold": gold,
                "gold_units": gold_units,
                "article_units": len(ordered),
                "position": first,
                "doc": us[0].doc_id,
                "law": us[0].law_name,
            }
        )

docs = sorted({u.doc_id for u in units})
sizes = {d: sum(u.doc_id == d for u in units) for d in docs}
left = quotas(docs, sizes, 20)
rng = random.Random(SEED)
picked, taken = [], set()
for stratum, n in STRATA.items():
    pool = sorted(cands[stratum], key=lambda c: c["gold"])
    got = 0
    for c in rng.sample(pool, len(pool)):
        if got == n:
            break
        if left[c["doc"]] > 0 and c["article"] not in taken:
            left[c["doc"]] -= 1
            taken.add(c["article"])
            picked.append(c | {"stratum": stratum})
            got += 1
    assert got == n, (stratum, got)
items = []
for n, c in enumerate(picked, 1):
    law = f"「{c['law']}」" if n in BRACKET else c["law"]
    para = "제" + c["para"]
    items.append(
        {
            "id": f"G{n:02d}",
            "layer": "a4",
            "query": TEMPLATES[(n - 1) % 4].format(law=law, art=c["article"].split("#")[1], para=para),
            "gold": [c["gold"]],
            "gold_units": c["gold_units"],
            "stratum": c["stratum"],
            "article_units": c["article_units"],
            "position": c["position"],
            "bracket": n in BRACKET,
            "method": f"항 지목 틀 {(n - 1) % 4 + 1}, 시드 {SEED}",
        }
    )
# 표본 대조(전수)
every = [u.unit_id for u in units]
for it in items:
    g = it["gold"][0]
    art = article(g)
    assert (
        art not in used
        and it["gold_units"] == [x for x in db_order[art] if x == g or x.startswith(g + ".")]
        and it["gold_units"]
    ), it["id"]
    assert sorted(it["gold_units"]) == sorted(x for x in every if x == g or x.startswith(g + ".")), it["id"]
    assert (
        it["article_units"] == len(db_order[art])
        and it["position"] == db_order[art].index(it["gold_units"][0]) + 1
    ), it["id"]
    assert {
        "L": it["article_units"] > 8 and it["position"] > 8,
        "M": it["article_units"] > 8 and it["position"] <= 8,
        "S": it["article_units"] <= 8,
    }[it["stratum"]], it["id"]
    law = by_article[art][0].law_name
    name, para = art.split("#")[1], "제" + g.rsplit(".", 1)[1]
    assert it["query"] in [
        t.format(law=x, art=name, para=para) for t in TEMPLATES for x in (law, f"「{law}」")
    ], it["id"]
    assert it["bracket"] == ("「" in it["query"])
assert (
    len(items) == 20
    and len({article(i["gold"][0]) for i in items}) == 20
    and sum(i["bracket"] for i in items) == 4
)
count = {s: sum(i["stratum"] == s for i in items) for s in STRATA}
HEADER = f"""# 검색 전용 평가셋 rset_a4: 항을 지목한 조문 질의 20문항 (조회가 "제M항"을 읽게 고치기 전에 뽑아 동결)
# 쓰임: "법령 이름 제N조 제M항 ..." 꼴 질의에서 지목한 항의 단위를 찾는지 본다.
# 만든 방법: build_rset_a4.py (시드 {SEED}, corpus/units 7,412단위, unit_id 순서는 로컬 DB의 ORDER BY unit_id).
#   층(stratum): L {count["L"]}문항 = 단위가 8개를 넘는 조문에서 지목한 항의 첫 단위가 unit_id 순으로 8번째 뒤(position > 8),
#                M {count["M"]}문항 = 단위가 8개를 넘는 조문에서 지목한 항이 앞 8개 안, S {count["S"]}문항 = 단위가 8개 이하인 조문.
#   그래서 단위 8개 넘는 조문이 {count["L"] + count["M"]}문항(8 이상), 그 가운데 8번째 뒤가 {count["L"]}문항(절반 이상)이다.
#   문서 배분은 rset_a2와 같은 상한(관세법 시행령·관세법 3개, 나머지 2개)으로 L, M, S 순서로 채웠다. 한 조문에서 하나만.
#   틀: 1 "{{법령}} {{조}} 제M항 내용", 2 "{{법령}} {{조}} 제M항", 3 "{{법령}} {{조}} 제M항에는 무엇이 규정되어 있나요?", 4 "{{법령}} {{조}} 제M항 조문 알려줘"
#   낫표 꼴(bracket: true) 4문항: 3, 8, 13, 18번째 문항은 법령 이름을 「」로 쌌다.
#   뺀 것: rset_v1 층 a·b, rset_a2, rset_a3, rset_b2에 쓰인 조문, 평가셋 v2 정답 조문, 삭제 조문, 별표.
# 정답(gold)은 그 항의 접두어 하나, gold_units는 그 항의 단위 전부. 맞춤 규칙은 레포의 matches (같거나 "." 아래 단위).
#   article_units = 그 조문의 단위 수, position = 지목한 항의 첫 단위가 그 조문 안에서 몇 번째인지(unit_id 순).
# 확인: 스크립트가 20문항 전부를 코드로 대조했다(정답 단위 = 그 항의 단위 전부, 층 조건, 자리, 뺀 조문 없음, 질의 = 틀 + 법령 이름 + 조 + 항).
# 한계: 20문항(한 문항 0.05). 질의 틀이 넷뿐이다("제N조제M항"처럼 붙여 쓴 꼴, 호까지 지목한 꼴은 없다). 화물 번호 없음.
"""
out.write_text(
    HEADER
    + yaml.safe_dump(
        {"version": "rset_a4", "as_of": "2026-11-06", "seed": SEED, "items": items},
        allow_unicode=True,
        sort_keys=False,
        width=200,
    ),
    encoding="utf-8",
)
print("쓴 문항", len(items), count, "남은 배분", {d: v for d, v in left.items() if v})
for it in items:
    print(
        it["id"],
        it["stratum"],
        it["query"],
        "| 조문 단위",
        it["article_units"],
        "자리",
        it["position"],
        "정답 단위",
        len(it["gold_units"]),
    )
