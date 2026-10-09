"""구조화 로그 (작업 A5).

요청 1건이 로그 한 줄이 된다. JSON으로 남겨야 배포 로그(Railway)에서 필드로 검색된다.
형식은 SDD 5.11: {request_id, path, model, tokens_in, tokens_out, latency_ms, status}.

model·tokens는 LLM을 부른 요청에만 붙는다. services/llm.py가 set_llm_usage()로 채우고,
미들웨어가 응답을 내보낼 때 같이 적는다. LLM을 안 부른 요청에서는 비어 있다.

B/L 번호와 키는 절대 로그에 넣지 않는다. B/L은 mask_bl()로 가린 값만 쓴다 (SDD 3.5, 7절).
"""
from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# 요청 하나 안에서만 유지되는 값들. 비동기로 여러 요청이 섞여도 서로 침범하지 않는다
request_id_var: ContextVar[str] = ContextVar("request_id", default="")
llm_usage_var: ContextVar[dict] = ContextVar("llm_usage", default={})
# 이 요청의 로그인 이메일 (auth.current_user가 채운다). 하루 토큰 한도의 운영자 예외 판단에 쓴다 (services/account/quota.py).
# 미들웨어가 요청마다 새 dict를 만든다. 요청 밖(스크립트·테스트)은 None이다
request_user_var: ContextVar[dict | None] = ContextVar("request_user", default=None)

logger = logging.getLogger("marvia.request")
failure_logger = logging.getLogger("marvia.failure")


class JsonFormatter(logging.Formatter):
    """로그 레코드를 JSON 한 줄로 만든다. extra로 넘긴 필드를 그대로 싣는다."""

    KEYS = ("request_id", "path", "method", "model", "tokens_in", "tokens_out", "latency_ms", "status",
            "stage", "error")

    def format(self, record: logging.LogRecord) -> str:
        payload = {"level": record.levelname, "message": record.getMessage()}
        for key in self.KEYS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False)


# 요청 주소를 INFO로 남기는 라이브러리 로거. httpx2는 fastapi TestClient가 쓴다
NOISY_URL_LOGGERS = ("httpx", "httpx2", "httpcore")


def setup_logging(level: int = logging.INFO) -> None:
    """루트 로거에 JSON 핸들러를 건다. 앱 기동 때 한 번 부른다."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # HTTP 클라이언트는 INFO로 요청 주소 전체를 남긴다. 외부 API 주소에는 키(UNI-PASS crkyCn,
    # 공공데이터 serviceKey, ShipFinder key)와 B/L 번호가 들어 있어 로그에 그대로 쌓인다
    # (실제 B/L 호출에서 발견, SDD 3.5 "로그에는 가린 번호만" 위반). 경고 이상만 남긴다.
    for name in NOISY_URL_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def set_llm_usage(model: str, tokens_in: int | None = None, tokens_out: int | None = None) -> None:
    """이 요청에서 쓴 모델과 토큰 수를 기록한다. services/llm.py가 부른다.

    변수를 새로 대입하지 않고 미들웨어가 만든 dict를 고친다. 동기 핸들러는 스레드풀에서 돌아
    컨텍스트가 복사되는데, 그때 새 대입은 미들웨어로 돌아오지 않고 dict 수정은 돌아온다.
    """
    llm_usage_var.get().update({"model": model, "tokens_in": tokens_in, "tokens_out": tokens_out})


def current_request_id() -> str:
    """지금 처리 중인 요청의 ID. Langfuse 트레이스와 맞출 때 쓴다."""
    return request_id_var.get()


def log_failure(stage: str, error: str) -> None:
    """어디서(stage) 무엇이(error) 실패했는지 WARNING 한 줄을 남긴다 (D6 에러 로깅).

    라우터는 실패를 partial·failed 응답으로 바꿔 돌려주므로 요청 로그의 status는 200이다.
    이 줄이 없으면 로그만 보고는 어느 단계가 왜 실패했는지 알 수 없다. request_id로 요청 로그·트레이스와 잇는다.
    error에는 오류 종류·코드만 넣는다. 예외 메시지는 넣지 않는다. 외부 API 주소(키)나 B/L이 섞일 수 있다 (SDD 3.5).
    메시지에도 stage·error를 적는다. JSON 핸들러가 없는 곳(평가 실행기 터미널)에서는 메시지만 찍혀서,
    전에는 "failure" 한 단어만 보여 무엇이 실패했는지 알 수 없었다.
    """
    failure_logger.warning("failure stage=%s error=%s", stage, error,
                           extra={"request_id": current_request_id(), "stage": stage, "error": error})


class RequestLogMiddleware:
    """요청마다 ID를 붙이고, 끝날 때 한 줄을 남긴다.

    BaseHTTPMiddleware가 아니라 순수 ASGI 미들웨어다. BaseHTTPMiddleware는 핸들러를
    다른 태스크에서 돌려서, 핸들러 안에서 set_llm_usage()로 넣은 값이 여기로 돌아오지 않는다.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        request_id = headers.get("x-request-id") or uuid.uuid4().hex[:12]
        request_id_var.set(request_id)
        usage: dict = {}  # 핸들러가 set_llm_usage로 채운다
        llm_usage_var.set(usage)
        request_user_var.set({})  # 로그인 확인(auth.current_user)이 email을 채운다
        started = time.perf_counter()
        status_holder = {"status": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                message.setdefault("headers", [])
                message["headers"].append((b"x-request-id", request_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            # 예외로 끝난 요청도 기록은 남긴다
            self._log(scope, request_id, status_holder["status"], started, usage)

    @staticmethod
    def _log(scope: Scope, request_id: str, status: int, started: float, usage: dict) -> None:
        logger.info(
            "request",
            extra={
                "request_id": request_id,
                "method": scope.get("method"),
                "path": scope.get("path"),
                "status": status,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "model": usage.get("model"),
                "tokens_in": usage.get("tokens_in"),
                "tokens_out": usage.get("tokens_out"),
            },
        )
