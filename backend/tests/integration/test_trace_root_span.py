"""요청 루트 span과 외부 호출 span 테스트 (SDD 5.11). 키 없이 돈다: 가짜 Langfuse 클라이언트로 확인한다.

확인하는 것:
  - 키가 없으면 아무것도 안 하고 동작이 그대로다 (루트 span·외부 span 모두 no-op)
  - 가짜 클라이언트로 루트 span이 만들어지고, 그 안의 generation·tool 관측이 루트를 부모로 받는다
  - 루트 span의 metadata(method·path·status·latency·request_id), 오류 상태
  - 라우터 /api/chat, /api/chat/stream이 루트 span을 열고 닫는다 (스트림은 처리가 끝날 때 닫힌다)
  - UNI-PASS·해수부·OCR 구간이 같은 루트 아래 tool 관측으로 남는다 (재시도 횟수 포함)
"""
import asyncio
import threading

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.clients import retry
from backend.app.main import app
from backend.app.observability import langfuse as tracing
from backend.app.observability.logging import request_id_var
from backend.app.routers import chat as chat_router
from backend.app.services.chat import chat as svc
from backend.app.services.judge import customs as customs_service


class FakeSpan:
    """Langfuse 관측 대신. 열릴 때의 인자와 update·end 결과를 모은다."""

    def __init__(self, n, name, as_type, trace_context, metadata):
        self.id = f"span{n}"
        self.trace_id = (trace_context or {}).get("trace_id") or f"trace{n}"
        self.name, self.as_type, self.trace_context = name, as_type, trace_context
        self.fields = {"metadata": dict(metadata or {})}
        self.ended = threading.Event()

    @property
    def parent_id(self):
        return (self.trace_context or {}).get("parent_span_id")

    def update(self, **fields):
        self.fields.update(fields)

    def end(self):
        self.ended.set()


class FakeClient:
    def __init__(self):
        self.spans: list[FakeSpan] = []

    def create_trace_id(self, seed=None):
        return f"trace-{seed}"

    def start_observation(self, *, name, as_type, input=None, trace_context=None, metadata=None, **extra):
        span = FakeSpan(len(self.spans) + 1, name, as_type, trace_context, metadata)
        self.spans.append(span)
        return span

    def named(self, name):
        return [s for s in self.spans if s.name == name]


@pytest.fixture
def fake(monkeypatch):
    """키가 있는 것처럼 보이게 하고 langfuse.get_client를 가짜로 바꾼다."""
    import langfuse

    client = FakeClient()
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setattr(langfuse, "get_client", lambda: client)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    return client


@pytest.fixture
def no_keys(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)


# ── (a) 키가 없을 때 ──

def test_no_keys_spans_are_noop(no_keys):
    with tracing.request_span("/api/agent") as root:
        with tracing.tool_span("unipass:fetch", {"bl": "TE****01"}) as tool:
            tool.metadata["attempts"] = 1
        root.status = 404
    # 예외도 그대로 올라온다 (삼키지 않는다)
    with pytest.raises(ValueError):
        with tracing.request_span("/api/agent"):
            raise ValueError("x")


