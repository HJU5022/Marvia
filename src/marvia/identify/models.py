"""식별 결과와 조회 결과의 모양을 정한다 (설계 4.3, 7.2).

하지 않는 일: 조회와 판정. 여기는 값을 담는 그릇만 둔다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from marvia.identify.parse import Kind


class CargoFacts(BaseModel):
    """조회 도구가 돌려준 화물 상태."""

    number: str  # 조회한 실제 번호. [주의] LLM에 넘기지 않는다
    stage: str  # 통관 진행 단계 이름 (예: 반입신고)
    stage_at: datetime | None = None  # 그 단계가 된 시각
    vessel_name: str | None = None
    port: str | None = None
    mrn: str | None = None  # 적하목록 관리번호 11자리. 배를 특정하는 데 쓴다
    # [왜] 근거 카드에 "어디서, 언제 가져온 값인지"를 항상 보여 주기 위해 출처와 조회 시각을 붙인다
    source: str = "unipass_replay"
    fetched_at: datetime


class ToolError(BaseModel):
    """도구가 실패하면 예외 대신 이 값을 돌려준다."""

    code: str  # 실패 종류 (예: not_found, timeout)
    message: str  # [주의] 실제 번호를 넣지 않는다. 트레이스·화면에 그대로 남을 수 있다
    retryable: bool  # 다시 시도하면 나아질 수 있나. 에이전트가 재시도할지 정하는 데 쓴다


class CargoIdentity(BaseModel):
    """식별 서브그래프의 결과 한 건. LLM은 token만 본다."""

    token: str  # LLM이 보는 가린 이름 (예: [BL1])
    kind: Kind  # cargo_no(화물관리번호), bl, container(컨테이너 번호)
    cargo_no: str | None = None
    bl_no: str | None = None
    # [왜] UNI-PASS는 B/L 조회에 연도가 필요하다. 지난해 B/L을 올해로 찾으면 "없음"이 나온다
    bl_year: int | None = None
    mrn: str | None = None
    vessel: str | None = None
    source: Literal["text", "photo", "message"] = "text"  # 어떤 단서에서 번호를 얻었나
    confidence: Literal["confirmed", "candidate", "unknown"]  # 확정 / 후보 / 확인 못 함
    candidates: list[str] = Field(default_factory=list)  # 확정 못 했을 때의 후보 (2차)
    facts: CargoFacts | None = None  # 조회에 성공하면 채운다
    error: ToolError | None = None  # 조회에 실패하면 채운다
