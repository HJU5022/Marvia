"""이미지·compose 경계 시험 (계획 4b Task 8, C8). 도커 없이 파일만 읽는다."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILES = [ROOT / "Dockerfile", ROOT / "web" / "Dockerfile"]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
PINNED = re.compile(r"@sha256:[0-9a-f]{64}$")


def test_the_build_context_is_an_allow_list_without_secrets_or_real_data():
    # [왜] 저장소 루트에 .env(키), .local(실제 응답 저장본)이 있다. COPY 층에 들어가면 이미지에서 지울 수 없다
    lines = [line.strip() for line in (ROOT / ".dockerignore").read_text().splitlines()]
    rules = [line for line in lines if line and not line.startswith("#")]
    assert rules[0] == "*"  # 모두 막고 시작한다
    opened = {line[1:] for line in rules if line.startswith("!")}
    assert opened == {
        "pyproject.toml",
        "uv.lock",
        "src",
        "rules",
        "prompts",
        "migrations",
        "fixtures/unipass",
        "corpus/graph",
    }


def test_every_image_is_pinned_by_digest():
    # [왜] 태그는 옮겨질 수 있다. 같은 커밋이 다른 날 다른 이미지로 빌드되지 않게 한다
    stages: set[str] = set()
    refs: list[str] = []
    for path in DOCKERFILES:
        for line in path.read_text().splitlines():
            if line.startswith("FROM "):
                parts = line.split()
                if parts[1] not in stages:  # [왜] "FROM base AS e2e"의 base는 앞 단계 이름이다
                    refs.append(parts[1])
                if len(parts) >= 4 and parts[2].upper() == "AS":
                    stages.add(parts[3])
    assert refs and all(PINNED.search(ref) for ref in refs), refs
    images = [service["image"] for service in COMPOSE["services"].values() if "build" not in service]
    assert images and all(PINNED.search(image) for image in images), images


def test_published_ports_open_on_this_computer_only():
    # [왜] 포트만 적으면 모든 주소에 열려 같은 망의 다른 기기가 기본 비밀번호로 DB·그래프에 붙는다
    for name, service in COMPOSE["services"].items():
        for port in service.get("ports", []):
            assert port.startswith("127.0.0.1:"), (name, port)
