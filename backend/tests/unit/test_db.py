"""DB 모듈 중 연결 없이 확인할 수 있는 부분. 실제 테이블 적용은 docker의 postgres로 확인한다."""
from backend.app.db import MIGRATIONS_DIR, plain_url


def test_plain_url_strips_driver_suffix():
    # compose의 api가 쓰는 asyncpg 주소를 워커(psycopg)도 읽을 수 있어야 한다
    assert plain_url("postgresql+asyncpg://app:app@db:5432/app") == "postgresql://app:app@db:5432/app"
    assert plain_url("postgresql://app:app@db:5432/app") == "postgresql://app:app@db:5432/app"


def test_migrations_are_ordered_sql_files():
    names = [p.name for p in sorted(MIGRATIONS_DIR.glob("*.sql"))]
    assert names and names[0].startswith("001_")
