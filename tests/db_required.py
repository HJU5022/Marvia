"""DB에 닿지 못했을 때 건너뛸지 실패할지 정한다. tests/conftest.py의 DB 준비물이 쓴다."""

import os

import pytest


def db_unreachable():
    """DB에 닿지 못했을 때: 로컬은 건너뛰고, MARVIA_REQUIRE_DB=1(CI)이면 실패한다."""
    # [왜] CI에서 Postgres가 안 떠도 DB 시험이 조용히 건너뛰어져 초록불이 되는 일을 막는다
    msg = "로컬 Postgres가 꺼져 있음 (docker compose up -d db)"
    if os.environ.get("MARVIA_REQUIRE_DB") == "1":
        pytest.fail(msg)
    pytest.skip(msg)
