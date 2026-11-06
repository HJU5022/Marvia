"""CI에서는 DB에 닿지 못하면 DB 시험을 건너뛰지 않고 실패한다 (MARVIA_REQUIRE_DB). DB 없이 도는 시험."""

import pytest
from db_required import db_unreachable


def test_db_unreachable_skips_locally(monkeypatch):
    monkeypatch.delenv("MARVIA_REQUIRE_DB", raising=False)
    with pytest.raises(pytest.skip.Exception):
        db_unreachable()


def test_db_unreachable_fails_when_the_db_is_required(monkeypatch):
    monkeypatch.setenv("MARVIA_REQUIRE_DB", "1")
    with pytest.raises(pytest.fail.Exception):
        db_unreachable()
