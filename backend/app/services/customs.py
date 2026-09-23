"""UNI-PASS 화물통관진행정보 조회와 정제 (작업 A8).

B/L 번호로 통관 진행 상태와 선박 정보를 가져온다. 이 조회는 LLM이 하지 않고 코드가 직접 한다.
B/L 번호를 LLM에 넘기면 숫자를 잘못 옮기거나 프롬프트 주입에 쓰일 수 있어서다 (SDD 6.3, CLAUDE.md).

응답에서 계약 C5(CustomsRecord)에 있는 필드만 남긴다. 품명·중량·세관명·화주 정보는
모델에 자리가 없어 자연히 빠진다. 로그와 트레이스에는 mask_bl()로 가린 번호만 남는다.

확인한 것 (2026-09-23):
- 엔드포인트는 https://unipass.customs.go.kr:38010/ext/rest/cargCsclPrgsInfoQry/retrieveCargCsclPrgsInfo
- 응답은 XML이고 루트가 cargCsclPrgsInfoQryRtnVo, 건수는 tCnt, 안내·오류 문구는 ntceInfo
- 없는 B/L은 tCnt=0, 파라미터가 빠지면 tCnt=-1과 안내 문구가 온다
- 성공 응답의 필드 이름은 공개 문서에 없어서 SDD 3.5 기준으로 잡고, 이름이 다를 경우를 대비해
  후보 여러 개를 순서대로 찾는다. 실제 B/L로 한 번 확인한 뒤 후보를 줄인다
"""
from __future__ import annotations

import os
from datetime import date, datetime, timezone
from xml.etree import ElementTree

import httpx

from backend.app.schemas.customs import CustomsRecord, CustomsStage, mask_bl

BASE_URL = "https://unipass.customs.go.kr:38010/ext/rest/cargCsclPrgsInfoQry/retrieveCargCsclPrgsInfo"
TIMEOUT_SEC = 15.0

# 응답 필드 이름 후보. 앞에서부터 찾아 처음 있는 값을 쓴다 (SDD 3.5 기준 + 흔한 변형)
FIELD_CANDIDATES = {
    "ship_name": ("shipNm", "sanm", "shipNmKr"),
    "ship_nat": ("shipNat", "shipNatNm", "ldprNat"),
    "voyage": ("vydf", "vydfNo", "voyNo"),
    "entry_date": ("etprDt", "etprCstm", "etprDttm"),
    "stage_name": ("csclPrgsStts", "prgsStts", "cargTrcnRelaBsopTpcd"),
    "stage_code": ("prgsStCd", "csclPrgsSttsCd", "prgsStts"),
    "shed_name": ("shedNm", "shedNmKr", "shedCd"),
}
STAGE_ITEM_TAGS = ("cargCsclPrgsInfoDtlQryVo", "cargCsclPrgsInfoDtlQryRtnVo", "detail")
STAGE_FIELDS = {
    "code": ("cargTrcnRelaBsopTpcd", "prgsStCd", "shedSgn"),
    "name": ("cargTrcnRelaBsopTpcdNm", "csclPrgsStts", "prgsStts"),
    "at": ("prcsDttm", "rlbrDttm", "shedRlbrDttm"),
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

        try:
            resp = self._http.get(BASE_URL, params=params)
            resp.raise_for_status()
            root = ElementTree.fromstring(resp.text)
        except httpx.TimeoutException as e:
            raise CustomsError("timeout", "UNI-PASS 응답 시간 초과") from e
        except httpx.HTTPError as e:
            raise CustomsError("error", f"UNI-PASS 호출 실패: {type(e).__name__}") from e
        except ElementTree.ParseError as e:
            raise CustomsError("error", "UNI-PASS 응답이 XML이 아닙니다") from e

        count = root.findtext("tCnt")
        notice = (root.findtext("ntceInfo") or "").strip()
        if count == "-1" or (notice and count in (None, "0") and "필수" in notice):
            raise CustomsError("bad_input", notice or "UNI-PASS 요청 파라미터 오류")
        if count in (None, "0"):
            return None  # 없는 B/L. 실패가 아니라 insufficient로 간다 (SDD 4.1)

        return self._refine(root, number)

    @staticmethod
    def _refine(root, bl_no: str) -> CustomsRecord:
        """계약 C5에 있는 필드만 남긴다. 품명·중량·화주는 애초에 옮기지 않는다."""
        stages = []
        for tag in STAGE_ITEM_TAGS:
            for item in root.iter(tag):
                name = _first(item, STAGE_FIELDS["name"])
                if not name:
                    continue
                stages.append(
                    CustomsStage(
                        code=_first(item, STAGE_FIELDS["code"]) or "",
                        name=name,
                        at=_dt(_first(item, STAGE_FIELDS["at"])),
                    )
                )
            if stages:
                break
        stages.sort(key=lambda s: s.at or datetime.min)

        return CustomsRecord(
            ship_name=_first(root, FIELD_CANDIDATES["ship_name"]),
            ship_nat=_first(root, FIELD_CANDIDATES["ship_nat"]),
            voyage=_first(root, FIELD_CANDIDATES["voyage"]),
            entry_date=_dt(_first(root, FIELD_CANDIDATES["entry_date"])),
            stage_code=_first(root, FIELD_CANDIDATES["stage_code"]),
            stage_name=_first(root, FIELD_CANDIDATES["stage_name"]) or (stages[-1].name if stages else None),
            shed_name=_first(root, FIELD_CANDIDATES["shed_name"]),
            stage_history=stages,
            bl_masked=mask_bl(bl_no),
            fetched_at=datetime.now(timezone.utc),
        )
