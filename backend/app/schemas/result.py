"""결과 스키마. 계산과 판정이 끝난 답. LLM 출력 계약 2이자 API 응답. (SDD 4절, 2절)

대형 모델이 만드는 것은 candidates 의 rank·reason·rejected_reason·switched_from 뿐이다.
숫자(소요시간·출발 시각·여유)와 access_ok 는 코드가 넣는다 (docs/PRD.md 3절 "가운데는 결정적").
대형 모델 응답은 {"rankings":[{"candidate_idx":0,"rank":1,"reason":"...","rejected_reason":null}]} 로 받아
Candidate 에 합친다.

좌표가 두 군데로 나뉘는 이유:
  Candidate 의 좌표는 판정 결과라 result 안에 있고, 참석자·목적지·픽업 좌표는 지오코딩 결과라
  AgentResponse.geocoded 로 나간다. Slots 에 좌표를 넣지 않는 것은 슬롯이 파인튜닝 출력 계약이기 때문이다.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.app.schemas.slots import Slots, Transport, check_text

CandidateKind = Literal["gate", "lobby", "landmark", "pier", "hq"]
Stage = Literal["need_confirm", "need_info", "done", "out_of_scope", "failed"]

MAX_CANDIDATES = 3
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def check_hhmm(value: str, field: str) -> str:
    """시각은 "HH:MM" 로만 주고받는다. 날짜는 세션의 meet_at 이 가진다."""
    if not _HHMM.match(value):
        raise ValueError(f"{field} 는 HH:MM 이어야 합니다: {value!r}")
    return value


class Candidate(BaseModel):
    """집결 후보 한 곳. failed 폴백이면 rank 없이 위치만 담아 지도에 찍는다 (SDD 2절)."""

    name: str
    kind: CandidateKind = Field(description="절차 시작점(gate·lobby·hq) / 랜드마크 / 부두 안")
    address: str
    lng: float = Field(ge=124.0, le=132.0, description="경도. 국내 범위를 벗어나면 지오코딩이 틀린 것")
    lat: float = Field(ge=33.0, le=39.0)
    rank: int | None = Field(default=None, ge=1, le=MAX_CANDIDATES, description="failed 폴백이면 None")
    access_ok: bool = Field(description="지금 출입조치 상태로 이 지점이 가능한가. 코드가 넣는다")
    switched_from: str | None = Field(default=None, description="전환 판정이면 원래 집결지")
    reason: str = Field(description="한 줄. 규칙 파일 항목을 인용한다")
    rejected_reason: str | None = None

    @model_validator(mode="after")
    def _check(self) -> Candidate:
        check_text(self.name, "후보 이름")
        return self


class ParticipantResult(BaseModel):
    """참석자 한 명이 이 후보로 갈 때의 계산 결과. 숫자는 전부 코드가 넣는다 (SDD 5절 4·5·7단계)."""

    name: str
    candidate_rank: int = Field(ge=1, le=MAX_CANDIDATES)
    transport: Transport
    duration_min: int = Field(ge=0, description="여유를 포함한 소요")
    raw_duration_min: int = Field(ge=0, description="경로 API 값 그대로")
    buffer_min: int = Field(ge=0)
    departure_time: str = Field(description='"18:15"')
    arrive_by: str = Field(description="절차 소요를 뺀 도착 기한")
    transfer_count: int | None = Field(default=None, ge=0)
    first_train: str | None = None
    last_train: str | None = None
    polyline: list[tuple[float, float]] = Field(default_factory=list, description="[[lng, lat], ...]")
    via_rendezvous: bool = False
    via_pickup: bool = Field(default=False, description="운전자 경로가 이 사람을 태우러 경유하는가")

    @field_validator("departure_time", "arrive_by")
    @classmethod
    def _time(cls, v: str) -> str:
        return check_hhmm(v, "시각")

    @field_validator("first_train", "last_train")
    @classmethod
    def _time_optional(cls, v: str | None) -> str | None:
        return None if v is None else check_hhmm(v, "첫차·막차")

    @model_validator(mode="after")
    def _check(self) -> ParticipantResult:
        # 여유를 뺀 값이 경로 값보다 작아지면 역산이 틀린 것이다 (SDD 5절 7단계)
        if self.duration_min < self.raw_duration_min:
            raise ValueError("duration_min 은 raw_duration_min 보다 작을 수 없습니다")
        return self


class Result(BaseModel):
    """집결지 판정 + 참석자별 결과. 이 값이 results 표에 암호화돼 저장된다 (테이블정의서 2절)."""

    candidates: list[Candidate] = Field(max_length=MAX_CANDIDATES)
    provisional: bool = Field(description="입항·배포 시각이 미확정이면 True (SDD 7절 schedule.md)")
    per_participant: list[ParticipantResult] = Field(default_factory=list)
    rendezvous_departure: str | None = Field(default=None, description="집결지에서 출발할 시각")
    confidence: float = Field(ge=0.0, le=1.0)
    model_small: str
    model_large: str | None = Field(default=None, description="소형으로 끝났으면 None (SDD 5절 라우팅)")
    prompt_version: str
    routed_to: Literal["small", "large"]

    @field_validator("rendezvous_departure")
    @classmethod
    def _time_optional(cls, v: str | None) -> str | None:
        return None if v is None else check_hhmm(v, "집결지 출발 시각")

    @model_validator(mode="after")
    def _check(self) -> Result:
        ranks = [c.rank for c in self.candidates if c.rank is not None]
        if len(ranks) != len(set(ranks)):
            raise ValueError("후보 순위가 겹칩니다")
        known = {c.rank for c in self.candidates}
        for row in self.per_participant:
            if row.candidate_rank not in known:
                raise ValueError(f"{row.name} 의 candidate_rank {row.candidate_rank} 에 해당하는 후보가 없습니다")
        return self


class GeocodedPin(BaseModel):
    """지도에 찍을 좌표 하나. 참석자 핀 확인(need_confirm)과 결과 화면(done)이 이걸 쓴다 (SDD 2절).

    confidence 가 0.8 보다 낮으면 2단계가 need_confirm 으로 멈추고 사용자에게 핀을 고치게 한다 (SDD 5절 2단계).
    """

    name: str
    lng: float = Field(ge=124.0, le=132.0)
    lat: float = Field(ge=33.0, le=39.0)
    confidence: float = Field(ge=0.0, le=1.0)
    kind: Literal["participant", "rendezvous", "destination", "pickup"]


class AgentResponse(BaseModel):
    """POST /api/agent 의 응답. stage 하나로 화면이 갈린다 (frontend/FRONTEND_GUIDE.md 표).

    need_confirm  참석자 핀을 찍고 사용자 확인 대기 (지오코딩 확신도가 낮음)
    need_info     필수 슬롯 누락. questions 로 되묻는다
    done          result 가 채워진다
    out_of_scope  범위 밖. message 만
    failed        재시도 후에도 실패. 후보 핀만 있으면 result.candidates 에 rank 없이 담는다
    """

    session_id: str
    stage: Stage
    slots: Slots | None = Field(
        default=None,
        description="추출·확정된 슬롯. 추출 전에 실패하면(캡처를 못 읽음, 스키마 위반) None",
    )
    result: Result | None = Field(default=None, description="stage == done 일 때")
    questions: list[str] = Field(default_factory=list)
    message: str = Field(description="화면에 보여줄 한 줄")
    trace_id: str = Field(description="Langfuse 트레이스 id. 화면·로그·평가가 같은 값을 쓴다")
    geocoded: list[GeocodedPin] | None = Field(
        default=None, description="need_confirm, done 일 때 지도에 찍을 좌표"
    )

    @model_validator(mode="after")
    def _check(self) -> AgentResponse:
        if self.stage == "done" and self.result is None:
            raise ValueError("stage 가 done 이면 result 가 있어야 합니다")
        # 슬롯이 없는 응답은 "뽑기 전에 끊긴" 경우뿐이다. 계산까지 간 응답에는 반드시 있다
        if self.slots is None and self.stage not in ("failed", "need_info"):
            raise ValueError("slots 없이 올 수 있는 stage 는 failed, need_info 뿐입니다")
        if self.stage == "need_info" and not self.questions:
            raise ValueError("stage 가 need_info 이면 questions 가 있어야 합니다")
        return self


class ParticipantPatchResponse(BaseModel):
    """PATCH /api/session/{id}/participants 의 응답. 갱신된 슬롯과, 재계산이 끝났으면 새 결과 (SDD 2절)."""

    slots: Slots
    result: Result | None = None
