"""Langfuse 트레이스·span. (SDD 5절 "단계마다 span 하나", 필수 조건 4)

키가 없거나 패키지가 없으면 아무 것도 보내지 않고 조용히 지나간다. 이유:
  - `pytest backend/tests` 는 키 없이 돌아야 한다 (TEST_GUIDE)
  - 관측이 죽었다고 서비스가 죽으면 안 된다. 트레이스는 곁다리지 본업이 아니다

쓰는 쪽은 이렇게만 안다:

    with trace("agent", user_id=user_id) as t:
        with t.span("extract", input=text) as s:
            s.output = slots

프롬프트도 여기서 가져온다 (SDD 8절). 코드에 프롬프트 문자열을 두지 않는다.
"""
from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

_client: Any | None = None
_checked = False


def _get_client() -> Any | None:
    """Langfuse 클라이언트. 키가 없거나 SDK가 없으면 None."""
    global _client, _checked
    if _checked:
        return _client
    _checked = True
    if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
        return None
    try:
        from langfuse import Langfuse  # 지연 import: 패키지가 없어도 테스트가 돈다
    except ImportError:
        return None
    _client = Langfuse(
        public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
        secret_key=os.environ["LANGFUSE_SECRET_KEY"],
        host=os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com"),
    )
    return _client


class Span:
    """단계 하나. output 에 결과를, error 에 실패 사유를 넣으면 종료할 때 함께 올라간다."""

    def __init__(self, handle: Any | None, name: str) -> None:
        self._handle = handle
        self.name = name
        self.output: Any = None
        self.error: str | None = None

    def end(self) -> None:
        if self._handle is None:
            return
        try:
            self._handle.update(output=self.output, level="ERROR" if self.error else None, status_message=self.error)
            self._handle.end()
        except Exception:  # noqa: BLE001  관측 실패가 요청을 깨뜨리지 않는다
            pass


class Trace:
    """요청 하나. trace_id 는 응답(AgentResponse.trace_id)과 request_logs 가 같은 값을 쓴다."""

    def __init__(self, handle: Any | None, trace_id: str) -> None:
        self._handle = handle
        self.id = trace_id

    @contextmanager
    def span(self, name: str, **input_kwargs: Any) -> Iterator[Span]:
        handle = None
        if self._handle is not None:
            try:
                handle = self._handle.span(name=name, input=input_kwargs or None)
            except Exception:  # noqa: BLE001
                handle = None
        span = Span(handle, name)
        try:
            yield span
        except Exception as e:
            span.error = f"{type(e).__name__}: {e}"
            span.end()
            raise
        span.end()


@contextmanager
def trace(name: str, user_id: str | None = None, **metadata: Any) -> Iterator[Trace]:
    """요청 하나를 감싼다. Langfuse 가 꺼져 있어도 trace_id 는 항상 만든다."""
    trace_id = uuid.uuid4().hex
    client = _get_client()
    handle = None
    if client is not None:
        try:
            handle = client.trace(id=trace_id, name=name, user_id=user_id, metadata=metadata or None)
        except Exception:  # noqa: BLE001
            handle = None
    yield Trace(handle, trace_id)
    if client is not None:
        try:
            client.flush()  # Cloud Run 은 요청이 끝나면 CPU 를 멈춘다. 여기서 보내지 않으면 유실된다
        except Exception:  # noqa: BLE001
            pass


def get_prompt(name: str, label: str = "production") -> tuple[str, str]:
    """Langfuse Prompt 에서 프롬프트 본문과 버전을 가져온다 (SDD 8절).

    이름은 SDD 8절 표에 있는 것만 쓴다: converge/slot-extract, converge/vision-transcribe,
    converge/judge-ship, converge/judge-si, converge/eval-judge.

    Langfuse 가 꺼져 있으면 부르는 쪽이 실패해야 한다. 프롬프트를 코드에 숨겨 두는 우회를 막기 위해서다.
    """
    client = _get_client()
    if client is None:
        raise RuntimeError(f"Langfuse 가 꺼져 있어 프롬프트를 가져올 수 없습니다: {name}")
    prompt = client.get_prompt(name, label=label)
    return prompt.prompt, str(prompt.version)
