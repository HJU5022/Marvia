"""UNI-PASS 화물통관진행정보 조회와 정제 (작업 A8).

B/L 번호로 통관 진행 상태와 선박 정보를 가져온다. 이 조회는 LLM이 하지 않고 코드가 직접 한다.
B/L 번호를 LLM에 넘기면 숫자를 잘못 옮기거나 프롬프트 주입에 쓰일 수 있어서다 (SDD 6.3, CLAUDE.md).

응답에서 계약 C5(CustomsRecord)에 있는 필드만 남긴다. 중량·세관명·화주 정보는
모델에 자리가 없어 자연히 빠진다. 품명은 이제 남긴다 (새 화면이 품명으로 화물을 구분). 로그와 트레이스에는 mask_bl()로 가린 번호만 남는다.

확인한 것 (2026-09-23):
- 엔드포인트는 https://unipass.customs.go.kr:38010/ext/rest/cargCsclPrgsInfoQry/retrieveCargCsclPrgsInfo
- 응답은 XML이고 루트가 cargCsclPrgsInfoQryRtnVo, 건수는 tCnt, 안내·오류 문구는 ntceInfo
- 없는 B/L은 tCnt=0, 파라미터가 빠지면 tCnt=-1과 안내 문구가 온다
- 실제 B/L 1건(HBL)으로 확인: cargMtNo(화물관리번호)는 19자리 = MRN 11 + MSN 4 + HSN 4.
  앞 11자리 MRN이 해수부 선박운항정보 mrNum과 같아서 B/L에서 배를 특정할 수 있다 (2026-09-23)

필드 이름 확정 (2026-09-27, UNI-PASS OpenAPI 연계가이드 v4.1 + 실제 응답 1건):
- 처음엔 필드 이름을 몰라 후보 여러 개를 찾았다. 확인한 이름 하나씩만 남겼다
- 상단 상태 칸은 셋이다. csclPrgsStts(통관진행상태, 예: 수입신고수리)와
  prgsStts + prgsStCd(화물 진행상태와 그 코드, 예: 반출완료 + CAGE12). stage_code는 prgsStCd를 쓴다.
  stage_name은 가장 최근 이력 줄의 처리구분이고, 이력이 없을 때만 csclPrgsStts를 쓴다.
  csclPrgsStts는 수입신고수리에서 멈춰 반출된 화물도 수리 단계로 보였다 (실제 B/L)
- 이력 줄(cargCsclPrgsInfoDtlQryVo)에는 단계 코드가 없고, 처리구분 cargTrcnRelaBsopTpcd에
  한글 이름이 바로 들어 있다 (예: 반입신고). 이전 코드는 이름을 다른 칸에서 찾아 이력을 전부 버렸다
- 이력은 최신이 위에 온다. 장치장명(shedNm)은 상단에 없고 이력 줄에만 있다
"""
from __future__ import annotations

import os
from datetime import date, datetime, timezone
from xml.etree import ElementTree

import httpx

from backend.app.clients.replay import replay_enabled, unipass_transport
from backend.app.clients.retry import with_retry
from backend.app.observability.langfuse import tool_span
from backend.app.schemas.customs import CustomsDetailRow, CustomsRecord, CustomsStage, mask_bl

BASE_URL = "https://unipass.customs.go.kr:38010/ext/rest/cargCsclPrgsInfoQry/retrieveCargCsclPrgsInfo"
TIMEOUT_SEC = 15.0

# 응답 필드 이름 (연계가이드 v4.1, 실제 응답으로 확인). _first()가 튜플을 받아서 튜플로 둔다
FIELD_CANDIDATES = {
    "ship_name": ("shipNm",),
    "ship_nat": ("shipNat",),
    "voyage": ("vydf",),
    "entry_date": ("etprDt",),
    "stage_name": ("csclPrgsStts",),  # 통관진행상태. 이력 줄이 없을 때만 단계 이름으로 쓴다 (_refine 참고)
    "stage_code": ("prgsStCd",),  # 진행상태코드. 짝은 prgsStts(화물 진행상태)라 stage_name과 뜻이 다를 수 있다
    "shed_name": ("shedNm",),  # 상단엔 없다. .// 검색이 최신 이력 줄(맨 위)의 값을 찾는다
    "discharge_port": ("dsprCd",),  # 양륙항 코드. 연계가이드 v4.1, 실제 부산 화물 1건은 KRPUS
    # 어디서 어디로 (실제 응답 상단에서 확인). 화물 카드에 "Qingdao(CN) → 부산항"으로 보인다
    "discharge_port_name": ("dsprNm",),
    "loading_port": ("ldprCd",),
    "loading_port_name": ("ldprNm",),
    "loading_country": ("lodCntyCd",),
    # 추가 (연계가이드 v4.1 API001 응답 항목). 포워더명은 비어 오는 화물이 많아 None이 흔하다
    "forwarder_name": ("frwrEntsConm",),
    "carrier_name": ("shcoFlco",),
    # 추가. 품명은 처음엔 버렸지만(SDD 3.5) 새 화면이 품명으로 화물을 구분해서 읽는다.
    # 실제 응답(마스터 B/L 1건)에서 상단에 영어 그대로 1건 왔다 (가공 예: TEST GOODS)
    "goods_name": ("prnm",),
}
CONTAINER_TAG = "cntrNo"  # 컨테이너 번호. 가이드상 API001은 1건(size 11)이라 보통 하나, 여럿이면 _join_all이 이어 붙인다
CONTAINER_JOIN = ", "
MRN_LENGTH = 11  # 화물관리번호 앞 MRN 길이 (실측 19자리 중 앞 11자리, 입항 MRN은 끝이 I)
STAGE_ITEM_TAG = "cargCsclPrgsInfoDtlQryVo"  # 이력 1줄
STAGE_FIELDS = {
    "name": ("cargTrcnRelaBsopTpcd",),  # 처리구분. 코드가 아니라 한글 이름이 들어 있다
    "at": ("prcsDttm",),  # 처리일시
}
# 화면 전용 처리 이력 원문의 칸 (schemas/customs.py CustomsDetailRow 필드 → UNI-PASS 태그). 실제 응답에서 확인한 13칸
DETAIL_FIELDS = {
    "kind": "cargTrcnRelaBsopTpcd", "processed_at": "prcsDttm", "declaration_no": "dclrNo", "moved_at": "rlbrDttm",
    "basis": "rlbrBssNo", "content": "rlbrCn", "notice": "bfhnGdncCn", "shed_name": "shedNm", "shed_code": "shedSgn",
    "package_count": "pckGcnt", "package_unit": "pckUt", "weight": "wght", "weight_unit": "wghtUt",
}


