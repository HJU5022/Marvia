"""FastAPI 진입점.

라우터 등록과 미들웨어만 둔다. LLM 호출은 services/llm.py 한 곳에서만 한다 (CLAUDE.md).

미들웨어:
- RequestLogMiddleware: 요청마다 JSON 로그 한 줄 (A5, SDD 5.11)
- CORS: ALLOWED_ORIGINS에 적힌 출처만 (A10, SDD 7절)

기동할 때 DB 마이그레이션을 적용한다. 워커는 기본이 꺼짐이라 워커만 믿으면 query_log 같은 표가 안 생긴다.
DB가 없거나 붙지 않으면 경고만 남기고 서버는 뜬다 (DB 없이도 판정은 돌아야 한다).
"""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.db import apply_migrations, connect
from backend.app.observability.langfuse import flush as langfuse_flush
from backend.app.observability.logging import RequestLogMiddleware, setup_logging
from backend.app.routers import agent, document, history

setup_logging()
logger = logging.getLogger(__name__)


def _migrate() -> None:
    """DATABASE_URL이 있을 때만 migrations/*.sql을 적용한다. 이미 적용한 파일은 건너뛴다 (db/__init__.py)."""
    if not os.environ.get("DATABASE_URL"):
        return
    try:
        with connect() as conn:
            applied = apply_migrations(conn)
        if applied:
            logger.info("migrations applied: %s", applied)
    except Exception as e:
        logger.warning("DB 마이그레이션을 적용하지 못했습니다(%s). DB 없이 계속합니다", type(e).__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _migrate()
    yield
    # 꺼질 때 남은 트레이스를 보낸다. 안 하면 마지막 요청들의 트레이스가 사라진다 (observability/langfuse.flush)
    langfuse_flush()


app = FastAPI(title="Marvia API", lifespan=lifespan)
app.add_middleware(RequestLogMiddleware)
app.add_middleware(
    CORSMiddleware,
    # 기본값은 로컬 프론트만. 배포에서는 .env의 ALLOWED_ORIGINS에 Vercel 도메인을 넣는다
    allow_origins=[o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


app.include_router(agent.router)
app.include_router(history.router)
app.include_router(document.router)  # 서류 사진 (docs/specs/document-extract.md)


@app.get("/health")
def health() -> dict:
    """채점자와 배포 환경이 서비스 상태를 확인하는 곳."""
    return {"status": "ok"}

