"""계약 C5(UNI-PASS 정제 결과). 근거: SDD 3.5.

책임: UNI-PASS 원본 응답에서 LLM에 넘겨도 되는 필드만 남긴 형태.
- 넘기는 것: 선명, 국적, 항차, 입항일, 통관 진행 상태·코드, 장치장명, 단계 이력, MRN(배 특정용).
- 넘기지 않는 것: 품명(prnm), 중량(wght), 세관명, 화주 정보. 이 모델에 아예 필드가 없다.
- B/L 번호는 LLM에 안 넘기고, 트레이스·로그에는 mask_bl()로 남긴다 (SDD 3.5, 7절).
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CustomsStage(BaseModel):
    """단계 이력 1건. UNI-PASS 단계 코드(prgsStCd)·이름·처리 일시(prcsDttm)."""

    code: str
    name: str
    at: datetime | None


class CustomsRecord(BaseModel):
    """UNI-PASS 화물통관진행정보 정제본. services/customs.py가 만들고 C(판정)는 이것만 소비한다."""

    ship_name: str | None = Field(default=None, description="shipNm")
    ship_nat: str | None = Field(default=None, description="shipNat, 국적 코드")
    voyage: str | None = Field(default=None, description="vydf, 항차")
    entry_date: datetime | None = Field(default=None, description="etprDt, 입항(예정)일")
    stage_code: str | None = Field(default=None, description="prgsStCd, 현재 통관 단계 코드")
    stage_name: str | None = Field(default=None, description="현재 단계명. 가장 최근 이력 줄의 처리구분(cargTrcnRelaBsopTpcd), 이력이 없으면 csclPrgsStts")
    shed_name: str | None = Field(default=None, description="shedNm, 장치장명")
    discharge_port: str | None = Field(default=None, description="dsprCd, 양륙항 코드(예: KRPUS). 부산이 아니면 unsupported (09-28 추가)")
    # 화물이 어디서 어디로 가나 (10-01 추가, 실제 응답에서 칸 이름 확인: ldprCd=CNTAO, ldprNm=Qingdao, lodCntyCd=CN)
    discharge_port_name: str | None = Field(default=None, description="dsprNm, 양륙항 이름(예: 부산항)")
    loading_port: str | None = Field(default=None, description="ldprCd, 적재항 코드(예: CNTAO)")
    loading_port_name: str | None = Field(default=None, description="ldprNm, 적재항 이름(예: Qingdao)")
    loading_country: str | None = Field(default=None, description="lodCntyCd, 적출국 코드(예: CN)")
    mrn: str | None = Field(
        default=None,
        description="cargMtNo 앞 11자리, 입항 적하목록 관리번호. 해수부 선박운항정보 mrNum과 같아서 배(호출부호)를 특정한다 (09-23 추가)",
    )
    stage_history: list[CustomsStage] = Field(default_factory=list)
    bl_masked: str = Field(description="앞4자+****+뒤4자. 로그·트레이스용")

    def route_fields(self) -> dict:
        """C1 CustomsInfo에 넣을 "어디서 어디로" 칸. 응답을 만드는 곳(routers/agent.py)이 그대로 펼쳐 넣는다 (10-01)."""
        return {"loading_port": self.loading_port, "loading_port_name": self.loading_port_name,
                "loading_country": self.loading_country, "discharge_port": self.discharge_port,
                "discharge_port_name": self.discharge_port_name}
    fetched_at: datetime


def mask_bl(bl_no: str) -> str:
    """B/L 번호의 가운데 절반을 *로 가린다 (SDD 3.5, 10-01 변경). 가린 자리 수만큼 *를 써서 길이를 유지한다.

    예: TESTBL01(8자) → TE****01, ABCD1234567890(14자) → ABCD*******890.
    전에는 "앞4자+****+뒤4자"라 8자 이하 번호는 전부 가려져(********) 조회 이력에서 알아볼 수 없었고,
    긴 번호는 오히려 8자가 드러났다. 이제 길이와 상관없이 항상 절반이 가려지고 앞뒤로 알아볼 만큼만 남는다.
    """
    n = len(bl_no)
    hidden = max(1, n // 2) if n else 0
    start = (n - hidden) // 2
    return bl_no[:start] + "*" * hidden + bl_no[start + hidden:]
