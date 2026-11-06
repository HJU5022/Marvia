"""평가셋을 읽고 모양을 검사한다 (설계 11절, done 3.1).

하지 않는 일: 채점(metrics.py)과 실행(run.py). 정답 근거가 법령 글과 맞는지는 이 코드가 아니라
독립 검증이 법령 원문과 대조해 eval/gold_check_v1.md에 남긴다.
여기서는 모양, 근거가 코퍼스에 있는지, 동결 해시만 본다.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

# src/marvia/eval/dataset.py에서 세 단계 올라가면 저장소 루트다
ROOT = Path(__file__).resolve().parents[3]
SET_PATH = ROOT / "eval" / "set_v1.yaml"
CORPUS_UNITS = ROOT / "corpus" / "units"

# 실행 결과의 행동 이름. 코드가 답 모양으로 정한다 (run.behaviour)
# answer: 근거·계산·화물 사실이 있는 답 / guide: 번호를 물을 포워더 문장이 있는 답(설계 4.1의 ③)
# not_found: 근거에 물은 대상이 없다고 밝힌 답
# choice: 선택지 질문 / partial: 부분 답 / decline: 도메인 밖 거절 / unsupported: 근거·계산·화물 없이 낸 답
Behaviour = Literal["answer", "guide", "choice", "partial", "not_found", "decline", "unsupported"]
Verdict = Literal["서류검사 요건 충족", "정밀검사 대상", "사실 부족", "대상 아님"]


class Deadline(BaseModel):
    """코드가 계산해야 하는 기한 하나 (calc_deadlines의 name·due)."""

    model_config = ConfigDict(extra="forbid")
    name: str
    due: date


class Calc(BaseModel):
    """코드 계산의 정답. 답을 냈다면 계산 칸이 이 값과 같아야 한다."""

    model_config = ConfigDict(extra="forbid")
    deadlines: list[Deadline] = []
    reimport: Verdict | None = None


class Trajectory(BaseModel):
    """에이전트 길의 도구 호출 조건 (done 3.4). 코드가 기록된 호출 순서로 확인한다."""

    model_config = ConfigDict(extra="forbid")
    must: list[str] = []  # 꼭 불러야 할 도구. "a|b"는 둘 중 하나면 된다
    must_not: list[str] = []  # 부르면 안 되는 도구
    order: list[tuple[str, str]] = []  # (앞, 뒤): 둘 다 불렀으면 앞이 먼저 나와야 한다
    max_calls: int | None = None  # 이 문항의 도구 호출 수 상한. 없으면 rules/eval.yaml 기본값


class Domain(BaseModel):
    """범용 도구 비교(done 3.8)에서 자유 글 답으로 볼 것. 코드가 글에서 찾는다."""

    model_config = ConfigDict(extra="forbid")
    stage: str | None = None  # 답에 나와야 할 통관 단계 이름
    due: date | None = None  # 답에 나와야 할 기한 날짜
    article: str | None = None  # 답에 나와야 할 조문 (예: "관세법 제241조")


class Item(BaseModel):
    """평가 문항 하나."""

    model_config = ConfigDict(extra="forbid")
    id: str
    group: Literal["related", "unrelated", "blocked"]  # 설계 11절의 세 갈래
    kind: str  # 갈래 안의 종류 (요건, 보류·검사, 도메인 밖 등)
    question: str  # 사용자 질문 그대로. 번호는 DEMO·MOCK·TEST·NOPE 가공값만
    behaviour: list[Behaviour] = Field(min_length=1)  # 맞는 행동 (하나라도 같으면 맞음)
    # 정답 근거 unit_id. 조·항까지만 적으면 그 아래 호·목 단위도 정답으로 본다 (metrics.matches)
    gold: list[str] = []
    also_ok: list[str] = []  # 정답은 아니지만 인용해도 틀리지 않은 단위
    reference: str = ""  # 정답 글 한두 문장 (ragas context precision·recall의 reference)
    calc: Calc | None = None
    trajectory: Trajectory = Trajectory()
    fault: Literal["search"] | None = None  # 막힘 행동 문항: 이 실행에서 일부러 끊을 바깥 기능
    human: bool = False  # 사람 채점 10건 (설계 11절)
    domain: Domain | None = None  # 범용 도구 비교 문항 (done 3.8)


class EvalSet(BaseModel):
    """평가셋 한 판. as_of는 실행의 오늘 날짜다(기한 계산과 법령 시행일 기준)."""

    model_config = ConfigDict(extra="forbid")
    version: str
    as_of: date
    items: list[Item]


def load_set(path: Path = SET_PATH) -> EvalSet:
    """평가셋 YAML을 읽어 모양을 검사한다. 칸 이름이 틀리면 ValidationError를 낸다."""
    return EvalSet.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def file_sha256(path: Path = SET_PATH) -> str:
    """파일의 sha256. 평가셋 동결과 실행 결과의 평가셋 표시에 쓴다."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def corpus_unit_ids(folder: Path = CORPUS_UNITS) -> set[str]:
    """코퍼스 단위 파일(corpus/units/*.jsonl)의 unit_id 모음. DB 없이 정답 근거가 있는지 본다."""
    ids: set[str] = set()
    for path in sorted(folder.glob("*.jsonl")):
        ids |= {json.loads(line)["unit_id"] for line in path.read_text(encoding="utf-8").splitlines() if line}
    return ids
