"""FastAPI 진입점. 라우터 등록, DB 연결 수명 관리. (SDD 1절)

LLM 호출은 여기가 아니라 services/llm.py 에, DB 접근은 services/store.py 에 모은다.
3차 프로젝트에서 그 자리에 RAG 그래프가 들어온다 — 호출부가 흩어져 있으면 그때 전부 뜯어야 한다.

아직 없는 것 (SDD 1절 순서대로 붙일 예정):
  routers/internal.py POST /internal/cleanup — Cloud Scheduler가 하루 1회, store.cleanup_expired
  /mcp 마운트         mcp_server/server.py 를 ASGI로
  request_id 미들웨어 요청마다 uuid를 만들어 응답 헤더와 request_logs 에 (SDD 1절 main.py 설명)
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.routers import agent, session
from backend.app.services import store


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱이 켜질 때 DB 풀을 열고, 꺼질 때 닫는다.

    켤 때 미리 여는 이유: 첫 요청에서 여는 것보다 "DATABASE_URL이 틀렸다"를 기동 시점에 바로 알 수 있다.
    compose는 db가 healthy가 된 뒤에 api를 띄우므로 (docker-compose.yml depends_on) 여기서 붙을 수 있다.
    """
    await store.get_pool()
    yield
    await store.close_pool()


app = FastAPI(title="Converge API", lifespan=lifespan)

# CORS: 브라우저는 다른 주소(프론트 :3000)에서 이 API(:8000)를 부를 때 서버가 "그 주소 허용"이라고
# 답해야만 응답을 넘겨준다. curl·서버 간 호출에는 없는 브라우저 전용 규칙.
# 허용 주소는 FRONTEND_ORIGIN 환경변수. 로컬은 http://localhost:3000, 배포는 Vercel 주소. 쉼표로 여러 개.
# allow_credentials=True: Authorization 헤더(로그인 토큰)를 실어 보낼 수 있게.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000").split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agent.router)
app.include_router(session.router)


@app.get("/health")
def health() -> dict:
    """채점자와 배포 환경이 서비스 상태를 확인하는 곳. 로그인 없음 (결정 4). 지우지 않는다 (BACKEND_GUIDE)."""
    return {"status": "ok"}
