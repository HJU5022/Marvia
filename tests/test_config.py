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


def test_model_defaults(monkeypatch):
    monkeypatch.delenv("MARVIA_CHAT_MODEL", raising=False)
    settings = Settings(_env_file=None)
    assert settings.chat_model == "claude-haiku-5-5"
    assert settings.embed_dim == 1024


def test_key_is_hidden_when_printed(monkeypatch):
    # [왜] 설정 객체를 실수로 print해도 키가 화면·로그에 나오지 않아야 한다
    monkeypatch.setenv("MARVIA_ANTHROPIC_API_KEY", "sk-test-not-real")
    settings = Settings(_env_file=None)
    assert "sk-test-not-real" not in repr(settings)
    assert settings.anthropic_api_key.get_secret_value() == "sk-test-not-real"
