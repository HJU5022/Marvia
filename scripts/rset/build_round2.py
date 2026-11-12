"""리랭커 입력을 바꾸기 전에 따로 뽑은 표본: rset_a3(조문 지목 20)와 rset_b2(자연어 20) 만들기. 시드 1114. LLM·DB·키 없음.

실행(레포 루트, PYTHONPATH에 build_rset.py가 있는 폴더):
  uv run python build_round2.py sample <retrieval-set 폴더> <작업 폴더>     rset_a3.yaml을 쓰고 rset_b2의 표본을 뽑는다
  uv run python build_round2.py write <retrieval-set 폴더> <작업 폴더>      questions.json을 합쳐 rset_b2.yaml(초안)을 쓴다
rset_a2(build_rset_a2.py), rset_v1 층 b(build_rset.py)와 같은 함수·배분·규칙을 쓴다. 정답은 코드가 정한다.
"""

# ruff: noqa: E501
# [왜] 평가셋 머리말과 질의 틀이 긴 줄로 들어 있다. 줄을 나누면 만들어지는 파일의 글자가 달라진다
import json
import random
import re
import sys
from pathlib import Path

import yaml
from build_rset import MIN_TEXT, TEMPLATES, article, group, quotas

from marvia.eval.dataset import CORPUS_UNITS, SET_V2_PATH, load_set
from marvia.eval.metrics import matches
from marvia.rag.index import read_units

SEED, SUFFIX_DOCS = 1114, 3
mode, setdir, work = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
units = [u for u in read_units(CORPUS_UNITS) if u.kind != "별표"]
by_id = {u.unit_id: u for u in units}
by_article: dict[str, list] = {}
for u in units:
    by_article.setdefault(article(u.unit_id), []).append(u)
docs = sorted({u.doc_id for u in units})
sizes = {d: sum(u.doc_id == d for u in units) for d in docs}
quota = quotas(docs, sizes, 20)


def used_articles() -> set[str]:
    """이미 쓴 조문: rset_v1 층 a·b, rset_a2, set_v2 정답."""
    v1 = yaml.safe_load((setdir / "rset_v1.yaml").read_text(encoding="utf-8"))
    a2 = yaml.safe_load((setdir / "rset_a2.yaml").read_text(encoding="utf-8"))
    used = {article(g) for i in v1["items"] if i["layer"] in ("a", "b") for g in i["gold"]}
    used |= {article(i["source_unit"]) for i in v1["items"] if i["layer"] == "b"}
    used |= {article(g) for i in a2["items"] for g in i["gold"]}
    used |= {article(g) for i in load_set(SET_V2_PATH).items for g in i.gold}
    return used


def deleted(us: list) -> bool:
    return any("삭제" in u.text and len(u.text) < 60 for u in us)


