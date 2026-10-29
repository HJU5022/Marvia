from marvia.config import Settings

LOCAL_DB = "postgresql://marvia:marvia@localhost:5433/marvia"


# [왜] monkeypatch는 이 테스트 동안만 환경 변수를 바꾸고, 끝나면 원래대로 되돌린다
# [왜] _env_file=None: 테스트는 루트 .env 파일을 읽지 않는다. 내 컴퓨터의 .env 내용에 따라 결과가 바뀌지 않게
def test_ignores_v1_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://v1-production")
    monkeypatch.delenv("MARVIA_DATABASE_URL", raising=False)
    assert Settings(_env_file=None).database_url == LOCAL_DB


def test_reads_prefixed_url(monkeypatch):
    monkeypatch.setenv("MARVIA_DATABASE_URL", "postgresql://x:y@localhost:5999/z")
    assert Settings(_env_file=None).database_url == "postgresql://x:y@localhost:5999/z"


def test_empty_value_uses_default(monkeypatch):
    # .env에 "MARVIA_DATABASE_URL="처럼 값 없이 적힌 경우
    monkeypatch.setenv("MARVIA_DATABASE_URL", "")
    assert Settings(_env_file=None).database_url == LOCAL_DB
