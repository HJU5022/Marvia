# 필수 조건 2. 채점자가 `docker compose up` 한 줄로 띄울 수 있어야 한다.
# 멀티스테이지 하나로 app과 mcp를 같이 만든다 (SDD 6.2). 둘은 같은 코드를 쓰고 실행 명령만 다르다.
FROM python:3.12-slim AS base

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# searoute는 항로망 데이터를 패키지에 들고 있어 빌드 도구가 필요 없다 (2026-09-23 확인)
COPY backend/ ./backend/
COPY mcp_server/ ./mcp_server/
COPY worker/ ./worker/
COPY skills/ ./skills/
COPY scripts/ ./scripts/
COPY evals/ ./evals/

FROM base AS app
EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS mcp
EXPOSE 8001
ENV MCP_HOST=0.0.0.0 MCP_PORT=8001
CMD ["python", "-m", "mcp_server.server"]

# 수집 워커 (D1, SDD 6.2). 스케줄러는 기본 꺼짐(WORKER_SCHEDULE=off). 한 번 돌리려면
# docker compose run --rm worker python -m worker.run --once
FROM base AS worker
CMD ["python", "-m", "worker.run"]
