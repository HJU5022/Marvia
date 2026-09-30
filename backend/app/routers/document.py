"""POST /api/document: 서류 사진에서 조회 값 7칸을 뽑아 확인 화면용으로 돌려준다 (docs/specs/document-extract.md).

처리 순서 (Spec "흐름"):
  1~2. 전처리 + OCR               services/doc_ocr.read_lines (로컬, 외부 호출 없음)
  3.   B/L 번호를 코드로 뽑고 가림   doc_ocr.take_bl, mask_bl. 가려지지 않으면 LLM을 부르지 않는다
  4.   나머지 6칸                   services/llm.extract_doc_fields (소형 모델, LLM_MODEL)
  5.   칸 검사                      doc_ocr.check_fields
여기서 판정하지 않고 LLM SDK를 import하지 않는다 (CLAUDE.md). 뽑은 값으로 /api/agent를 부르지도 않는다. 사용자가 확인한 뒤 프론트가 부른다.
대형 비전 모델로 넘기기는 2차다. 지금은 검사에 걸리면 needs_review=true로 사용자에게 맡긴다.
"""
from contextlib import nullcontext

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from PIL import UnidentifiedImageError

from backend.app.observability.langfuse import session_scope
from backend.app.observability.logging import current_request_id, log_failure
from backend.app.schemas.document import DocumentFields, DocumentResponse, FieldResult, OcrInfo
from backend.app.services import doc_ocr, llm

router = APIRouter(prefix="/api", tags=["document"])

# 사진 한 장 상한. 폰 사진이 보통 2~5MB라 넉넉히 잡되, 큰 파일로 서버 메모리를 쓰게 두지 않는다 (Spec EC-02, 임시값)
MAX_BYTES = 10 * 1024 * 1024
LLM_FIELDS = ("vessel", "voyage", "eta", "pol", "pod", "item")


@router.post("/document", response_model=DocumentResponse)
def read_document(file: UploadFile = File(...), session_id: str | None = Form(None)) -> DocumentResponse:
    """사진을 받아 7칸을 채운다. def(동기)로 둔 이유: OCR이 CPU를 1~2초 쓰므로 FastAPI가 스레드풀에서 돌리게 한다."""
    data = file.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="too_large")
    try:
        ocr = doc_ocr.read_lines(data)
    except (UnidentifiedImageError, OSError):
        raise HTTPException(status_code=400, detail="invalid_image")

    bl = doc_ocr.take_bl(ocr.lines)
    values: dict[str, str | None] = {"bl_no": bl, **{k: None for k in LLM_FIELDS}}
    status = "ok"
    try:
        masked = doc_ocr.mask_bl(ocr.lines, bl)
    except ValueError:
        # 가려지지 않은 B/L을 LLM에 보내지 않는다 (CLAUDE.md). 코드가 뽑은 B/L만 돌려준다
        log_failure("doc_mask", "bl_not_masked")
        masked, status = None, "partial"

    if masked is not None and ocr.lines:
        with session_scope(session_id) if session_id else nullcontext():  # session 없이 오면 트레이스만 남긴다
            try:
                out = llm.extract_doc_fields(masked).output
                values.update({k: getattr(out, k) for k in LLM_FIELDS})
                values["vessel"] = doc_ocr.strip_ship_suffix(values["vessel"])
            except llm.LLMError as e:  # 키 없음·과부하·형식 깨짐 모두 (Spec EC-05)
                log_failure("doc_extract", f"{e.kind} {e.code}" if e.code else e.kind)
                status = "partial"

    checks = doc_ocr.check_fields(values, ocr.lines)
    fields = DocumentFields(**{k: FieldResult(value=values[k], checks=checks[k]) for k in doc_ocr.FIELDS})
    return DocumentResponse(
        status=status,
        needs_review=any(checks.values()),
        fields=fields,
        ocr=OcrInfo(lines=len(ocr.lines), rotation=ocr.rotation, runs=ocr.runs, ocr_ms=ocr.ocr_ms),
        trace_id=current_request_id(),
    )

