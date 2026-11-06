"""대표 품목의 요건 그래프 데이터(corpus/graph/items.yaml)를 읽고 검사한다 (설계 5.5, 계획 3b Task 5).

하지 않는 일: LLM 뽑기(scripts/extract_items.py가 한 번 한다), Neo4j 적재(graphdb.py).
[왜] LLM이 뽑은 간선은 데이터 파일로 동결해 적재가 늘 같게 한다. 근거 구절이 그 단위 글에 그대로 있는지
     코드가 본다. 그래프 검색은 Unit 후보만 돌려주고 요건·서류·기관 이름은 작성자에게 넘기지 않는다(설계 5.6).
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from marvia.rag.models import Unit

ITEMS_PATH = Path(__file__).resolve().parents[3] / "corpus" / "graph" / "items.yaml"


class Grounding(BaseModel):
    """요건 하나의 근거: 코퍼스 단위와 그 글에 그대로 있는 짧은 구절."""

    model_config = ConfigDict(extra="forbid")
    unit_id: str = Field(description="unit_id copied exactly from the provisions block")
    quote: str = Field(
        description="A short exact phrase (under 40 characters) copied from that provision's text"
    )


class Requirement(BaseModel):
    """품목이 수입될 때 따르는 요건 하나 (Requirement 노드와 NEEDS·BY·GROUNDED_IN 간선)."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(description="Short Korean name of the requirement, e.g. 수입신고, 정밀검사")
    grounded_in: list[Grounding] = Field(min_length=1)
    needs: list[str] = Field(
        default_factory=list, description="Korean names of documents the requirement needs"
    )
    by: list[str] = Field(default_factory=list, description="Korean names of the agencies in charge")


class Item(BaseModel):
    """대표 품목 하나 (Item 노드와 REQUIRES 간선)."""

    model_config = ConfigDict(extra="forbid")
    name: str
    aliases: list[str] = Field(default_factory=list)
    requires: list[Requirement]


class ItemGraph(BaseModel):
    """items.yaml 전체. reviewed는 검토 상태 표시다(예: 에이전트 대조, 사람 검토 전)."""

    model_config = ConfigDict(extra="forbid")
    reviewed: str
    items: list[Item]


def load_items(path: Path = ITEMS_PATH) -> ItemGraph:
    """items.yaml을 읽는다."""
    return ItemGraph.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def check_items(graph: ItemGraph, units: dict[str, Unit]) -> list[str]:
    """근거 단위가 코퍼스에 있고 구절·서류 이름·기관 이름이 그 글에 그대로 있는지 본다. 문제마다 한 줄."""
    problems = []
    for item in graph.items:
        for req in item.requires:
            for g in req.grounded_in:
                unit = units.get(g.unit_id)
                if unit is None:
                    problems.append(f"{item.name}/{req.name}: 코퍼스에 없는 단위 {g.unit_id}")
                elif g.quote not in unit.text:
                    problems.append(f"{item.name}/{req.name}: 구절이 {g.unit_id} 글에 없다")
            # [왜] 서류·기관 이름도 LLM이 지어낼 수 있다. 그 요건의 근거 단위 글 중 하나에 그대로 있어야 한다
            texts = [u.text for g in req.grounded_in if (u := units.get(g.unit_id))]
            for kind, names in (("서류", req.needs), ("기관", req.by)):
                problems += [
                    f"{item.name}/{req.name}: {kind} 이름이 근거 글에 없다: {n}"
                    for n in names
                    if not any(n in t for t in texts)
                ]
    return problems


def item_names(query: str, items: list[Item]) -> list[str]:
    """질의에 이름이나 별칭이 들어 있는 품목 이름. 띄어쓰기는 보지 않는다."""
    # [왜] 질의 분석 프롬프트에 품목 칸을 새로 만들면 모든 지표가 흔들린다. 글자 맞추기로 충분하다 (사전
    #      부검 F9)
    flat = query.replace(" ", "")
    return [i.name for i in items if any(n.replace(" ", "") in flat for n in [i.name, *i.aliases])]


def known_cost(cost: float | None) -> float:
    """뽑기 누계 비용. 단가를 모르는 모델이면(None) 상한이 조용히 풀리지 않게 멈춘다."""
    if cost is None:
        sys.exit("[멈춤] 단가를 모르는 모델이다 (rules/pricing.yaml)")
    return cost
