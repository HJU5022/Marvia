"""A5 구조화 로그 테스트."""
import json
import logging

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.observability.logging import JsonFormatter, current_request_id, set_llm_usage, setup_logging


def test_health_request_logs_one_json_line(caplog):
    with caplog.at_level(logging.INFO, logger="marvia.request"):
        with TestClient(app) as client:
            response = client.get("/health")

    assert response.status_code == 200
    record = next(r for r in caplog.records if r.name == "marvia.request")
    assert record.path == "/health" and record.method == "GET" and record.status == 200
    assert record.latency_ms >= 0 and record.request_id


def test_request_id_is_echoed_back():
    with TestClient(app) as client:
        response = client.get("/health", headers={"x-request-id": "given-id-123"})
    assert response.headers["x-request-id"] == "given-id-123"


def test_request_id_is_generated_when_missing():
    with TestClient(app) as client:
        first = client.get("/health").headers["x-request-id"]
        second = client.get("/health").headers["x-request-id"]
    assert first and second and first != second


def test_json_formatter_keeps_only_known_fields():
    record = logging.LogRecord("marvia.request", logging.INFO, "x", 1, "request", None, None)
    record.request_id = "abc"
    record.path = "/api/agent"
    record.status = 200
    record.latency_ms = 12.3
    record.secret = "무시돼야 한다"

    payload = json.loads(JsonFormatter().format(record))
    assert payload["request_id"] == "abc" and payload["path"] == "/api/agent"
    assert "secret" not in payload


def test_llm_usage_is_attached_to_log(caplog):
    """LLM을 부른 요청에는 모델과 토큰 수가 붙는다."""

    @app.get("/test-llm-usage")
    def _endpoint() -> dict:
        set_llm_usage("anthropic/claude-sonnet-5", tokens_in=100, tokens_out=20)
        return {"request_id": current_request_id()}

    with caplog.at_level(logging.INFO, logger="marvia.request"):
        with TestClient(app) as client:
            body = client.get("/test-llm-usage").json()

    record = next(r for r in caplog.records if getattr(r, "path", "") == "/test-llm-usage")
    assert record.model == "anthropic/claude-sonnet-5"
    assert (record.tokens_in, record.tokens_out) == (100, 20)
    assert body["request_id"] == record.request_id


def test_http_client_request_urls_are_not_logged(capsys):
    """외부 API 주소에는 키(crkyCn·serviceKey·key)와 B/L 번호가 들어 있다. httpx가 INFO로 주소 전체를
    남기면 로그에 그대로 쌓인다(실제 B/L 호출에서 발견). 주소를 남기는 로거는 WARNING 이상만 남긴다."""
    import httpx

    setup_logging()

    def handler(request):
        return httpx.Response(200, text="ok")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        client.get("https://example.test/api?serviceKey=SECRET-KEY-123&hblNo=REALBL0001")

    out = capsys.readouterr().out
    assert "SECRET-KEY-123" not in out and "REALBL0001" not in out


def test_failure_line_carries_stage_and_error():
    """D6 에러 로깅 한 줄이 JSON에 stage·error로 실린다 (Cloud Run 로그에서 필드로 검색)."""
    record = logging.LogRecord("marvia.failure", logging.WARNING, "x", 1, "failure", None, None)
    record.request_id = "abc"
    record.stage = "customs"
    record.error = "timeout"

    payload = json.loads(JsonFormatter().format(record))
    assert payload == {"level": "WARNING", "message": "failure", "request_id": "abc",
                       "stage": "customs", "error": "timeout"}


def test_failure_message_is_readable_without_json(caplog):
    """JSON 핸들러가 없는 터미널(평가 실행기)에서도 무엇이 실패했는지 보인다. 전에는 "failure"만 찍혔다."""
    from backend.app.observability.logging import log_failure

    with caplog.at_level(logging.WARNING, logger="marvia.failure"):
        log_failure("customs", "timeout")

    assert caplog.records[-1].getMessage() == "failure stage=customs error=timeout"
