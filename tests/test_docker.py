"""이미지·compose 경계 시험 (계획 4b Task 8·9, C8·C9). 도커 없이 파일만 읽는다."""

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILES = [ROOT / "Dockerfile", ROOT / "web" / "Dockerfile", ROOT / "web" / "e2e.Dockerfile"]
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
        "e2e/fake_api.py",
    }


def test_every_image_is_pinned_by_digest():
    # [왜] 태그는 옮겨질 수 있다. 같은 커밋이 다른 날 다른 이미지로 빌드되지 않게 한다
    stages: set[str] = set()
    refs: list[str] = []
    for path in DOCKERFILES:
        for line in path.read_text().splitlines():
            if line[:5].upper() == "FROM ":  # [왜] 소문자 from도 같은 줄이다
                parts = line.split()
                if parts[1] not in stages:  # [왜] "FROM base AS e2e"의 base는 앞 단계 이름이다
                    refs.append(parts[1])
                if len(parts) >= 4 and parts[2].upper() == "AS":
                    stages.add(parts[3])
    assert refs and all(PINNED.search(ref) for ref in refs), refs
    # [왜] build와 image가 함께 있으면 image는 만든 이미지의 이름(:local)이다. 그 밖의 이미지는 고정한다
    images = [
        s["image"] for s in COMPOSE["services"].values() if "image" in s and not s["image"].endswith(":local")
    ]
    assert images and all(PINNED.search(image) for image in images), images


def test_published_ports_open_on_this_computer_only():
    # [왜] 포트만 적으면 모든 주소에 열려 같은 망의 다른 기기가 기본 비밀번호로 DB·그래프에 붙는다
    ports = [(name, port) for name, s in COMPOSE["services"].items() for port in s.get("ports", [])]
    assert ports  # [왜] 공개 포트가 하나도 없으면 아래 검사가 아무것도 보지 않는다
    for name, port in ports:
        assert port.startswith("127.0.0.1:"), (name, port)


def test_the_e2e_network_cannot_reach_outside_and_the_runtime_image_has_no_fake_api():
    assert COMPOSE["networks"]["e2e"]["internal"] is True
    for name in ("api-e2e", "web-e2e", "playwright"):
        assert COMPOSE["services"][name]["networks"] == ["e2e"], name
    dockerfile = (ROOT / "Dockerfile").read_text()
    runtime = dockerfile.split("FROM base AS runtime")[1]
    assert "fake_api" not in runtime  # 가짜 API는 e2e 단계에만 복사한다
    assert dockerfile.rstrip().endswith('CMD ["python", "-m", "marvia.server"]')  # 기본(마지막) 단계가 운영


def test_the_playwright_image_matches_the_test_package_version():
    # [왜] 이미지 태그와 @playwright/test 버전이 다르면 브라우저 실행 파일을 찾지 못한다
    package = json.loads((ROOT / "web" / "package.json").read_text())
    version = package["devDependencies"]["@playwright/test"]
    image = next(
        line.split()[1]
        for line in (ROOT / "web" / "e2e.Dockerfile").read_text().splitlines()
        if line.startswith("FROM ")
    )
    assert image.startswith(f"mcr.microsoft.com/playwright:v{version}-noble@sha256:")
    # [왜] @axe-core/playwright는 playwright-core를 아무 버전이나 받는다. 같은 버전으로 묶지 않으면
    #      npm이 최신판을 따로 깔아 타입이 둘로 갈린다(11-07 실측: 1.65.0과 1.64.1, next build 실패)
    assert package["devDependencies"]["playwright-core"] == version
    # [왜] 정확한 버전만 쓴다(save-exact). ^·~가 붙으면 잠금 파일 밖에서 버전이 바뀔 수 있다
    versions = {**package["dependencies"], **package["devDependencies"]}
    assert all(re.fullmatch(r"\d+\.\d+\.\d+", v) for v in versions.values()), versions


def test_prepare_db_twice_makes_the_tables_the_server_needs_and_the_second_run_changes_nothing(
    db, monkeypatch, tmp_path
):
    # [왜] 표 준비는 여러 번 돌려도 같아야 하고 서버가 쓰는 표가 모두 있어야 한다. 시험용 스키마에서만 돈다
    from cryptography.fernet import Fernet
    from psycopg.conninfo import make_conninfo

    from marvia import prepare_db
    from marvia.config import Settings

    schema = db.execute("SELECT current_schema()").fetchone()[0]
    db.commit()
    monkeypatch.chdir(tmp_path)  # [왜] 저장소의 .env를 읽지 않게 빈 폴더에서 돈다
    monkeypatch.setenv(
        "MARVIA_DATABASE_URL",
        make_conninfo(Settings(_env_file=None).database_url, options=f"-c search_path={schema},public"),
    )
    monkeypatch.setenv("MARVIA_DATA_KEY", Fernet.generate_key().decode())

    def snapshot() -> tuple:
        tables = db.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s ORDER BY 1", (schema,)
        ).fetchall()
        versions = [
            db.execute(f"SELECT count(*) FROM {t}").fetchone()
            for t in ("checkpoint_migrations", "store_migrations")
        ]
        db.commit()
        return tables, versions

    prepare_db.main()
    first = snapshot()
    names = {row[0] for row in first[0]}
    assert {"checkpoints", "checkpoint_blobs", "checkpoint_writes", "store", "watches"} <= names
    assert all(count[0] > 0 for count in first[1])
    prepare_db.main()
    assert snapshot() == first
