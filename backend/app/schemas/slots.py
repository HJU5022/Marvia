"""슬롯 스키마. 문장에서 뽑아낸 것을 담는다. LLM 출력 계약 1. (SDD 3절)

왜 계약인가:
  소형 모델이 이 모양으로만 답하도록 강제하고(GBNF), 어긋나면 재시도한다. 파인튜닝 데이터의 output도
  이 모양과 완전히 같아야 한다. 필드 하나를 늘리면 평가셋 30건과 학습 데이터가 같이 깨지므로
  SDD 3절을 먼저 고친 뒤에만 바꾼다 (CLAUDE.md "하지 말 것").

여기 없는 것:
  좌표. 문장에는 좌표가 없고 소형 모델이 만들 수도 없다. 지오코딩 결과는 AgentResponse.geocoded 로 나간다
  (SDD 2절). owner_user_id 만 예외로 여기 있는데, LLM이 아니라 서버가 핀 확인 단계에서 채운다 (SDD 7절).
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Transport = Literal["car", "transit", "walk"]
Preset = Literal["ship_maintenance", "si_deploy"]

# 사람이 쓴 지명·이름에 허용하는 문자. 한자·가나가 섞이면 소형 모델이 엉뚱한 곳을 지어낸 것이라 보고 막는다
# (SDD 3절 검증 규칙, request_logs.error_type = foreign_char).
_ALLOWED_TEXT = re.compile(r"^[가-힣ㄱ-ㅎㅏ-ㅣA-Za-z0-9\s.,·\-()\[\]/&'\"~:+#]*$")


def check_text(value: str | None, field: str) -> str | None:
    """지명·이름에 허용하지 않는 문자가 있으면 ValidationError를 낸다."""
    if value is not None and not _ALLOWED_TEXT.match(value):
        raise ValueError(f"{field}에 쓸 수 없는 문자가 있습니다: {value!r}")
    return value


class Participant(BaseModel):
    """참석자 한 명. 이름과 출발지는 개인정보라 저장할 때 암호화한다 (테이블정의서 7절)."""

    name: str
    origin: str | None = Field(default=None, description="지명 텍스트. 없으면 None")
    transport: Transport | None = Field(default=None, description="없으면 None. 추측하지 않는다")
    pickup: str | None = Field(default=None, description="이 사람을 태워 주는 참석자 이름")
    pickup_at: str | None = Field(default=None, description="태워지는 지점. 집결지(rendezvous)와 다르다")
    unfamiliar: bool = Field(default=False, description="그 일대 지리를 모르는 참석자")
    role: Literal["site", "vendor", "client", "colleague"]
    owner_user_id: str | None = Field(
        default=None,
        description="이 핀을 소유한 사용자. None이면 주선자 소유. LLM 출력에는 없고 서버가 채운다 (SDD 7절)",
    )

    @model_validator(mode="after")
    def _check(self) -> Participant:
        check_text(self.name, "참석자 이름")
        check_text(self.origin, "출발지")
        check_text(self.pickup_at, "픽업 지점")
        # 짝이 맞아야 하는 이유: 태워 주는 사람만 알고 태우는 지점을 모르면 4단계가 경유지를 못 넣는다 (SDD 5절)
        if bool(self.pickup) != bool(self.pickup_at):
            raise ValueError("pickup 과 pickup_at 은 둘 다 있거나 둘 다 없어야 합니다")
        return self


class Rendezvous(BaseModel):
    """전원이 모이는 집결지. 개인 픽업 지점은 Participant.pickup_at 에 둔다."""

    name: str
    transport_after: Transport | None = None

    @model_validator(mode="after")
    def _check(self) -> Rendezvous:
        check_text(self.name, "집결지 이름")
        return self


class Access(BaseModel):
    """출입조치·인솔 절차. lead_min 은 규칙 파일 기본값으로 채운다 (SDD 7절 access.md)."""

    required: bool
    applied: bool | None = Field(default=None, description="신청 여부. 모르면 None")
    lead_min: int | None = Field(default=None, ge=0, description="절차 소요(분)")


class Slots(BaseModel):
    """한 요청에서 확정된 상황. 재질문이면 이전 Slots를 프롬프트에 넣고 바뀐 것만 갱신한다 (SDD 5절)."""

    preset: Preset | None = Field(default=None, description="out_of_scope가 True일 때만 None")
    datetime: str | None = Field(default=None, description='"목요일 08:00" 같은 사람 말 그대로')
    purpose: str | None = None
    destination: str | None = None
    participants: list[Participant] = Field(default_factory=list)
    rendezvous: Rendezvous | None = None
    access: Access | None = None
    schedule_confirmed: bool | None = Field(default=None, description="입항·배포 시각 확정 여부. 모르면 None")
    constraints: list[str] = Field(
        default_factory=list,
        description='"arrival_delayed", "port_changed", "vendor_route_same_day", "mutual_deference", "luggage"',
    )
    missing: list[str] = Field(default_factory=list, description='"participants[0].origin" 처럼 경로로 적는다')
    out_of_scope: bool = Field(default=False, description="출발 후 실시간 상황이면 True")

    @model_validator(mode="after")
    def _check(self) -> Slots:
        check_text(self.purpose, "목적")
        check_text(self.destination, "목적지")

        if self.out_of_scope:
            # 범위 밖이면 참석자를 지어내지 않는다. 뽑을 상황 자체가 아니다 (SDD 5절 1-1)
            if self.preset is not None or self.participants:
                raise ValueError("out_of_scope 이면 preset은 None, participants는 빈 목록이어야 합니다")
            return self

        if self.preset is None:
            raise ValueError("out_of_scope 가 아니면 preset 이 있어야 합니다")
        if not self.participants:
            raise ValueError("참석자가 한 명 이상이어야 합니다")

        # 이동수단을 모르면 반드시 되물어야 한다. missing 에 없으면 그대로 계산에 들어가 버린다 (SDD 5절 1-2)
        for i, p in enumerate(self.participants):
            if p.transport is None and f"participants[{i}].transport" not in self.missing:
                raise ValueError(f"participants[{i}].transport 가 None 인데 missing 에 없습니다")
        return self
