"""정답 독립 확인에서 나온 고칠 목록 9건을 rset_v1 초안에 반영한다. LLM·DB·키 없음.

실행(레포 루트): uv run python apply_fixes.py <초안 yaml> <고친 yaml>
"""

# ruff: noqa: E501
# [왜] 평가셋 머리말과 질의 틀이 긴 줄로 들어 있다. 줄을 나누면 만들어지는 파일의 글자가 달라진다
import sys
from pathlib import Path

import yaml

from marvia.eval.dataset import CORPUS_UNITS
from marvia.eval.metrics import matches
from marvia.rag.index import read_units

src, dst = Path(sys.argv[1]), Path(sys.argv[2])
text = src.read_text(encoding="utf-8")
head = "".join(line for line in text.splitlines(keepends=True) if line.startswith("#"))
data = yaml.safe_load(text)
rows = {r["id"]: r for r in data["items"]}
units = {u.unit_id for u in read_units(CORPUS_UNITS)}


def reword(key: str, old: str, new: str) -> None:
    assert old in rows[key]["query"], (key, rows[key]["query"])
    rows[key]["query"] = rows[key]["query"].replace(old, new)


def regold(key: str, old: str, new: str) -> None:
    assert rows[key]["gold"] == [old], (key, rows[key]["gold"])
    rows[key]["gold"] = [new]
    rows[key]["gold_units"] = sorted(u for u in units if matches(u, [new]))
    assert rows[key]["source_unit"] in rows[key]["gold_units"], key


def also(key: str, *ids: str) -> None:
    for i in ids:
        assert any(matches(u, [i]) for u in units), (key, i)
    rows[key]["also_ok"] = list(ids)


regold("B02", "A36744@20231213#제2조", "A36744@20231213#제2조.1호")
reword("B02", "감시 대상 화물", "관리대상화물")
reword("B03", "감시 대상으로 지정된 화물", "관리대상화물")
also("B03", "A36744@20231213#제6조.4항", "A36744@20231213#제7조.1항")
regold("B06", "A36893@20251217#제122조", "A36893@20251217#제122조.6호")
also("B14", "L002421@20260227#제77조.1항")
rows["B15"]["query"] = (
    "수출할 물건을 포장하는 데 쓸 용품을 들여왔다가 물건과 함께 다시 내보낼 거면 관세가 면제되나요?"
)
reword("C03", "위해 이력으로 3등급이 된 수입자", "행정처분을 받은 지 얼마 안 된 수입자")
also("C10", "L012247@20261008#제21조.1항")
reword("C11", "서류검사를 생략할 수 있나요", "서류검사 대상인가요")
also("C19", "A36852@20260224#제34조.1항.1호")
for key in ("B14", "B19"):
    rows[key]["importer_question"] = (
        False  # 수입자의 질문이 아님(독립 확인 의견). 층 b 값을 넣은 값과 뺀 값으로 함께 본다
    )
for key in ("B02", "B03", "B06", "B14", "B15", "C03", "C10", "C11", "C19"):
    rows[key]["method"] += ", 검증 확인으로 고침"
assert len(rows) == 60 and len({r["query"] for r in rows.values()}) == 60
assert len(rows["B02"]["gold_units"]) == 5 and len(rows["B06"]["gold_units"]) == 1
head = head.replace("(초안, 정답 독립 확인 전)", "(정답 독립 확인 반영판)")
# also_ok를 단 문항이 생겼으므로 한계 줄에 그 사실을 덧붙인다
LIMIT = (
    "#   - 정답은 뽑힌 단위 하나(또는 한 조·항)뿐이다. 같은 내용을 담은 다른 조문이 검색돼도 오답으로 센다.\n"
)
assert LIMIT in head
head = head.replace(
    LIMIT,
    LIMIT
    + "#     다만 정답 독립 확인에서 also_ok를 단 네 문항(B03, B14, C10, C19)은 그 단위를 찾아도 맞음으로 센다.\n",
)
head += (
    "# 정답 독립 확인(문항을 만들지 않은 쪽이 60문항을 코퍼스 본문과 대조): 맞음 51, 고침 9, 버림 0.\n"
    "#   고침: 정답 좁힘 B02(제2조 → 제2조.1호), B06(제122조 → 제122조.6호). 질문 고침 B02, B03, B15, C03, C11.\n"
    "#   also_ok(이것을 찾아도 맞음) B03, B14, C10, C19. importer_question: false = 수입자의 질문이 아님(B14, B19).\n"
)
data["version"] = "rset_v1"
dst.write_text(head + yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")
print("고친 판", dst)
