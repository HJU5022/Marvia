# 필수 조건 2 — 채점자가 `docker compose up` 한 줄로 띄울 수 있어야 합니다.
FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
# skills/는 규칙값 문서(domain/rules.py가 읽음), mcp_server/는 /mcp 마운트. SDD 1절: 빌드 컨텍스트가 루트인 이유
COPY skills/ ./skills/
COPY mcp_server/ ./mcp_server/

# SDD 1절: 빌드 시 HF에서 GGUF를 받아 이미지에 넣는다 (git, LFS 미사용).
# 공개 저장소라 토큰 없이 받는다. 모델을 바꾸면 SDD 1절·9절과 이 ARG를 함께 고친다.
ARG HF_REPO=kimseunguk/converge-slot-extractor
ARG GGUF_FILE=kanana_2.1b-Q4_K_M.gguf
RUN pip install --no-cache-dir huggingface_hub && \
    python -c "from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='${HF_REPO}', filename='${GGUF_FILE}', local_dir='/app/backend/app/models')" && \
    pip uninstall -y huggingface_hub && \
    ls -la /app/backend/app/models/

EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
