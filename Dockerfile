# syntax=docker/dockerfile:1
# Marvia API 이미지 (설계 13절: 멀티스테이지, non-root, 계획 4b Task 8).
# 단계: build(uv로 .venv) → base(실행에 필요한 것만, uid 10001) → runtime(운영, 마지막 단계)
# [주의] 이미지는 digest로 고정한다. 태그는 옮겨질 수 있다. 맥(arm64)에서도 --platform linux/amd64로 한 번 빌드해 본다(Cloud Run)
FROM ghcr.io/astral-sh/uv:0.9.30@sha256:538e0b39736e7feae937a65983e49d2ab75e1559d35041f9878b7b7e51de91e4 AS uv

FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS build
COPY --from=uv /uv /bin/uv
# [왜] 바이트코드는 .venv의 패키지만 미리 만든다(UV_COMPILE_BYTECODE). 편집 모드의 /app/src는 시작할 때 메모리에서
#      컴파일한다. /app은 읽기 전용(주인 root)이라 쓰지 못해도 동작한다. 이미지의 파이썬만 쓴다(내려받지 않음)
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0 UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
# [왜] 의존성 층을 소스와 나눠, 코드만 바뀌면 이 층을 다시 쓰지 않는다
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-install-project
COPY src ./src
COPY rules ./rules
COPY prompts ./prompts
COPY migrations ./migrations
COPY fixtures/unipass ./fixtures/unipass
COPY corpus/graph ./corpus/graph
# [주의] 프로젝트는 편집 모드(.pth가 /app/src를 가리킴)로 둔다. rules·prompts를 소스 트리 기준으로 찾는다(Path(__file__))
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev

FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS base
RUN useradd --uid 10001 --create-home --home-dir /home/marvia marvia
WORKDIR /app
# [왜] 파일 주인은 root로 두고 실행은 10001로 한다. 실행 중에 코드·규칙을 바꿀 수 없다
COPY --from=build /app /app
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 HOME=/home/marvia PORT=8080 MARVIA_HOST=0.0.0.0
# [왜] 서버 기본은 127.0.0.1이다. 컨테이너 안에서만 모든 주소에서 듣고, 바깥 쪽 포트는 compose가 127.0.0.1로만 연다 (R-074)
USER 10001
EXPOSE 8080
# [왜] slim 이미지에는 curl이 없다. 파이썬 표준 라이브러리로 /health를 본다
HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ['PORT'], timeout=2)"]

FROM base AS runtime
CMD ["python", "-m", "marvia.server"]
