"""docker-compose.yml 경계 시험. 키·도커 없이 파일만 읽는다."""

from pathlib import Path

import yaml

COMPOSE = yaml.safe_load(
    (Path(__file__).resolve().parents[1] / "docker-compose.yml").read_text(encoding="utf-8")
)


def test_neo4j_ports_are_published_on_this_computer_only():
    # [왜] 포트만 적으면 모든 주소에 열려 같은 망의 다른 기기가 비밀번호 기본값으로 그래프에 붙을 수 있다
    for name, service in COMPOSE["services"].items():
        if name.startswith("neo4j"):
            assert service["ports"] and all(p.startswith("127.0.0.1:") for p in service["ports"]), name


def test_the_test_neo4j_is_separate_loopback_only_and_keeps_no_data():
    # [왜] 시험이 개발 그래프를 지운 사고 뒤, 시험은 따로 띄운 Neo4j만 쓴다. 데이터는 남기지 않는다
    dev, test = COMPOSE["services"]["neo4j"], COMPOSE["services"]["neo4j-test"]
    assert test["image"] == dev["image"]  # 같은 고정 이미지
    assert test["ports"] == ["127.0.0.1:7689:7687"]  # bolt만. 브라우저 문은 열지 않는다
    assert "volumes" not in test and test["tmpfs"]
