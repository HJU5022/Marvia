"""외부 API 재시도 (작업 A9).

타임아웃과 5xx는 잠깐 뒤 다시 부르면 되는 경우가 많다. SDD 8절이 도구 단위 재시도 2회와
백오프를 요구한다. 재시도해도 안 되면 원래 예외를 그대로 올려서 호출부가 partial로 간다.

재시도하지 않는 것: 4xx, 인증 실패, 없는 자원. 다시 불러도 같은 답이 온다.
빈도 초과(ShipFinder 23·29)도 여기서 다루지 않는다. 그쪽은 캐시가 받는다 (B8).
"""
from __future__ import annotations

import logging
import time
from typing import Callable, TypeVar

import httpx

T = TypeVar("T")

MAX_ATTEMPTS = 3  # 최초 1회 + 재시도 2회 (SDD 8절)
BACKOFF_SEC = 0.5  # 시도 사이 대기. 2회차 0.5초, 3회차 1.0초
RETRYABLE_STATUS = range(500, 600)

logger = logging.getLogger(__name__)


def is_retryable(error: Exception) -> bool:
    if isinstance(error, httpx.TimeoutException):
        return True
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in RETRYABLE_STATUS
    return isinstance(error, (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError))


def with_retry(call: Callable[[], T], *, name: str, attempts: int = MAX_ATTEMPTS, backoff: float | None = None) -> T:
    """call을 부르고, 되살아날 만한 실패면 백오프를 두고 다시 부른다.

    Args:
        call: 인자 없는 호출. 보통 lambda로 감싼다
        name: 로그에 남길 이름. 예: shipfinder:VesselSearch
        attempts: 최초 호출을 포함한 총 시도 횟수
        backoff: 첫 대기 시간(초). 시도마다 곱절로 늘린다. 생략하면 모듈 기본값(테스트는 0으로 바꾼다)
    """
    wait_base = BACKOFF_SEC if backoff is None else backoff
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception as e:  # 되살아날 만한 실패인지 보고 정한다
            if not is_retryable(e) or attempt == attempts:
                raise
            last = e
            wait = wait_base * (2 ** (attempt - 1))
            logger.warning("%s 실패(%s), %.1f초 뒤 재시도 %d/%d", name, type(e).__name__, wait, attempt + 1, attempts)
            time.sleep(wait)
    raise last  # 여기 오지 않는다. 마지막 시도는 위에서 raise된다
