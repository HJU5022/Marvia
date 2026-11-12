"""정답 독립 확인에서 나온 고칠 목록 11건을 rset_b2 초안에 반영한다. LLM·DB·키 없음.

실행(레포 루트): uv run python apply_fixes_b2.py <초안 yaml> <고친 yaml>
"""

# ruff: noqa: E501
# [왜] 평가셋 머리말과 질의 틀이 긴 줄로 들어 있다. 줄을 나누면 만들어지는 파일의 글자가 달라진다
import sys
from pathlib import Path

import yaml

from marvia.eval.dataset import CORPUS_UNITS
from marvia.rag.index import read_units

src, dst = Path(sys.argv[1]), Path(sys.argv[2])
text = src.read_text(encoding="utf-8")
head = "".join(line for line in text.splitlines(keepends=True) if line.startswith("#"))
data = yaml.safe_load(text)
rows = {r["id"]: r for r in data["items"]}
units = {u.unit_id for u in read_units(CORPUS_UNITS)}


def hit(unit_id: str, gold: str) -> bool:
    return unit_id == gold or unit_id.startswith(gold + ".")


def regold(key: str, old: str, new: str) -> None:
    assert rows[key]["gold"] == [old], (key, rows[key]["gold"])
    rows[key]["gold"] = [new]
    rows[key]["gold_units"] = sorted(u for u in units if hit(u, new))
    assert rows[key]["source_unit"] in rows[key]["gold_units"], key


def also(key: str, *ids: str) -> None:
    for i in ids:
        assert any(hit(u, i) for u in units), (key, i)
    rows[key]["also_ok"] = list(ids)


regold("Q02", "A36744@20231213#제5조.2항", "A36744@20231213#제5조.2항.1호")
regold("Q06", "A36893@20251217#제14조.1항", "A36893@20251217#제14조.1항.1호.나목")
regold("Q09", "L001556@20261002#제277조.6항", "L001556@20261002#제277조.6항.3호")
regold("Q10", "L001556@20261002#제327조의3.3항", "L001556@20261002#제327조의3.3항.2호")
regold("Q11", "L001556@20261002#제81조.1항", "L001556@20261002#제81조.1항.4호")
regold("Q14", "L002421@20260227#제245조의5.1항", "L002421@20260227#제245조의5.1항.1호.나목")
regold("Q15", "L006392@20260731#제79조의4.1항", "L006392@20260731#제79조의4.1항.52호")
regold("Q17", "L012247@20261008#제40조.2항", "L012247@20261008#제40조.2항.3호")
regold("Q19", "L012500@20260930#제16조.1항", "L012500@20260930#제16조.1항.5호")
also("Q05", "L002421@20260227#제245조.1항")
assert "어떤 정보교류를 하나요" in rows["Q12"]["query"]
rows["Q12"]["query"] = "수출입 물품 안전 관련 관계 기관 협의회에서는 어떤 일을 협의하나요?"
assert rows["Q12"]["gold"] == ["L002421@20260227#제251조의3.1항"]
also("Q12", "L001556@20261002#제246조의3.7항")
for key in ("Q07", "Q12", "Q15"):
    rows[key]["importer_question"] = False  # 수입자의 질문이 아님(독립 확인 의견)
for key in ("Q02", "Q05", "Q06", "Q09", "Q10", "Q11", "Q12", "Q14", "Q15", "Q17", "Q19"):
    rows[key]["method"] += ", 검증 확인으로 고침"
assert len(rows) == 20 and len({r["query"] for r in rows.values()}) == 20
for r in rows.values():
    assert len(r["gold"]) == 1 and r["gold_units"] and all(hit(u, r["gold"][0]) for u in r["gold_units"])
head = head.replace(
    "(리랭커 입력을 바꾸기 전에 따로 뽑은 표본, 초안. 정답 독립 확인 전)",
    "(리랭커 입력을 바꾸기 전에 따로 뽑은 표본, 정답 독립 확인 반영판)",
)
assert "반영판" in head
head += (
    "# 정답 독립 확인(문항을 만들지 않은 쪽이 20문항을 코퍼스 본문과 대조): 맞음 9, 고침 11, 버림 0.\n"
    "#   정답 좁힘(같은 조·항의 다른 호가 다른 내용이라 답이 든 호·목으로): Q02, Q06, Q09, Q10, Q11, Q14, Q15, Q17, Q19.\n"
    "#   also_ok(이것을 찾아도 맞음): Q05, Q12. 질문 고침: Q12. importer_question: false = 수입자의 질문이 아님(Q07, Q12, Q15).\n"
)
data["version"] = "rset_b2"
dst.write_text(head + yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")
print("고친 판", dst, {k: len(r["gold_units"]) for k, r in rows.items()})
