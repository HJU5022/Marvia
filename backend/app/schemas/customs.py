"""계약 C5(UNI-PASS 정제 결과). 근거: SDD 3.5.

책임: UNI-PASS 원본 응답에서 LLM에 넘겨도 되는 필드만 남긴 형태.
- 넘기는 것: 선명, 국적, 항차, 입항일, 통관 진행 상태·코드, 장치장명, 단계 이력, MRN(배 특정용).
- 포워더명(forwarder_name)·선사명(carrier_name)은 화물 정보로 채팅 에이전트 LLM에도 간다 (10-06 결정).
  컨테이너 번호(container_no)는 B/L처럼 화물을 특정하는 번호라 LLM에 넘기지 않고 화면·엑셀에만 쓴다 (10-06 결정).
- 품명(goods_name, prnm)은 처음엔 버렸지만 10-06 오후부터 남긴다. 새 화면이 선명·국적·품명으로 화물을 구분하고,
  "고추 화물 어디야?"처럼 품명으로 묻는 말을 채팅 에이전트가 알아들어야 해서다 (정운 결정). 판정 LLM에는 안 넘긴다.
- 넘기지 않는 것: 중량(wght), 세관명, 화주 정보. 이 모델에 아예 필드가 없다.
- B/L 번호는 LLM에 안 넘기고, 트레이스·로그에는 mask_bl()로 남긴다 (SDD 3.5, 7절).
- 예외: display_rows(UNI-PASS 처리 이력 원문)는 화면에만 보여 준다. model_dump에서 빠져(exclude) LLM 입력에
  들어가지 않고, 응답(C1 customs_detail)으로 옮긴 뒤에도 DB 저장·후속 질문 LLM 입력에서 뺀다 (docs/specs/customs-detail.md, 10-02).
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CustomsStage(BaseModel):
    """단계 이력 1건. UNI-PASS 단계 코드(prgsStCd)·이름·처리 일시(prcsDttm)."""

    code: str
    name: str
    at: datetime | None


class CustomsDetailRow(BaseModel):
    """UNI-PASS 처리 이력 1줄(cargCsclPrgsInfoDtlQryVo) 원문. 화면 전용 (docs/specs/customs-detail.md, 10-02).

    값은 UNI-PASS가 준 글자 그대로 둔다(빈 칸은 None). 뜻이 단계마다 달라(dclrNo는 반출입 신고번호·수입신고번호·MRN 등)
    코드가 해석하지 않는다. 중량·관세법인명이 들어 있어 LLM과 DB에는 넣지 않는다 (SDD 3.5).
    """

    kind: str | None = Field(default=None, description="cargTrcnRelaBsopTpcd, 처리 구분 (예: 반입신고)")
    processed_at: str | None = Field(default=None, description="prcsDttm, 처리 일시 YYYYMMDDhhmmss (한국 시각)")
    declaration_no: str | None = Field(default=None, description="dclrNo, 신고번호")
    moved_at: str | None = Field(default=None, description="rlbrDttm, 반출입 일시")
    basis: str | None = Field(default=None, description="rlbrBssNo, 반출입 근거번호 (관세법인명·하선반입기한 글이 들어오기도 한다)")
    content: str | None = Field(default=None, description="rlbrCn, 반출입 내용")
    notice: str | None = Field(default=None, description="bfhnGdncCn, 사전 안내 내용")
    shed_name: str | None = Field(default=None, description="shedNm, 장치장 이름")
    shed_code: str | None = Field(default=None, description="shedSgn, 장치장 부호")
    package_count: str | None = Field(default=None, description="pckGcnt, 포장 개수")
    package_unit: str | None = Field(default=None, description="pckUt, 포장 단위")
    weight: str | None = Field(default=None, description="wght, 중량")
    weight_unit: str | None = Field(default=None, description="wghtUt, 중량 단위")


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
    # 10-06 추가. 연계가이드 v4.1 API001 응답 항목. 값이 없으면(빈 태그) None. 모두 추가만 한 선택 필드라 기존 호출부는 안 바뀐다
    forwarder_name: str | None = Field(default=None, description="frwrEntsConm, 포워더명(예: 가공 포워더). 비어 오는 화물이 많다. LLM에 넘겨도 된다")
    carrier_name: str | None = Field(default=None, description="shcoFlco, 선사·항공사 이름. LLM에 넘겨도 된다")
    container_no: str | None = Field(
        default=None,
        description="cntrNo, 컨테이너 번호(11자, 예: ABCD1234567). 가이드상 API001에서는 1건(size 11)이지만 "
                    "컨테이너 여러 개면 서로 다른 번호를 ', '로 이어 한 문자열로 둔다. 화물을 특정하는 번호라 LLM에 넘기지 않는다",
    )
    goods_name: str | None = Field(
        default=None,
        description="prnm, 품명. 적하목록에 적힌 영어 그대로(예: TEST GOODS). 채팅 에이전트 LLM에는 가고 판정 LLM에는 안 간다 (10-06 오후)",
    )
    stage_history: list[CustomsStage] = Field(default_factory=list)
    # 화면 전용 처리 이력 원문. exclude=True라 model_dump에 안 나와 판정 LLM 입력(llm.judge)에 섞이지 않는다
    display_rows: list[CustomsDetailRow] = Field(default_factory=list, exclude=True)
    bl_masked: str = Field(description="앞4자+****+뒤4자. 로그·트레이스용")

    def route_fields(self) -> dict:
        """C1 CustomsInfo에 넣을 "어디서 어디로" 칸. 응답을 만드는 곳(routers/agent.py)이 그대로 펼쳐 넣는다 (10-01)."""
        return {"loading_port": self.loading_port, "loading_port_name": self.loading_port_name,
                "loading_country": self.loading_country, "discharge_port": self.discharge_port,
                "discharge_port_name": self.discharge_port_name}

    def party_fields(self) -> dict:
        """C1 CustomsInfo에 넣을 포워더·선사·컨테이너·품명 칸 (10-06). route_fields와 같은 방식으로 응답을 만드는 곳이 펼쳐 넣는다.
        화면·엑셀·다른 클라이언트가 읽는 값이다. 이 넷을 LLM에 넘길지는 쓰는 곳이 정한다 (container_no는 넘기지 않는다)."""
        return {"forwarder_name": self.forwarder_name, "carrier_name": self.carrier_name,
                "container_no": self.container_no, "goods_name": self.goods_name}
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