if mode == "sample":
    used = used_articles()
    rng = random.Random(SEED)
    suffix_docs = sorted(docs, key=lambda d: (-quota[d], -sizes[d], d))[:SUFFIX_DOCS]
    picked_all = []
    for doc, n in quota.items():
        pool = sorted(
            a for a, us in by_article.items() if us[0].doc_id == doc and a not in used and not deleted(us)
        )
        picked = []
        if doc in suffix_docs:
            picked.append(rng.choice([a for a in pool if "의" in a.split("#")[1]]))
        picked += rng.sample([a for a in pool if a not in picked], n - len(picked))
        picked_all += picked
    items = []
    for n, art in enumerate(picked_all, 1):
        us = by_article[art]
        items.append(
            {
                "id": f"P{n:02d}",
                "layer": "a3",
                "query": TEMPLATES[(n - 1) % 4].format(law=us[0].law_name, art=art.split("#")[1]),
                "gold": [art],
                "gold_units": [u.unit_id for u in us],
                "method": f"조문 지목 틀 {(n - 1) % 4 + 1}, 시드 {SEED}",
            }
        )
    for it in items:  # 표본 대조(전수)
        art = it["gold"][0]
        assert art not in used and it["gold_units"] == [u for u in by_id if article(u) == art], it["id"]
        assert it["query"] in [
            t.format(law=by_id[it["gold_units"][0]].law_name, art=art.split("#")[1]) for t in TEMPLATES
        ], it["id"]
    n_suffix = sum("의" in it["gold"][0].split("#")[1] for it in items)
    assert len(items) == 20 and len({it["gold"][0] for it in items}) == 20 and n_suffix >= 3
    head = f"""# 검색 전용 평가셋 rset_a3: 조문 지목 20문항 (리랭커 입력을 바꾸기 전에 따로 뽑아 동결한 표본)
# 만든 방법: 스크립트로 뽑았다(시드 {SEED}, corpus/units 7,412단위). rset_a2와 같은 함수·배분(큰 문서 둘 3개, 나머지 2개)·질의 틀 4가지.
#   틀: 1 "{{법령}} {{조}} 내용", 2 "{{법령}} {{조}}", 3 "{{법령}} {{조}}에는 무엇이 규정되어 있나요?", 4 "{{법령}} {{조}} 조문 알려줘"
#   뺀 것: rset_v1 층 a·b와 rset_a2에 쓰인 조문, 평가셋 v2 정답 조문, 삭제 조문.
#   "제N조의M" 규칙: 배분이 큰 문서 셋({", ".join(suffix_docs)})은 첫 조문을 그 꼴에서 뽑는다(이 판은 {n_suffix}개).
# 정답(gold)은 조 접두어 하나, gold_units는 그 조문의 단위 전부. 맞춤 규칙은 레포의 matches.
# 확인: 스크립트가 20문항 전부를 코드로 대조했다(정답 단위 = 그 조문의 단위 전부, 뺀 조문 없음, 질의 = 틀 + 법령 이름 + 조 번호).
# 한계: 20문항(한 문항 0.05). 질의 틀이 rset_v1 층 a, rset_a2와 같다. 화물 번호 없음.
"""
    (setdir / "rset_a3.yaml").write_text(
        head
        + yaml.safe_dump(
            {"version": "rset_a3", "as_of": "2026-11-06", "seed": SEED, "items": items},
            allow_unicode=True,
            sort_keys=False,
            width=200,
        ),
        encoding="utf-8",
    )
    # rset_b2 표본: rset_v1 층 b와 같은 규칙. 이미 쓴 조문과 방금 뽑은 rset_a3 조문은 뺀다. 같은 난수기를 이어 쓴다
    used_b = used | set(picked_all)
    v2_gold = [g for i in load_set(SET_V2_PATH).items for g in i.gold]
    taken, b_units = set(), []
    for doc, n in quota.items():
        pool = sorted(
            (
                u
                for u in units
                if u.doc_id == doc
                and len(u.text) >= MIN_TEXT
                and article(u.unit_id) not in used_b
                and not deleted(by_article[article(u.unit_id)])
                and not any(matches(u.unit_id, [g]) for g in v2_gold)
            ),
            key=lambda u: u.unit_id,
        )
        got = []
        for u in rng.sample(pool, len(pool)):
            if article(u.unit_id) not in taken:
                taken.add(article(u.unit_id))
                got.append(u)
            if len(got) == n:
                break
        b_units += got
    assert len(b_units) == 20
    rows = []
    for n, u in enumerate(b_units, 1):
        gold = group(u.unit_id)
        rows.append(
            {
                "id": f"Q{n:02d}",
                "layer": "b2",
                "query": None,
                "gold": [gold],
                "gold_units": sorted(x for x in by_id if matches(x, [gold])),
                "source_unit": u.unit_id,
            }
        )
    work.mkdir(parents=True, exist_ok=True)
    (work / "b2_sample.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    (work / "b2_for_writer.json").write_text(
        json.dumps(
            [
                {
                    "key": r["id"],
                    "law_name": by_id[r["source_unit"]].law_name,
                    "heading": by_id[r["source_unit"]].heading,
                    "text": by_id[r["source_unit"]].text,
                }
                for r in rows
            ],
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print("rset_a3", len(items), "제N조의M", n_suffix, "| rset_b2 표본", len(rows))
    for it in items:
        print(it["id"], it["query"], len(it["gold_units"]))
    for r in rows:
        print(r["id"], r["source_unit"], "| gold", r["gold"], len(r["gold_units"]))
else:
    rows = json.loads((work / "b2_sample.json").read_text(encoding="utf-8"))
    questions = json.loads((work / "b2_questions.json").read_text(encoding="utf-8"))
    bad = []
    for r in rows:
        q = str(questions[r["id"]]).strip()
        if re.search(r"제\s*\d+\s*조|별표\s*\d|\d{6,}", q) or by_id[r["source_unit"]].law_name in q or not q:
            bad.append((r["id"], q))
        r["query"], r["method"] = q, f"본문을 보고 모델(sonnet)이 쓴 질문, 시드 {SEED}"
        assert r["gold_units"] and all(u in by_id for u in r["gold_units"])
    assert not bad, bad
    assert len(rows) == 20 and len({r["query"] for r in rows}) == 20
    head = f"""# 검색 전용 평가셋 rset_b2: 자연어 질문 20문항 (리랭커 입력을 바꾸기 전에 따로 뽑은 표본, 초안. 정답 독립 확인 전)
# 만든 방법: 스크립트로 뽑았다(시드 {SEED}). rset_v1 층 b와 같은 방법: 문서 9개에서 본문 {MIN_TEXT}자 이상인 단위를 고루 뽑고(큰 문서 둘 3개, 나머지 2개,
#   한 조문에서 하나), 본문만 보고 모델(sonnet)이 질문을 썼다. 검색 결과는 보여 주지 않았다. 조문 번호와 법령 이름은 질문에 없다(코드로 검사).
#   뺀 것: rset_v1 층 a·b, rset_a2, rset_a3에 쓰인 조문, 평가셋 v2 정답 조문, 삭제 조문.
# 정답(gold)은 답이 든 단위(source_unit)의 조·항(호·목 포함). 다른 조문을 가리키기만 하는 조문을 정답으로 두지 않는다.
# 한계: 질문을 정답 본문을 보고 썼다(본문 낱말이 질문에 들어가 검색에 유리하게 치우친다). 정답은 한 조·항뿐이다. 20문항(한 문항 0.05). 화물 번호 없음.
"""
    (setdir / "rset_b2.yaml").write_text(
        head
        + yaml.safe_dump(
            {"version": "rset_b2-draft", "as_of": "2026-11-06", "seed": SEED, "items": rows},
            allow_unicode=True,
            sort_keys=False,
            width=200,
        ),
        encoding="utf-8",
    )
    print("rset_b2 초안", len(rows))