def test_no_keys_chat_route_unchanged(no_keys, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setattr(svc, "handle", lambda *a, **k: svc.ChatResult(kind="message", reply="안녕하세요"))
    with TestClient(app) as client:
        r = client.post("/api/chat", json={"message": "안녕", "session_id": "s1"})
    assert r.status_code == 200 and r.json()["reply"] == "안녕하세요"


# ── (b) 루트 span과 자식 ──

def test_children_attach_to_root(fake):
    token = request_id_var.set("req-1")
    try:
        with tracing.request_span("/api/agent") as root:
            gen = tracing.start_generation("marvia-judge", "{}")
            tool = tracing.start_tool("mcp:vessel", {})
            with tracing.tool_span("unipass:fetch", {"bl": "TE****01"}) as t:
                t.metadata["attempts"] = 2
            root.status = 200
        after = tracing.start_tool("outside", {})  # 루트가 끝난 뒤에는 부모가 없다
    finally:
        request_id_var.reset(token)
    rootspan = fake.named("request:/api/agent")[0]
    assert rootspan.trace_context == {"trace_id": "trace-req-1"}  # 요청 ID가 씨앗인 트레이스, 부모 없음
    for child in (gen, tool, fake.named("unipass:fetch")[0], ):
        assert child.parent_id == rootspan.id
        assert child.trace_id == rootspan.trace_id
    assert after.parent_id is None
    meta = rootspan.fields["metadata"]
    assert meta["method"] == "POST" and meta["path"] == "/api/agent" and meta["status"] == 200
    assert meta["request_id"] == "req-1" and meta["latency_ms"] >= 0
    assert rootspan.ended.is_set()
    assert fake.named("unipass:fetch")[0].fields["metadata"]["attempts"] == 2
    assert "input" not in rootspan.fields  # 루트에는 입력·출력을 싣지 않는다


def test_root_records_http_error_status(fake):
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        with tracing.request_span("/api/chat"):
            raise HTTPException(status_code=429, detail="limit")
    with pytest.raises(RuntimeError):
        with tracing.request_span("/api/chat"):
            raise RuntimeError("boom")
    a, b = fake.named("request:/api/chat")
    assert a.fields["metadata"]["status"] == 429 and "level" not in a.fields and a.ended.is_set()
    assert b.fields["metadata"]["status"] == 500 and b.fields["level"] == "ERROR" and b.ended.is_set()


def test_chat_route_opens_root_and_children_nest(fake, monkeypatch):
    def fake_handle(*a, **k):
        tracing.start_tool("mcp:x", {})  # 서비스 안에서 여는 관측
        return svc.ChatResult(kind="message", reply="안녕")
    monkeypatch.setattr(svc, "handle", fake_handle)
    with TestClient(app) as client:
        assert client.post("/api/chat", json={"message": "안녕", "session_id": "s1"}).status_code == 200
    root = fake.named("request:/api/chat")[0]
    assert root.ended.is_set() and root.fields["metadata"]["status"] == 200
    assert fake.named("mcp:x")[0].parent_id == root.id


def test_tracing_failure_never_blocks_request(monkeypatch):
    """Langfuse 쪽이 터져도 요청은 정상이다."""
    import langfuse

    def broken():
        raise RuntimeError("langfuse down")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    monkeypatch.setattr(langfuse, "get_client", broken)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setattr(svc, "handle", lambda *a, **k: svc.ChatResult(kind="message", reply="ok"))
    with TestClient(app) as client:
        assert client.post("/api/chat", json={"message": "안녕", "session_id": "s1"}).status_code == 200


# ── (c) 스트리밍 ──

def test_stream_ends_root_span(fake, monkeypatch):
    monkeypatch.setattr(svc, "handle", lambda *a, **k: (tracing.start_tool("mcp:y", {}),
                                                         svc.ChatResult(kind="message", reply="안녕"))[1])
    with TestClient(app) as client:
        r = client.post("/api/chat/stream", json={"message": "안녕", "session_id": "s1"})
        assert "event: result" in r.text
    root = fake.named("request:/api/chat/stream")[0]
    assert root.ended.is_set()  # 스트림 끝 표시는 span이 닫힌 뒤에 나간다
    assert root.fields["metadata"]["status"] == 200
    assert fake.named("mcp:y")[0].parent_id == root.id


def test_stream_ends_root_span_on_error(fake, monkeypatch):
    def crash(*a, **k):
        raise RuntimeError("비밀")
    monkeypatch.setattr(svc, "handle", crash)
    with TestClient(app) as client:
        r = client.post("/api/chat/stream", json={"message": "안녕", "session_id": "s1"})
        assert "event: error" in r.text and "비밀" not in r.text
    root = fake.named("request:/api/chat/stream")[0]
    assert root.ended.is_set()
    assert root.fields["metadata"]["status"] == 500 and root.fields["level"] == "ERROR"
    assert "비밀" not in str(root.fields)  # 예외 메시지는 올리지 않는다 (종류만)


def test_stream_ends_root_span_after_client_disconnect(fake, monkeypatch):
    """클라이언트가 응답을 안 읽고 끊어도 처리 스레드가 끝나면 span이 닫힌다."""
    release = threading.Event()

    def slow(*a, **k):
        release.wait(5)
        return svc.ChatResult(kind="message", reply="늦은 답")
    monkeypatch.setattr(svc, "handle", slow)
    monkeypatch.setattr(chat_router, "PING_SEC", 0.05)
    # 제너레이터를 직접 받아 첫 조각만 읽고 닫는다 (연결이 끊긴 것과 같다)
    resp = chat_router.chat_stream(chat_router.ChatRequest(message="안녕", session_id="s1"), None)
    gen = resp.body_iterator

    async def read_one_then_close():
        assert await gen.__anext__() == ": ping\n\n"
        await gen.aclose()
    asyncio.run(read_one_then_close())
    root = fake.named("request:/api/chat/stream")[0]
    assert not root.ended.is_set()  # 처리가 아직 도는 동안은 열려 있다
    release.set()
    assert root.ended.wait(5)


# ── 외부 호출 구간 ──

def _unipass_client(handler):
    return customs_service.UnipassClient(key="k", transport=httpx.MockTransport(handler))


XML_EMPTY = "<cargCsclPrgsInfoQryRtnVo><tCnt>0</tCnt></cargCsclPrgsInfoQryRtnVo>"


def test_unipass_span_records_retries(fake, monkeypatch):
    monkeypatch.setattr(retry, "BACKOFF_SEC", 0)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, text=XML_EMPTY)
    with tracing.request_span("/api/agent"):
        assert _unipass_client(handler).fetch("TESTBL01") is None
    root = fake.named("request:/api/agent")[0]
    span = fake.named("unipass:fetch")[0]
    assert span.parent_id == root.id and span.as_type == "tool"
    meta = span.fields["metadata"]
    assert meta["attempts"] == 3 and meta["retries"] == 2 and meta["found"] is False and "latency_ms" in meta
    assert "level" not in span.fields and span.ended.is_set()


