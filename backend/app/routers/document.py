"""POST /api/document: 서류 사진에서 조회 값 7칸과 출항일(etd)을 뽑아 확인 화면용으로 돌려준다 (docs/specs/document-extract.md).

처리 순서 (Spec "흐름"):
  1~2. 전처리 + OCR               services/chat/doc_ocr.read_lines (로컬, 외부 호출 없음). PDF(%PDF로 시작)는 read_pdf: 글자층 먼저, 없으면 그림으로 OCR
  3.   B/L 번호를 코드로 뽑고 가림   doc_ocr.take_bl, mask_bl. 가려지지 않으면 LLM을 부르지 않는다
  4.   나머지 6칸                   services/llm.extract_doc_fields (소형 모델, LLM_MODEL)
  5.   칸 검사                      doc_ocr.check_fields, B/L 조건·연락처는 doc_ocr.check_conditions (결정 6)
여기서 판정하지 않고 LLM SDK를 import하지 않는다 (CLAUDE.md). 뽑은 값으로 /api/agent를 부르지도 않는다. 사용자가 확인한 뒤 프론트가 부른다.
대형 비전 모델로 넘기기는 2차다. 지금은 검사에 걸리면 needs_review=true로 사용자에게 맡긴다.
"""
from contextlib import nullcontext
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from PIL import UnidentifiedImageError
from pydantic import BaseModel, Field

from backend.app.auth import current_user_id
from backend.app.observability.langfuse import request_span, session_scope
from backend.app.observability.logging import current_request_id, log_failure
from backend.app.routers.agent import quota_guard
from backend.app.schemas.document import DocumentFields, DocumentResponse, FieldResult, OcrInfo
from backend.app.services.chat import doc_ocr
from backend.app.services import llm

router = APIRouter(prefix="/api", tags=["document"])

# 사진 한 장 상한. 폰 사진이 보통 2~5MB라 넉넉히 잡되, 큰 파일로 서버 메모리를 쓰게 두지 않는다 (Spec EC-02, 임시값)
MAX_BYTES = 10 * 1024 * 1024
# 해상도 초과 안내 (상한은 doc_ocr.MAX_IMAGE_PIXELS). 용량이 작아도 픽셀이 너무 많으면 읽는 데 오래 걸려 거절한다
IMAGE_TOO_LARGE_MESSAGE = "사진 해상도가 너무 커요. 5000만 화소(약 7000x7000) 이하로 줄여서 올려 주세요."
LLM_FIELDS = ("vessel", "voyage", "eta", "pol", "pod", "item", "etd")  # etd는 없으면 null (프롬프트에 아직 없을 때도 안전)
# 서류 종류 → 거래처 출처 이름 (메모장 거래처 출처 목록, docs/specs/memory.md)
DOC_KIND = {"bl": "B/L", "arrival_notice": "A/N"}


def _ocr_upload(file: UploadFile) -> doc_ocr.OcrResult:
    """올린 파일을 읽어 OCR 결과를 돌려준다. 전체 판독(/api/document)과 B/L만 찾기(/api/document/bl)가 같이 쓴다.
    크기·형식 오류는 400이다. PDF 여부는 앞 4바이트로 가른다. 파일 이름·content-type은 믿지 않는다."""
    data = file.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="too_large")
    if doc_ocr.is_pdf(data):
        try:
            return doc_ocr.read_pdf(data)
        except doc_ocr.InvalidPdf:
            raise HTTPException(status_code=400, detail="invalid_pdf")
    try:
        return doc_ocr.read_lines(data)
    except doc_ocr.ImageTooLarge:
        # 해상도 초과·압축 폭탄. 프론트는 400의 detail 글을 그대로 보여 주므로 한국어 문장을 담는다
        raise HTTPException(status_code=400, detail=IMAGE_TOO_LARGE_MESSAGE)
    except (UnidentifiedImageError, OSError):
        raise HTTPException(status_code=400, detail="invalid_image")


class DocumentBlResponse(BaseModel):
    """B/L만 찾기 응답. 채팅 첨부가 쓴다. 코드가 뽑은 값만 담고 LLM 필드는 없다."""
    bl_no: str | None = Field(description="코드(doc_ocr.take_bl)가 뽑은 B/L. 못 찾으면 null")
    mrn: str | None = Field(default=None, description="코드(doc_ocr.take_mrn)가 뽑은 MRN. 없으면 null")
    ocr: OcrInfo
    trace_id: str


@router.post("/document/bl", response_model=DocumentBlResponse)
def read_document_bl(file: UploadFile = File(...), session_id: str | None = Form(None),
                     user_id: Annotated[str | None, Depends(current_user_id)] = None) -> DocumentBlResponse:
    """서류에서 B/L 번호(와 MRN)만 코드로 뽑는다.: 채팅 첨부는 "보내기"를 눌렀을 때만 이 길로 읽고,
    뽑은 B/L로 바로 채팅 조회를 보낸다. 선박·항차·날짜·연락처 같은 LLM 칸은 읽지 않는다: 토큰과 시간이 들고,
    조회가 UNI-PASS 등에서 더 정확한 값을 가져오기 때문이다. 그래서 LLM을 부르지 않고 B/L도 LLM에 보내지 않는다 (CLAUDE.md).
    OCR만 돌리므로 보통 1~3초다. 전체 7칸 판독은 POST /api/document가 그대로 맡는다."""
    with request_span("/api/document/bl"):
        quota_guard(session_id, user_id)  # 토큰은 안 쓰지만 한도를 다 쓴 사용자는 채팅이 막히므로 같은 문턱을 둔다
        ocr = _ocr_upload(file)
        return DocumentBlResponse(
            bl_no=doc_ocr.take_bl(ocr.lines), mrn=doc_ocr.take_mrn(ocr.lines),
            ocr=OcrInfo(lines=len(ocr.lines), rotation=ocr.rotation, runs=ocr.runs, ocr_ms=ocr.ocr_ms),
            trace_id=current_request_id())


