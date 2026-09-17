# 필수 조건 2 — 채점자가 `docker compose up` 한 줄로 띄울 수 있어야 합니다.
FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
# skills/는 규칙값 문서(domain/rules.py가 읽음), mcp_server/는 /mcp 마운트. SDD 1절: 빌드 컨텍스트가 루트인 이유
COPY skills/ ./skills/
COPY mcp_server/ ./mcp_server/

EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
