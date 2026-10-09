# 필수 조건 2. 채점자가 `docker compose up` 한 줄로 띄울 수 있어야 한다.
# 멀티스테이지 하나로 app과 mcp를 같이 만든다 (SDD 6.2). 둘은 같은 코드를 쓰고 실행 명령만 다르다.
FROM python:3.12-slim AS base

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY backend/requirements.txt backend/requirements.lock.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt -c backend/requirements.lock.txt

# searoute는 항로망 데이터를 패키지에 들고 있어 빌드 도구가 필요 없다 (2026-09-23 확인)
COPY backend/ ./backend/
COPY mcp_server/ ./mcp_server/
COPY worker/ ./worker/
COPY skills/ ./skills/
COPY scripts/ ./scripts/
COPY evals/ ./evals/

# 서류 사진 OCR은 api(app 스테이지)만 쓴다. OCR 패키지·시스템 라이브러리·모델을 base에 두면 worker 이미지까지
# 458MB → 1.28GB로 커져서 app 스테이지로 옮겼다 (결정 (a), backend/requirements-doc.txt)
FROM base AS app

# rapidocr가 설치하는 opencv-python은 slim 이미지에 없는 화면 라이브러리(libGL, glib)를 찾는다.
# 없으면 import cv2에서 죽는다 (서류 사진 OCR, docs/specs/document-extract.md)
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements-doc.txt ./backend/requirements-doc.txt
RUN pip install --no-cache-dir -r backend/requirements-doc.txt -c backend/requirements.lock.txt

# OCR 모델(약 18MB)을 빌드 때 받아 이미지에 넣는다. 안 하면 첫 요청이 인터넷에서 모델을 받느라 느리고,
# 네트워크가 막힌 곳에서는 실패한다. 엔진을 한 번 만들면 rapidocr가 패키지 폴더에 받아 둔다
RUN python -c "from backend.app.services.chat.doc_ocr import _get_engine; _get_engine()"

# 서비스가 MCP 도구를 자기 /mcp로 부른다 (backend/app/services/mcp_client.py). 포트는 아래 CMD의 8000과 같아야 한다.
# 이 값이 없으면(테스트·평가 실행기) 같은 프로세스 안의 MCP 서버에 메모리로 붙는다
ENV MCP_URL=http://127.0.0.1:8000/mcp
EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# 수집 워커 (D1, SDD 6.2). 스케줄러는 기본 꺼짐(WORKER_SCHEDULE=off). 한 번 돌리려면
# docker compose run --rm worker python -m worker.run --once
FROM base AS worker
CMD ["python", "-m", "worker.run"]
