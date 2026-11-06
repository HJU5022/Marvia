"""코퍼스 단위에서 법령 그래프의 간선을 만든다: PART_OF, DELEGATES_TO, REFERS_TO (설계 5.5, 계획 3b Task 2).

하지 않는 일: Neo4j 적재(graphdb.py), 품목 간선(items.py), LLM 호출. 순수 함수라 서버 없이 시험한다.
[왜] 조문 참조는 글에 "제241조제1항", "법 제30조", "「관세법」 제226조", "별표 9"처럼 정해진 꼴로 나온다.
     정규식으로 뽑고, 약칭(법·영·규칙)은 문서마다 정한 표(rules/graph.yaml)로 푼다.
[주의] 코퍼스는 문서당 한 판(시행일 하나)이라고 본다. 같은 조(별표)에 판이 둘이면 두 판 모두에 간선이 걸린다.
       단위 글에는 조 머리말과 윗 항·호 글이 붙어 있다(lawpage.py). 그래서 윗 글의 참조가 그 아래 잎 단위
       모두에 붙는다. 같은 조(별표) 안을 가리키는 참조는 버린다(자기 참조 0).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from functools import cache

from marvia.rag.annex import SYLLABLES
from marvia.rag.models import Unit
from marvia.tools.rules import load_rules

# 「법령명」 제N조 / 법·영·규칙 제N조 / 제N조. 뒤에 제N항, 제N호가 이어질 수 있다
ARTICLE_TAIL = r"제(?P<article>\d+)조(?:의(?P<sub>\d+))?(?:\s*제(?P<para>\d+)항)?(?:\s*제(?P<item>\d+)호)?"
# 별표 N(의 M) 제N호 X목
ANNEX_REF = re.compile(
    rf"(?:「(?P<quoted>[^」]+)」\s*)?별표\s*(?P<num>\d+(?:의\s*\d+)?)(?:\s*제(?P<ho>\d+)호)?(?:(?P<mok>[{SYLLABLES}])목)?"
)


@cache
def _article_ref() -> re.Pattern[str]:
    """약칭 낱말은 rules/graph.yaml에서 읽어 정규식을 한 번만 만든다."""
    abbr = "|".join(re.escape(a) for a in load_rules("graph")["refs"]["abbr"])
    return re.compile(rf"(?:「(?P<quoted>[^」]+)」\s*|(?<![가-힣])(?P<abbr>{abbr})\s+)?{ARTICLE_TAIL}")


@dataclass
class Edges:
    """만든 간선과 버린 참조의 수(까닭별)."""

    refers: list[tuple[str, str]] = field(default_factory=list)  # (가리키는 unit_id, 가리켜진 unit_id)
    part_of: list[tuple[str, str]] = field(default_factory=list)  # (unit_id, doc_id)
    delegates: list[tuple[str, str]] = field(default_factory=list)  # (위임하는 doc_id, 받는 doc_id)
    dropped: Counter[str] = field(default_factory=Counter)


def _root(key: str) -> str:
    """unit_id의 '#' 뒤 키에서 조(별표) 부분. 제30조.1항 → 제30조, 별표9.2호.가목 → 별표9."""
    return key.split(".", 1)[0]


def _article_key(m: re.Match[str]) -> str:
    key = f"제{m['article']}조" + (f"의{m['sub']}" if m["sub"] else "")
    return key + (f".{m['para']}항" if m["para"] else "") + (f".{m['item']}호" if m["item"] else "")


def _annex_key(m: re.Match[str]) -> str:
    key = "별표" + re.sub(r"\s+", "", m["num"])
    return key + (f".{m['ho']}호" if m["ho"] else "") + (f".{m['mok']}목" if m["mok"] else "")


def references(
    text: str, doc_id: str, laws: dict[str, str], alias: dict[str, str]
) -> tuple[list[tuple[str, str]], Counter[str]]:
    """글 하나의 참조를 (doc_id, 키) 목록으로 푼다. 풀지 못한 참조는 까닭별로 센다."""
    refs = load_rules("graph")["refs"]
    qualified = tuple(refs["qualified"])
    gap_ok = re.compile(r"\s*(?:" + "|".join(re.escape(c) for c in refs["connectors"]) + r")\s*")
    names = sorted(laws, key=len, reverse=True)  # [왜] "관세법 시행령"이 "관세법"보다 먼저 맞아야 한다
    found: list[tuple[str, str]] = []
    dropped: Counter[str] = Counter()
    for pattern, make_key in ((_article_ref(), _article_key), (ANNEX_REF, _annex_key)):
        # [왜] 「관세법」 제246조 및 제265조처럼 법령 이름 뒤에 나열한 조문은 앞 참조의 법령을 따른다.
        #      (target, 버린 까닭) 중 하나만 차 있다. 법령 이름 없이 시작한 나열은 None이라 그 문서 안이다
        prev: tuple[str | None, str | None] | None = None
        prev_end = 0
        for m in pattern.finditer(text):
            before = text[: m.start()].rstrip()
            abbr = m.groupdict().get("abbr")
            named: tuple[str | None, str | None]  # (target, 버린 까닭)
            explicit = True
            if m["quoted"]:
                target = laws.get(m["quoted"])
                named = (target, None if target else "outside_corpus")
            elif abbr:
                if before.endswith(refs["same_as"]):
                    named = (None, "same_as")
                else:
                    name = alias.get(abbr)
                    target = laws.get(name) if name else None
                    named = (target, None if target else ("outside_corpus" if name else "unknown_abbr"))
            elif prev and gap_ok.fullmatch(text[prev_end : m.start()]):
                named = prev
            elif plain := next((n for n in names if before.endswith(n)), None):
                named = (laws[plain], None)  # 「」 없이 쓴 코퍼스 법령 이름 (고시의 "관세법 제241조")
            elif before.endswith(qualified):
                named = (None, "qualified")
            else:
                # [왜] 법령 이름 없는 "제N조", "별표 N"은 그 문서 안이다
                named = (doc_id, None)
                explicit = False
            prev, prev_end = (named if explicit else None), m.end()
            if reason := named[1]:
                dropped[reason] += 1
            elif named[0]:
                found.append((named[0], make_key(m)))
    return found, dropped


def build_edges(units: list[Unit]) -> Edges:
    """코퍼스 단위 전체로 간선을 만든다. 가리켜진 키 아래의 모든 단위로 편다(조 참조 → 그 조의 항·호)."""
    cfg = load_rules("graph")
    laws = {u.law_name: u.doc_id for u in units}
    by_root: dict[tuple[str, str], list[str]] = {}
    for u in units:
        by_root.setdefault((u.doc_id, _root(u.unit_id.split("#", 1)[1])), []).append(u.unit_id)
    edges = Edges(
        part_of=[(u.unit_id, u.doc_id) for u in units],
        delegates=[(a, b) for a, b in cfg["delegates"]],
    )
    seen: set[tuple[str, str]] = set()
    for u in units:
        own = (u.doc_id, _root(u.unit_id.split("#", 1)[1]))
        refs, dropped = references(u.text, u.doc_id, laws, cfg["alias"].get(u.doc_id, {}))
        edges.dropped.update(dropped)
        for doc, key in refs:
            if (doc, _root(key)) == own:
                edges.dropped["self"] += 1  # [왜] 머리말 "제30조(…)"와 같은 조 안 참조는 간선이 아니다
                continue
            under = by_root.get((doc, _root(key)), [])
            targets = [t for t in under if (k := t.split("#", 1)[1]) == key or k.startswith(key + ".")]
            if not targets:
                edges.dropped["missing_target"] += 1
                continue
            for t in targets:
                if (u.unit_id, t) not in seen:
                    seen.add((u.unit_id, t))
                    edges.refers.append((u.unit_id, t))
    return edges
