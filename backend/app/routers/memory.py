"""화물 비서 기억 창구 (docs/specs/memory.md "API", 결정 7).

창구만 한다: 로그인 확인 → services(memory, cargo) 부르기 → HTTP 응답. 검사·저장 규칙은 services에 있다.
  GET    /api/memory                    내 메모장 보기 (번호 없는 마크다운 + 항목 + 화물 요약, 원본 B/L 없음)
  DELETE /api/memory                    메모장 전부 지우기 (화물 표는 남는다, 결정 D2)
  DELETE /api/memory/items/{id}         메모장 항목 하나 지우기
  POST   /api/memory/document-facts     서류 확인 화면에서 확인한 B/L 조건·거래처 저장
로그인 필수다. 로그인 기능이 꺼진 채점 환경은 사람이 없어 401 (EC-08). 삭제는 실패를 숨기지 않고 503 (routers/history.py와 같다).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from backend.app.auth import current_user_id
from backend.app.db import connect
from backend.app.observability.logging import log_failure
from backend.app.schemas.memory import (
    CargoSummary, DocumentFactsRequest, DocumentFactsResponse, MemoryDeleteResponse, MemoryItem, MemoryResponse,
)
from backend.app.services.watch import cargo
from backend.app.services.account import memory
from backend.app.services.chat.chat import DEFAULT_BL_TYPE
from backend.app.services.judge.evidence import KST

router = APIRouter(prefix="/api", tags=["memory"])

DB_DOWN = "기억 저장소에 연결하지 못했습니다. 잠시 뒤 다시 시도하세요"


def _login_required(user_id: str | None) -> str:
    """로그인한 사람만. 로그인 기능이 꺼진 환경에는 기억할 사람이 없다 (EC-08)."""
    if not user_id:
        raise HTTPException(status_code=401, detail="로그인한 사용자만 기억을 볼 수 있습니다",
                            headers={"WWW-Authenticate": "Bearer"})
    return user_id


def _db_required(stage: str) -> None:
    """지우기·저장은 DB가 있어야 한다. 없으면 0건으로 숨기지 않고 503 (routers/history.py와 같은 원칙)."""
    if not os.environ.get("DATABASE_URL"):
        log_failure(stage, "not_configured")
        raise HTTPException(status_code=503, detail=DB_DOWN)


def _summary(row: dict) -> CargoSummary:
    """화물 줄을 화면 요약으로. 지문·잠긴 B/L·배 번호는 옮기지 않는다."""
    keep = {k: row.get(k) for k in CargoSummary.model_fields if k not in ("pending", "summary")}
    return CargoSummary(**keep, pending=row.get("pending") or [],
                        summary=cargo.done_summary(row) if row.get("status") == "done" else None)


@router.get("/memory", response_model=MemoryResponse)
def get_memory(user_id: Annotated[str | None, Depends(current_user_id)] = None) -> MemoryResponse:
    """내 메모장과 화물 요약. DB를 못 읽으면 available=false (빈 기억과 구분한다)."""
    user_id = _login_required(user_id)
    if not os.environ.get("DATABASE_URL"):
        log_failure("memory_view", "not_configured")
        return MemoryResponse(markdown="", items=[], cargo=[], full=False, available=False)
    try:
        with connect() as conn:
            seen = memory.view(conn, user_id)
    except Exception as e:  # noqa: BLE001
        log_failure("memory_view", type(e).__name__)
        return MemoryResponse(markdown="", items=[], cargo=[], full=False, available=False)
    rows = {r["cargo_key"]: r for r in seen["cargo"]}
    items = [MemoryItem(id=i["id"], section=i["section"], kind=i["kind"], fields=i.get("fields") or {},
                        noted_at=i.get("noted_at"),
                        cargo_name=memory.cargo_name(rows.get(i.get("cargo_key"))) if i["section"] == "cargo" else None)
             for i in seen["items"]]
    return MemoryResponse(markdown=seen["markdown"], items=items, cargo=[_summary(r) for r in seen["cargo"]],
                          full=seen["full"], used_chars=len(seen["markdown"]), max_chars=memory.MAX_CHARS)


@router.delete("/memory", response_model=MemoryDeleteResponse)
def delete_memory(user_id: Annotated[str | None, Depends(current_user_id)] = None) -> MemoryDeleteResponse:
    """메모장을 전부 지운다 (Spec "사용자는 전부 지울 수 있다", 개인정보보호법 제36조). deleted는 지운 메모 항목 수.
    화물 표(기억한 화물)와 조회 기록은 남는다 (결정 D2). 화물 표는 "내 조회 기록 지우기"(DELETE /api/history)와 탈퇴가 지운다."""
    user_id = _login_required(user_id)
    _db_required("memory_delete")
    try:
        with connect() as conn:
            deleted = memory.delete_all(conn, user_id)
    except Exception as e:  # noqa: BLE001
        log_failure("memory_delete", type(e).__name__)
        raise HTTPException(status_code=503, detail=DB_DOWN) from None
    return MemoryDeleteResponse(deleted=deleted)


@router.delete("/memory/items/{item_id}", response_model=MemoryDeleteResponse)
def delete_memory_item(item_id: str, user_id: Annotated[str | None, Depends(current_user_id)] = None) -> MemoryDeleteResponse:
    """메모장 항목 하나를 지운다. 없는 번호면 404, 동시 수정이 계속 겹쳐 못 지웠으면 503 (지운 척하지 않는다)."""
    user_id = _login_required(user_id)
    _db_required("memory_delete")
    try:
        with connect() as conn:
            status = memory.delete_item(conn, user_id, item_id)
    except Exception as e:  # noqa: BLE001
        log_failure("memory_delete", type(e).__name__)
        raise HTTPException(status_code=503, detail=DB_DOWN) from None
    if status == "missing":
        raise HTTPException(status_code=404, detail="지울 항목이 없습니다")
    if status != "deleted":
        log_failure("memory_delete", status)
        raise HTTPException(status_code=503, detail="다른 기기에서 기억을 고치는 중이라 지우지 못했습니다. 잠시 뒤 다시 시도하세요")
    return MemoryDeleteResponse(deleted=1)


@router.post("/memory/document-facts", response_model=DocumentFactsResponse)
def save_document_facts(body: DocumentFactsRequest,
                        user_id: Annotated[str | None, Depends(current_user_id)] = None) -> DocumentFactsResponse:
    """서류 확인 화면에서 사용자가 "확인한 값으로 채우기"를 누른 값만 저장한다 (결정 7).

    - B/L 조건(원본 B/L·은행 지시식·운임·인코텀즈)은 화물 표 줄에. 줄이 없으면 만든다. 모르는 칸(null)은 덮지 않는다
    - 거래처는 메모장 거래처 항목으로, 출처는 B/L 또는 A/N. 서류 종류(source)를 모르면 저장하지 않는다
    - B/L 구분을 모르면 채팅 창구 기본값(하우스)으로 새 줄을 만든다. 나중 조회가 실제 구분으로 고친다
    """
    user_id = _login_required(user_id)
    _db_required("memory_document")
    facts = body.model_dump(include={"original_bl", "to_order_bank", "freight_term", "incoterm"})
    today = datetime.now(timezone.utc).astimezone(KST).date()
    try:
        with connect() as conn:
            key, saved = None, False
            if any(v is not None for v in facts.values()):
                key = cargo.apply_document_facts(conn, user_id, body.bl_no, body.bl_type or DEFAULT_BL_TYPE, facts)
                saved = key is not None
            contact = "skipped"
            if body.contact and body.source:
                key = key or cargo.cargo_key(body.bl_no)
                if key and cargo.get_row(conn, user_id, key) is None:
                    key = None  # 화물 줄이 없으면(조건 없이 거래처만) 이 사람에 대해 칸에 둔다
                contact = memory.add_contact(conn, user_id, {**body.contact.model_dump(), "source": body.source},
                                             key, today)
    except Exception as e:  # noqa: BLE001
        log_failure("memory_document", type(e).__name__)
        raise HTTPException(status_code=503, detail=DB_DOWN) from None
    return DocumentFactsResponse(conditions_saved=saved, contact=contact)
