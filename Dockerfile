# Marvia API 이미지 (설계 13절: 멀티스테이지, non-root, 계획 4b Task 8).
# 단계: build(uv로 .venv) → base(실행에 필요한 것만, uid 10001) → e2e(가짜 API, 화면 시험용) / runtime(운영) / runtime-cli(임시)
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

FROM base AS e2e
COPY e2e/fake_api.py /app/e2e/fake_api.py
# [왜] 배 식별 화면 시험이 쓰는 재생 응답(가공값)이다. 운영 이미지에는 넣지 않는다 (계획 8b)
COPY fixtures/mof /app/fixtures/mof
COPY fixtures/shipfinder /app/fixtures/shipfinder
CMD ["python", "/app/e2e/fake_api.py"]

FROM base AS runtime
CMD ["python", "-m", "marvia.server"]

# [임시] API 잔액이 없을 때 배포 서버가 Claude Code CLI로 모델을 부르는 이미지(MARVIA_LLM_VIA=cli, docs/deploy.md).
# runtime은 그대로 두고 그 위에 Claude Code 네이티브 바이너리만 더한다. 운영 이미지 크기 상한 때문에 runtime을 건드리지 않는다
# [주의] 판 번호와 sha256은 공식 설치 스크립트(https://claude.ai/install.sh)가 쓰는 곳에서 11-24에 확인했다.
#        내려받는 곳 https://downloads.claude.ai/claude-code-releases/<판>/<플랫폼>/claude,
#        체크섬 https://downloads.claude.ai/claude-code-releases/2.1.328/manifest.json 의 platforms.linux-x64.checksum.
#        판을 올릴 때는 두 값을 함께 바꾼다. ADD가 sha256이 다르면 빌드를 멈춘다
FROM runtime AS runtime-cli
ADD --chmod=0755 --checksum=sha256:a982d38030b97e750848add2cbb2df6d9a70d5544a22ca9b216a349ba25865e8 \
    https://downloads.claude.ai/claude-code-releases/2.1.328/linux-x64/claude /usr/local/bin/claude
# [왜] Cloud Run의 쓰기 가능한 파일시스템은 메모리다. CLI가 HOME 아래로 새 판(약 373MB)을 받으면 인스턴스 메모리가 줄어든다.
#      이 변수는 자동 갱신만 끈다(측정 때와 같게 기능 플래그 가져오기는 그대로 둔다). 이름과 뜻은 Claude Code 공식 문서(환경 변수 표)
#      https://code.claude.com/docs/en/env-vars 에서 11-24에 확인했다. 자식 프로세스까지 가게 rules/agent.yaml llm.cli_env에도 적는다
ENV DISABLE_AUTOUPDATER=1
# [왜] 바이너리는 root 소유로 두고 실행은 10001로 한다. 빌드 중에 돌려 보아 라이브러리가 모자라면 여기서 실패한다
USER 10001
RUN claude --version

# [왜] 마지막 단계는 늘 운영 이미지다. --target 없이 빌드해도 CLI 이미지가 나오지 않는다(tests/test_docker.py)
FROM runtime
CMD ["python", "-m", "marvia.server"]
