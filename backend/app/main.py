"""FastAPI 진입점.

라우터 등록과 미들웨어만 둔다. LLM 호출은 services/llm.py 한 곳에서만 한다 (CLAUDE.md).

미들웨어:
- RequestLogMiddleware: 요청마다 JSON 로그 한 줄 (A5, SDD 5.11)
- CORS: ALLOWED_ORIGINS에 적힌 출처만 (A10, SDD 7절)
"""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.observability.logging import RequestLogMiddleware, setup_logging
from backend.app.routers import agent, history

setup_logging()

app = FastAPI(title="Marvia API")
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


@app.get("/health")
def health() -> dict:
    """채점자와 배포 환경이 서비스 상태를 확인하는 곳."""
    return {"status": "ok"}

