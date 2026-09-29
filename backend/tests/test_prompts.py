"""D4 프롬프트 가져오기 테스트. Langfuse 없이 돈다."""
import sys

from backend.app.observability.langfuse import LOCAL_VERSION, get_prompt


def test_without_keys_uses_local_file(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    prompt = get_prompt("marvia-judge")
    assert prompt.version == LOCAL_VERSION
    assert "fine" in prompt.text and "act" in prompt.text


def test_langfuse_failure_falls_back_to_local_file(monkeypatch):
    """키가 있어도 Langfuse가 안 되면(여기선 미설치로 흉내) 판정을 막지 않고 로컬 파일을 쓴다."""
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setitem(sys.modules, "langfuse", None)  # import하면 ImportError가 나게 한다

    assert get_prompt("marvia-judge").version == LOCAL_VERSION


def test_langfuse_fallback_is_logged(monkeypatch, caplog):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setitem(sys.modules, "langfuse", None)

    with caplog.at_level("WARNING", logger="marvia.failure"):
        get_prompt("marvia-judge")

    logged = [(r.stage, r.error) for r in caplog.records if r.name == "marvia.failure"]
    assert logged == [("langfuse_prompt", "ModuleNotFoundError fallback=local_file")]


def test_flush_without_keys_does_nothing(monkeypatch):
    """키가 없으면 아무것도 안 한다. 서버 종료를 막지 않는다."""
    from backend.app.observability.langfuse import flush

    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    flush()


def test_flush_failure_is_logged_not_raised(monkeypatch, caplog):
    """Langfuse가 안 되면 종료를 막지 않고 로그만 남긴다."""
    from backend.app.observability.langfuse import flush

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setitem(sys.modules, "langfuse", None)
    with caplog.at_level("WARNING", logger="marvia.failure"):
        flush()
    assert [(r.stage, r.error) for r in caplog.records if r.name == "marvia.failure"] == [("langfuse_flush", "ModuleNotFoundError")]
