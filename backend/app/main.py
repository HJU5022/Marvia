"""FastAPI 진입점.

라우터 등록과 미들웨어만 둔다. LLM 호출은 services/llm.py 한 곳에서만 한다 (CLAUDE.md).

미들웨어:
- RequestLogMiddleware: 요청마다 JSON 로그 한 줄 (A5, SDD 5.11)
- CORS: ALLOWED_ORIGINS에 적힌 출처만 (A10, SDD 7절)

MCP 서버(/mcp)도 이 앱의 경로로 붙인다 (09-29 결정, SDD 5.9). 서버·Cloud Run 서비스가 하나로 끝난다.
외부 MCP 클라이언트(Claude Desktop 등)용 창구이고, 서비스 자신은 도구 함수를 직접 부른다.

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
from backend.app.routers import account, admin, agent, document, history, profile
from mcp_server.server import MountedMCP

setup_logging()
logger = logging.getLogger(__name__)
mcp_app = MountedMCP()


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
    # /mcp의 세션 관리자를 서버 수명 동안 돌린다. 이게 없으면 /mcp 요청이 처리되지 않는다 (MountedMCP)
    async with mcp_app.running():
        yield
    # 꺼질 때 남은 트레이스를 보낸다. 안 하면 마지막 요청들의 트레이스가 사라진다 (observability/langfuse.flush)
    langfuse_flush()


app = FastAPI(title="Marvia API", lifespan=lifespan)
app.add_middleware(RequestLogMiddleware)
app.add_middleware(
    CORSMiddleware,
    # 기본값은 로컬 프론트만. 배포에서는 .env의 ALLOWED_ORIGINS에 Vercel 도메인을 넣는다
    allow_origins=[o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip()],
    allow_methods=["GET", "POST", "DELETE"],  # DELETE: 내 기록 삭제·회원 탈퇴 (09-30). 빠지면 브라우저가 막는다
    allow_headers=["*"],
)


app.include_router(agent.router)
app.include_router(history.router)
app.include_router(document.router)  # 서류 사진 (docs/specs/document-extract.md)
app.include_router(account.router)  # 회원 탈퇴 (삭제 3단계)
app.include_router(admin.router)  # 운영자 관리 (docs/specs/operator-admin.md)
app.include_router(profile.router)  # 회원 정보 (docs/specs/user-profile.md)


# /mcp: MCP 클라이언트가 연결하는 프로토콜 창구. /api/agent(사용자 화면용)와 경로를 나눈다 (가이드 v4 배포 구조).
# MCP_TOKEN이 있으면 Bearer 토큰 없이는 401 (mcp_server/auth.py)
app.add_route("/mcp", mcp_app, include_in_schema=False)


@app.get("/health")
def health() -> dict:
    """채점자와 배포 환경이 서비스 상태를 확인하는 곳."""
    return {"status": "ok"}

