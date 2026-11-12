"""마이그레이션과 시험 스키마 지킴 시험.

[왜] migrations/ 폴더가 없는 나무에서 시험을 돌리면 마이그레이션이 아무것도 안 돌리고 끝나 시험 스키마가 비고,
     이름만 쓴 corpus_units가 public(개발 색인)으로 풀려 시험 줄이 개발 색인에 들어갔다 (11-13 확인).
"""

import pytest
from db_required import require_test_tables

from marvia import db as db_module
from marvia.db import apply_migrations


def test_apply_migrations_fails_when_it_finds_no_migration_file(monkeypatch, tmp_path):
    monkeypatch.setattr(db_module, "MIGRATIONS", tmp_path)  # 마이그레이션 파일이 하나도 없는 폴더

    class NoDatabase:
        def execute(self, *args):
            raise AssertionError("파일이 없으면 DB에 닿기 전에 멈춰야 한다")

        commit = execute

    with pytest.raises(RuntimeError, match="마이그레이션 파일이 없다"):
        apply_migrations(NoDatabase())  # type: ignore[arg-type]


def test_the_db_fixture_fails_when_the_test_schema_has_no_tables(db):
    # 준비물(db)이 만든 시험 스키마에는 표가 있다
    require_test_tables(db, db.execute("SELECT current_schema()").fetchone()[0])
    # [왜] 표가 없는 시험 스키마로 시험이 돌면 이름만 쓴 corpus_units가 public(개발 색인)으로 풀린다.
    #      건너뛰지 않고 그 자리에서 실패해야 개발 색인에 시험 줄이 들어가지 않는다
    db.execute("CREATE SCHEMA marvia_test_empty")
    try:
        with pytest.raises(pytest.fail.Exception, match="corpus_units"):
            require_test_tables(db, "marvia_test_empty")
    finally:
        db.execute("DROP SCHEMA marvia_test_empty CASCADE")
