"""판정 평가 문항(eval/verdict_set_v1.yaml)을 읽고 돌린다 (계획 8a). LLM도 바깥 조회도 없다.

문항 하나 = 가공 입력(화물 사실, 배 위치, 입항 일정, 지난 위치)과 기대값(신호 여섯, 등급·확신·일정,
믿을 ETA의 출처, 여유 일수, 확신을 낮춘 이유). 코드(tools/judge.py)가 낸 값이 기대값과 모두 같아야 통과다.
배 확정 문항(matches)은 tools/vessel_match.py의 결과를 본다.
하지 않는 일: 에이전트 평가(src/marvia/eval/run.py). 이 문항들은 모델이 도구를 고르는지를 보지 않는다.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

from marvia.eval.dataset import ROOT
from marvia.identify.models import CargoFacts
from marvia.tools.judge import Verdict, judge
from marvia.tools.verdict import Confidence, Grade, Schedule
from marvia.tools.vessel import PortSchedule, Position, SailingPlan, TrackPoint
from marvia.tools.vessel_match import Candidate, Match, match_vessel

SET_PATH = ROOT / "eval" / "verdict_set_v1.yaml"
State = Literal["triggered", "clear", "unknown"]


class Expect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    signals: dict[str, State]
    grade: Grade | None  # None = 도착 시각을 알 출처가 없어 등급을 내지 않음
    confidence: Confidence
    schedule: Schedule | None
    eta_source: str | None
    margin_days: int | None
    notes: list[str] = []
    dest_value: str | None = None  # 목적지 바뀜 신호의 값(항구 코드나 broken·empty). 적은 문항만 본다
    info: list[str] | None = None  # 참고 사실(판매 예정일 없음). 적은 문항만 본다


class V1(BaseModel):
    """v1 코드가 같은 입력에 낸 값. 옮긴 문항에만 있다."""

    model_config = ConfigDict(extra="forbid")
    id: str  # v1 평가셋의 문항 id
    signals: dict[str, State]
    table_verdict: Literal["fine", "watch", "act"]
    differs: str = ""  # v2 등급이 v1 표와 다르면 그 이유


class VerdictItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    layer: Literal["ported", "port", "conflict", "failure", "nodata", "stage", "edge"]
    why: str
    now: datetime
    sale_due: date | None = None
    first_eta: datetime | None = None
    forwarder_eta: date | None = None
    cargo: dict | None  # CargoFacts의 칸 일부. None이면 화물을 확정하지 못한 것
    position: dict | None
    schedule: dict | None
    history: list[dict] = []
    v1: V1 | None = None
    expect: Expect


class MatchExpect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["confirmed", "ask", "none"]
    mmsi: int | None
    reason: str


class MatchItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    why: str
    cargo: dict
    candidates: list[Candidate]
    plans: dict[str, list[SailingPlan] | None]
    mrn_call_sign: str | None = None
    expect: MatchExpect


class VerdictSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    items: list[VerdictItem]
    matches: list[MatchItem]


def load_verdict_set(path: Path = SET_PATH) -> VerdictSet:
    """문항 파일을 읽어 모양을 검사한다. 칸 이름이 틀리면 ValidationError를 낸다."""
    return VerdictSet.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _facts(cargo: dict | None, now: datetime) -> CargoFacts | None:
    # [왜] 번호와 조회 시각은 판정에 쓰이지 않는다. 문항마다 적지 않고 여기서 채운다
    return (
        None
        if cargo is None
        else CargoFacts.model_validate({"number": "TEST0001", "fetched_at": now, **cargo})
    )


def run_item(item: VerdictItem) -> Verdict:
    """문항의 입력으로 판정 함수를 돈다."""
    position = Position.model_validate({"fetched_at": item.now, **item.position}) if item.position else None
    plan = PortSchedule.model_validate({"fetched_at": item.now, **item.schedule}) if item.schedule else None
    return judge(
        _facts(item.cargo, item.now),
        position,
        plan,
        now=item.now,
        sale_due=item.sale_due,
        first_eta=item.first_eta,
        forwarder_eta=item.forwarder_eta,
        history=[TrackPoint.model_validate(point) for point in item.history],
    )


def mismatches(item: VerdictItem) -> list[str]:
    """기대값과 다른 칸의 목록. 비었으면 통과."""
    got, want = run_item(item), item.expect
    states = {s.id: s.state for s in got.signals}
    pairs = [
        ("signals", states, want.signals),
        ("grade", got.grade, want.grade),
        ("confidence", got.confidence, want.confidence),
        ("schedule", got.schedule, want.schedule),
        ("eta_source", got.eta_source, want.eta_source),
        ("margin_days", got.margin_days, want.margin_days),
        ("notes", got.notes, want.notes),
    ]
    if want.info is not None:
        pairs.append(("info", got.info, want.info))
    if want.dest_value is not None:
        pairs.append(
            ("dest_value", next(s.value for s in got.signals if s.id == "dest_changed"), want.dest_value)
        )
    return [f"{name}: {seen!r} != {expected!r}" for name, seen, expected in pairs if seen != expected]


def run_match(item: MatchItem) -> Match:
    """문항의 입력으로 배 확정 함수를 돈다."""
    facts = CargoFacts.model_validate(
        {"number": "TEST0001", "fetched_at": datetime.now().astimezone(), **item.cargo}
    )
    return match_vessel(facts, item.candidates, item.plans, item.mrn_call_sign)


def match_mismatches(item: MatchItem) -> list[str]:
    got, want = run_match(item), item.expect
    pairs = [
        ("status", got.status, want.status),
        ("mmsi", got.mmsi, want.mmsi),
        ("reason", got.reason, want.reason),
    ]
    return [f"{name}: {seen!r} != {expected!r}" for name, seen, expected in pairs if seen != expected]


def summarize(data: VerdictSet) -> dict:
    """층마다 문항 수와 통과 수. 저장소에 남기는 숫자다."""
    layers: dict[str, dict[str, int]] = {}
    for item in data.items:
        row = layers.setdefault(item.layer, {"n": 0, "passed": 0})
        row["n"] += 1
        row["passed"] += not mismatches(item)
    return {
        "items": {"n": len(data.items), "passed": sum(row["passed"] for row in layers.values())},
        "layers": layers,
        "matches": {"n": len(data.matches), "passed": sum(not match_mismatches(m) for m in data.matches)},
    }