@router.post("/document", response_model=DocumentResponse)
def read_document(file: UploadFile = File(...), session_id: str | None = Form(None),
                  user_id: Annotated[str | None, Depends(current_user_id)] = None) -> DocumentResponse:
    """사진을 받아 7칸을 채운다. def(동기)로 둔 이유: OCR이 CPU를 1~2초 쓰므로 FastAPI가 스레드풀에서 돌리게 한다.
    로그인 필수다 (auth.py). 로그인 기능이 꺼진 채점 환경에서만 user_id 없이 돈다."""
    # 요청 전체를 루트 span 하나로 감싼다. OCR(ocr:read)과 서류 칸 추출 LLM이 그 자식이 된다. 키가 없으면 아무것도 안 한다
    with request_span("/api/document"):
        return _read_document(file, session_id, user_id)


def _read_document(file: UploadFile, session_id: str | None, user_id: str | None) -> DocumentResponse:
    """read_document의 실제 처리. 루트 span 안에서 불린다."""
    # 서류 판독도 LLM을 부르므로 하루 토큰 한도를 확인한다 (docs/specs/token-quota.md)
    quota_guard(session_id, user_id)
    ocr = _ocr_upload(file)

    bl = doc_ocr.take_bl(ocr.lines)
    values: dict[str, str | None] = {"bl_no": bl, **{k: None for k in LLM_FIELDS}}
    conditions: dict[str, str | None] = {}
    evidence: dict[str, str | None] = {}
    doc_kind = None
    status = "ok"
    llm_error: str | None = None  # LLM 단계가 실패한 종류(bad_format, timeout 등). 화면이 "AI가 못 읽었다"를 알리는 데 쓴다
    try:
        masked = doc_ocr.mask_bl(ocr.lines, bl)
    except ValueError:
        # 가려지지 않은 B/L을 LLM에 보내지 않는다 (CLAUDE.md). 코드가 뽑은 B/L만 돌려준다
        log_failure("doc_mask", "bl_not_masked")
        masked, status = None, "partial"

    if masked is not None and ocr.lines:
        # 로그인 사용자면 session 없이 와도 범위를 연다. 안 열면 서류 판독 토큰이 하루 한도에 안 쌓인다 (services/account/quota.py)
        with session_scope(session_id, user_id) if (session_id or user_id) else nullcontext():  # 둘 다 없으면 트레이스만 남긴다
            try:
                out = llm.extract_doc_fields(masked).output
                values.update({k: getattr(out, k) for k in LLM_FIELDS})
                values["vessel"] = doc_ocr.strip_ship_suffix(values["vessel"])
                conditions = {k: getattr(out, k) for k in doc_ocr.CONDITION_FIELDS}
                if out.to_order_bank is not None:  # 응답 칸은 글자다 (FieldResult.value)
                    conditions["to_order_bank"] = "true" if out.to_order_bank else "false"
                evidence = {k: getattr(out, k) for k in doc_ocr.EVIDENCE_OF.values()}
                doc_kind = DOC_KIND.get(out.doc_kind or "")
            except llm.LLMError as e:  # 키 없음·과부하·형식 깨짐 모두 (Spec EC-05)
                log_failure("doc_extract", f"{e.kind} {e.code}" if e.code else e.kind)
                status = "partial"
                # 빈 칸만 보이면 사용자가 서류 탓인지 AI 탓인지 모른다. 실패 종류를 응답에 실어 다시 시도하게 안내한다
                llm_error = e.kind

    checks = doc_ocr.check_fields(values, ocr.lines)
    shown, extra_checks = doc_ocr.check_conditions(conditions, evidence, ocr.lines)
    fields = DocumentFields(**{k: FieldResult(value=values[k], checks=checks[k]) for k in doc_ocr.FIELDS},
                            **{k: FieldResult(value=shown[k], checks=extra_checks[k]) for k in doc_ocr.CONDITION_FIELDS})
    return DocumentResponse(
        status=status,
        needs_review=any(checks.values()) or any(extra_checks.values()),
        fields=fields,
        ocr=OcrInfo(lines=len(ocr.lines), rotation=ocr.rotation, runs=ocr.runs, ocr_ms=ocr.ocr_ms),
        trace_id=current_request_id(),
        mrn=doc_ocr.take_mrn(ocr.lines),  # 세관에 아직 없는 화물의 대체 조회용 (mrn-fallback)
        doc_kind=doc_kind,
        llm_error=llm_error,
    )

