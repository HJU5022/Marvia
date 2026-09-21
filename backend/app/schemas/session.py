"""공유 링크 응답 모양. GET /api/session/{id} 가 돌려주는 것. (SDD 2절)

왜 여기 있나 (BACKEND_GUIDE "출력은 app/schemas/의 모델로 검증한다"):
  응답 필드는 이 파일에서만 정의한다. 라우터는 store.py에서 받은 dict를 이 모델에 넣어 돌려주고,
  FastAPI가 모양이 맞는지 검증한 뒤 /docs 자동 문서에도 띄운다 (채점 필수 3 출력 계약, 8-2 API 설계).

이 파일은 "세션 읽기" 응답만 있다. 계산 결과의 자세한 모양(Candidate, ParticipantResult 등)은
SDD 4절대로 schemas/result.py 에 정의될 예정이라 여기서는 dict로 둔다. result.py가 생기면 바꾼다.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SessionBrief(BaseModel):
    """내 계획 목록의 한 줄 (SDD 2절 GET /api/sessions).

    참석자 이름·좌표가 없다. 목록에 필요하지 않고, 복호화 비용과 노출 위험만 늘기 때문이다
    (테이블정의서 7절). 이름이 필요하면 그 계획을 열어서 본다.
    """

    id: str
    preset: str
    status: str = Field(description="draft / pins_confirmed / computed / failed")
    purpose: str | None = None
    destination: str | None = Field(default=None, description="sessions.destination_name")
    meet_at: datetime | None = Field(default=None, description="약속 시각. 없으면 임시 세션")
    participant_count: int
    created_at: datetime
    expires_at: datetime
    locked: bool = Field(description="약속 다음날부터 True. 재질문 불가")


class SessionRead(BaseModel):
    """세션 한 건 + 가장 최근 계산 결과. 공유 링크 화면이 그대로 그린다.

    participants / rendezvous / result 는 DB에선 암호문이지만 여기서는 평문이다.
    화면에 보여주려면 풀어야 하므로. HTTPS 구간이라 중간에서는 못 본다.
    "링크를 알고 로그인한 사람은 참석자 이름·출발지를 볼 수 있다"는 안내는 프론트 화면 몫 (테이블정의서 7절).
    """

    id: str
    preset: str = Field(description="ship_maintenance / si_deploy")
    status: str = Field(description="draft / pins_confirmed / computed / failed")
    meet_at: datetime | None = Field(default=None, description="약속 시각. 없으면 임시 세션")
    purpose: str | None = None
    destination_name: str | None = None
    destination_lng: float | None = None
    destination_lat: float | None = None
    participants: list[dict[str, Any]] = Field(description="참석자 목록(평문). 구조는 테이블정의서 1절 participants_enc")
    rendezvous: dict[str, Any] | None = Field(default=None, description="집결지 {name, lng, lat, transport_after}")
    access: dict[str, Any] | None = None
    schedule_confirmed: bool | None = None
    constraints: list[str] = []
    created_at: datetime
    updated_at: datetime
    expires_at: datetime = Field(description="이 시각이 지나면 링크가 죽는다")
    locked: bool = Field(description="약속 다음날부터 True. 재질문 불가, 열람·삭제는 가능")
    result: dict[str, Any] | None = Field(default=None, description="가장 최근 계산 결과. 아직 계산 전이면 None")