class CustomsError(Exception):
    """UNI-PASS 호출 실패. 라우터가 status와 안내 문구로 바꾼다 (SDD 8절)."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.retryable = code == "timeout"


def _first(node, names: tuple[str, ...]) -> str | None:
    """후보 이름을 순서대로 찾아 처음 나오는 값을 돌려준다."""
    for name in names:
        found = node.findtext(f".//{name}")
        if found and found.strip():
            return found.strip()
    return None


def _join_all(node, name: str) -> str | None:
    """같은 이름 태그를 전부 찾아 값이 있는 것만 중복 없이 순서대로 ', '로 이어 한 문자열로 돌려준다.
    컨테이너 번호용이다. 가이드(v4.1)는 API001의 cntrNo를 1건(11자)으로 적었고, 같은 번호가 나오는 컨테이너 내역 조회(API 별도)는
    0..n건이라 여러 개일 가능성을 열어 둔다. 한 칸에 여러 건이 와도 한 문자열로 두면 스키마를 안 바꾸고 화면·엑셀에 그대로 보인다."""
    values = []
    for found in node.findall(f".//{name}"):
        text = (found.text or "").strip()
        if text and text not in values:
            values.append(text)
    return CONTAINER_JOIN.join(values) if values else None


def _mrn(cargo_no: str | None) -> str | None:
    """화물관리번호에서 MRN(앞 11자리)만 꺼낸다. 짧으면 형식이 달라 None으로 둔다."""
    if not cargo_no or len(cargo_no) < MRN_LENGTH:
        return None
    return cargo_no[:MRN_LENGTH].upper()


def _dt(value: str | None) -> datetime | None:
    """20260923, 20260923103000, 2026-09-23T10:30:00+09:00 모두 받는다."""
    if not value:
        return None
    text = value.strip()
    for fmt in ("%Y%m%d%H%M%S", "%Y%m%d%H%M", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


class UnipassClient:
    def __init__(self, key: str | None = None, transport: httpx.BaseTransport | None = None):
        self._key = key or os.environ.get("UNIPASS_KEY", "")
        # REPLAY_MODE면 키 없이 evals/fixtures/replay/unipass/를 읽는다 (SDD 6.1, clients/replay.py).
        # 테스트가 transport를 직접 주면 그쪽이 먼저다
        if transport is None and replay_enabled():
            transport = unipass_transport()
            self._key = self._key or "replay"
        if not self._key:
            raise CustomsError("bad_key", "UNIPASS_KEY가 비어 있습니다")
        self._http = httpx.Client(timeout=TIMEOUT_SEC, transport=transport)

    def close(self) -> None:
        self._http.close()

    def fetch(self, bl_no: str, bl_type: str = "MASTER", bl_year: int | None = None) -> CustomsRecord | None:
        """B/L로 통관 진행정보를 가져온다. 조회 결과가 없으면 None.

        bl_type이 MASTER면 mblNo, HOUSE면 hblNo로 보낸다. 둘은 서로 다른 번호라
        잘못 고르면 결과가 없다고 나온다 (SDD 8절의 insufficient 경로).
        """
        number = bl_no.replace(" ", "").replace("-", "").upper()
        params = {
            "crkyCn": self._key,
            "blYy": str(bl_year or date.today().year),
            "mblNo" if bl_type.upper() == "MASTER" else "hblNo": number,
        }

        def call() -> httpx.Response:
            resp = self._http.get(BASE_URL, params=params)
            resp.raise_for_status()
            return resp

        # UNI-PASS 구간을 Langfuse에 남긴다. 15초 x 3회까지 갈 수 있는 판정 요청의 가장 큰 외부 대기다.
        # input은 가린 B/L뿐이고, metadata에 시도 횟수(retries = 시도 - 1)와 결과를 적는다
        stats: dict = {}
        with tool_span("unipass:fetch", {"bl": mask_bl(number), "bl_type": bl_type.upper()}) as span:
            try:
                # 타임아웃·5xx는 2회까지 다시 부른다 (A9, SDD 8절)
                root = ElementTree.fromstring(with_retry(call, name="unipass:cargCsclPrgsInfo", stats=stats).text)
            except httpx.TimeoutException as e:
                span.error = "timeout"
                raise CustomsError("timeout", "UNI-PASS 응답 시간 초과") from e
            except httpx.HTTPError as e:
                span.error = f"error {type(e).__name__}"
                raise CustomsError("error", f"UNI-PASS 호출 실패: {type(e).__name__}") from e
            except ElementTree.ParseError as e:
                span.error = "error parse"
                raise CustomsError("error", "UNI-PASS 응답이 XML이 아닙니다") from e
            finally:
                span.metadata["attempts"] = stats.get("attempts", 0)
                span.metadata["retries"] = max(stats.get("attempts", 1) - 1, 0)
            span.metadata["found"] = root.findtext("tCnt") not in (None, "0", "-1")

        count = root.findtext("tCnt")
        notice = (root.findtext("ntceInfo") or "").strip()
        if count == "-1" or (notice and count in (None, "0") and "필수" in notice):
            raise CustomsError("bad_input", notice or "UNI-PASS 요청 파라미터 오류")
        if count in (None, "0"):
            return None  # 없는 B/L. 실패가 아니라 insufficient로 간다 (SDD 4.1)

        return self._refine(root, number)

    @staticmethod
    def _refine(root, bl_no: str) -> CustomsRecord:
        """계약 C5에 있는 필드만 남긴다. 중량·화주는 애초에 옮기지 않는다 (품명은 이제 옮긴다).

        예외로 처리 이력 원문(display_rows)은 화면에 보여 주려고 13칸을 그대로 옮긴다. 이 칸은 model_dump에서 빠져
        LLM 입력에 들어가지 않는다 (schemas/customs.py, docs/specs/customs-detail.md).
        """
        stages = []
        # 원문은 응답 순서(최신이 위) 그대로 둔다. UNI-PASS 화면과 같은 순서라 사용자가 대조하기 쉽다
        rows = [CustomsDetailRow(**{key: (item.findtext(tag) or "").strip() or None for key, tag in DETAIL_FIELDS.items()})
                for item in root.iter(STAGE_ITEM_TAG)]
        for item in root.iter(STAGE_ITEM_TAG):
            name = _first(item, STAGE_FIELDS["name"])
            if not name:
                continue
            # 이력 줄에는 단계 코드 칸이 없다. 계약 C5의 code는 필수 문자열이라 빈 값으로 둔다
            stages.append(CustomsStage(code="", name=name, at=_dt(_first(item, STAGE_FIELDS["at"]))))
        stages.sort(key=lambda s: s.at or datetime.min)  # 응답은 최신이 위. 오래된 순으로 뒤집는다

        return CustomsRecord(
            ship_name=_first(root, FIELD_CANDIDATES["ship_name"]),
            ship_nat=_first(root, FIELD_CANDIDATES["ship_nat"]),
            voyage=_first(root, FIELD_CANDIDATES["voyage"]),
            entry_date=_dt(_first(root, FIELD_CANDIDATES["entry_date"])),
            stage_code=_first(root, FIELD_CANDIDATES["stage_code"]),
            # 현재 단계는 가장 최근 이력 줄. 상단 csclPrgsStts는 수입신고수리에서 멈춰 반출을 못 보여서
            # 이력이 없을 때만 쓴다 (실제 B/L: 반출완료 화물이 "다음은 반출신고"로 나옴)
            stage_name=stages[-1].name if stages else _first(root, FIELD_CANDIDATES["stage_name"]),
            shed_name=_first(root, FIELD_CANDIDATES["shed_name"]),
            discharge_port=_first(root, FIELD_CANDIDATES["discharge_port"]),
            discharge_port_name=_first(root, FIELD_CANDIDATES["discharge_port_name"]),
            loading_port=_first(root, FIELD_CANDIDATES["loading_port"]),
            loading_port_name=_first(root, FIELD_CANDIDATES["loading_port_name"]),
            loading_country=_first(root, FIELD_CANDIDATES["loading_country"]),
            mrn=_mrn(_first(root, ("cargMtNo",))),
            forwarder_name=_first(root, FIELD_CANDIDATES["forwarder_name"]),
            carrier_name=_first(root, FIELD_CANDIDATES["carrier_name"]),
            container_no=_join_all(root, CONTAINER_TAG),
            goods_name=_first(root, FIELD_CANDIDATES["goods_name"]),
            stage_history=stages,
            display_rows=rows,
            bl_masked=mask_bl(bl_no),
            fetched_at=datetime.now(timezone.utc),
        )