def test_unipass_span_records_failure(fake, monkeypatch):
    monkeypatch.setattr(retry, "BACKOFF_SEC", 0)

    def handler(request):
        raise httpx.ReadTimeout("느림")
    with pytest.raises(customs_service.CustomsError):
        _unipass_client(handler).fetch("TESTBL01")
    span = fake.named("unipass:fetch")[0]
    assert span.fields["level"] == "ERROR" and span.fields["status_message"] == "timeout"
    assert span.fields["metadata"]["attempts"] == 3
    assert "TESTBL01" not in str(span.fields)  # B/L 원문은 올리지 않는다 (가린 값만)


def test_mof_arrivals_span(fake, monkeypatch):
    class FakeMof:
        def sailing_plans_all(self, start, end):
            return [1, 2, 3]

        def close(self):
            pass
    monkeypatch.setattr(svc, "MofClient", lambda **k: FakeMof())
    svc._plans_cache.clear()
    assert svc._arrivals(3) == [1, 2, 3]
    span = fake.named("mof:sailing_plans_all")[0]
    assert span.fields["metadata"]["count"] == 3 and span.ended.is_set()
    svc._arrivals(3)  # 캐시 적중이면 해수부를 안 부르니 span도 안 늘어난다
    assert len(fake.named("mof:sailing_plans_all")) == 1
    svc._plans_cache.clear()


def test_ocr_span(fake):
    import io

    from PIL import Image

    from backend.app.services.chat import doc_ocr

    class Engine:  # OCR 엔진 대신. 줄 하나를 돌려준다
        def __call__(self, img):
            return [], None
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(buf, "PNG")
    with tracing.request_span("/api/document"):
        try:
            doc_ocr.read_lines(buf.getvalue(), engine=Engine())
        except Exception:  # 가짜 엔진 모양이 달라 실패해도 span은 남아야 한다
            pass
    root = fake.named("request:/api/document")[0]
    span = fake.named("ocr:read")[0]
    assert span.parent_id == root.id and span.ended.is_set()
