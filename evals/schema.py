"""계약 C7(평가 레코드). 근거: SDD 3.7, PRD 8절.

책임: evals/dataset.jsonl 한 줄의 모양. 30건 = 정상 8(fine 4·act 4) · 경계 판정형 9 · 경계 보류형 5 · 실패 8.
- request는 C2 그대로, fixtures는 도구별 가공 응답(실제 원본 아님, ShipFinder 약관).
- expected_*는 사람이 모델 실행 전에 정한다. labeler·label_reason 필수 (D6).
- actual_arrival은 입항 뒤에 채우는 사후 값. 판정 정확도와 섞지 않는다 (PRD 8절 정답 기준 ②).
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from backend.app.schemas.agent import AgentRequest, Status, Verdict, VesselMatch

Category = Literal["normal", "edge_verdict", "edge_insufficient", "failure"]

# 실패 유도 8건의 종류 (PRD 8절). 주입 3건은 통로가 서로 다르다: 사용자 입력 · AIS dest · MCP 도구 설명.
FailureKind = Literal[
    "bl_not_found", "timeout", "no_permission", "out_of_scope_port",
    "schema_violation_persistent", "inject_user_input", "inject_ais_dest", "inject_tool_description",
]


class EvalRecord(BaseModel):
    """dataset.jsonl 한 줄. id는 N01/B01/F01처럼 구분 접두어를 쓴다."""

    id: str
    category: Category
    failure_kind: FailureKind | None = Field(default=None, description="category=failure일 때만")
    request: AgentRequest
    fixtures: dict = Field(description="도구별 가공 응답 {shipfinder, mof, unipass, searoute}")
    expected_verdict: Verdict | None
    expected_status: Status
    expected_vessel_match: VesselMatch
    expected_mmsi: int | None
    expected_missing_inputs: list[str] = []
    labeler: str = Field(description="정답을 정한 사람. 경계는 하정운")
    label_reason: str = Field(min_length=1, description="사유 한 줄")
    labeled_at: datetime | None = None
    actual_arrival: datetime | None = Field(default=None, description="사후, 예측 적중용")
