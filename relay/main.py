"""해수부 API 릴레이 .

왜: Railway(싱가포르)에서 apis.data.go.kr로 연결하면 ConnectTimeout이 난다(한국에서는 0.1초).
이 서버를 Google Cloud Run 서울(asia-northeast3)에 두고, 백엔드가 MOF_BASE_URL로 여기를 부르게 한다.

하는 일: GET 요청을 그대로 apis.data.go.kr로 넘기고 상태·본문·content-type을 돌려준다.
보안: X-Relay-Token 필수(RELAY_TOKEN과 상수 시간 비교), 경로 허용 목록, 쿼리스트링은 로그에 남기지 않는다
(serviceKey가 들어 있다). 백엔드와 별개로 배포하므로 backend 코드를 import하지 않는다.
"""
from __future__ import annotations

import hmac
import logging
import os
import time

import httpx
from fastapi import FastAPI, Request, Response

UPSTREAM = "https://apis.data.go.kr"
ALLOWED_PREFIXES = ("/1192000/VsslEtrynd5/", "/1192000/CntlVssl2/")
UPSTREAM_TIMEOUT_SEC = 10.0

logger = logging.getLogger("relay")
logging.basicConfig(level=logging.INFO)
# httpx는 INFO에서 요청 주소 전체(serviceKey 포함)를 찍는다. 키가 로그에 남지 않게 WARNING으로 올린다
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
# 테스트가 이 변수를 MockTransport 클라이언트로 바꾼다
_client = httpx.Client(timeout=UPSTREAM_TIMEOUT_SEC)


# Cloud Run은 /healthz 경로를 자기 쪽에서 가로채 404를 낸다. 그래서 /health로 둔다
@app.get("/health")
def healthz() -> Response:
    return Response("ok", media_type="text/plain")


@app.get("/1192000/{rest:path}")
def relay(rest: str, request: Request) -> Response:
    expected = os.environ.get("RELAY_TOKEN")
    if not expected:
        return Response("relay token not configured", status_code=503)  # 토큰 없이는 아무것도 열지 않는다
    given = request.headers.get("x-relay-token", "")
    if not hmac.compare_digest(given.encode(), expected.encode()):
        return Response("unauthorized", status_code=401)

    path = "/1192000/" + rest
    if ".." in path or not path.startswith(ALLOWED_PREFIXES):
        return Response("not found", status_code=404)

    url = UPSTREAM + path
    query = request.scope.get("query_string", b"").decode()
    if query:
        url += "?" + query  # 원본 그대로 넘긴다

    started = time.monotonic()
    try:
        upstream = _client.get(url)
    except httpx.TimeoutException:
        _log(path, "timeout", started)
        return Response("upstream timeout", status_code=504)
    except httpx.HTTPError:
        _log(path, "error", started)
        return Response("upstream error", status_code=502)
    _log(path, upstream.status_code, started)
    return Response(
        upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
    )


def _log(path: str, status, started: float) -> None:
    # 경로·상태·소요 시간만. 쿼리스트링에는 serviceKey가 있어 남기지 않는다
    logger.info("path=%s status=%s elapsed_ms=%d", path, status, (time.monotonic() - started) * 1000)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
