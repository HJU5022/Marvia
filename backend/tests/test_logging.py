"""A5 구조화 로그 테스트."""
import json
import logging

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.observability.logging import JsonFormatter, current_request_id, set_llm_usage


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
