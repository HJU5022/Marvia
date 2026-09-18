"""Langfuse 트레이스·span·프롬프트. (SDD 5절 "단계마다 span 하나", 8절 프롬프트, 필수 조건 4)

키가 없거나 패키지가 없으면 아무 것도 보내지 않고 조용히 지나간다. 이유:
  - `pytest backend/tests` 는 키 없이 돌아야 한다 (TEST_GUIDE)
  - 관측이 죽었다고 서비스가 죽으면 안 된다. 트레이스는 곁다리지 본업이 아니다

프롬프트만은 예외로, 못 가져오면 부르는 쪽이 실패한다. 프롬프트를 코드에 숨겨 두는 우회를 막기 위해서다.

쓰는 쪽은 이렇게만 안다:

    with trace("agent", user_id=user_id) as t:
        with t.span("extract", input=text) as s:
            s.output = slots

SDK 버전:
  설치된 langfuse 는 4.x 다 (requirements.txt 는 >=2.50). 2.x 의 client.trace(...) 는 없어지고
  OpenTelemetry 기반 start_as_current_observation / propagate_attributes 로 바뀌었다. 이 파일이
  그 차이를 흡수하므로 파이프라인은 SDK 버전을 몰라도 된다.
"""
from __future__ import annotations

import os
import uuid
from contextlib import ExitStack, contextmanager
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
    try:
        _client = Langfuse(
            public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
            secret_key=os.environ["LANGFUSE_SECRET_KEY"],
            host=os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )
    except Exception:  # noqa: BLE001  관측 초기화 실패가 서비스를 막지 않는다
        _client = None
    return _client


class Span:
    """단계 하나. output 에 결과를, error 에 실패 사유를 넣으면 종료할 때 함께 올라간다."""

    def __init__(self, handle: Any | None, name: str) -> None:
        self._handle = handle
        self.name = name
        self.output: Any = None
        self.error: str | None = None

    def flush_update(self) -> None:
        if self._handle is None:
            return
        try:
            self._handle.update(
                output=self.output,
                level="ERROR" if self.error else None,
                status_message=self.error,
            )
        except Exception:  # noqa: BLE001
            pass


class Trace:
    """요청 하나. id 는 응답(AgentResponse.trace_id)과 request_logs 가 같은 값을 쓴다."""

    def __init__(self, client: Any | None, trace_id: str) -> None:
        self._client = client
        self.id = trace_id

    @contextmanager
    def span(self, name: str, **input_kwargs: Any) -> Iterator[Span]:
        if self._client is None:
            yield Span(None, name)
            return
        with ExitStack() as stack:
            handle = None
            try:
                handle = stack.enter_context(
                    self._client.start_as_current_observation(name=name, input=input_kwargs or None)
                )
            except Exception:  # noqa: BLE001
                handle = None
            span = Span(handle, name)
            try:
                yield span
            except Exception as e:
                span.error = f"{type(e).__name__}: {e}"
                span.flush_update()
                raise
            span.flush_update()


@contextmanager
def trace(
    name: str, user_id: str | None = None, session_id: str | None = None, **metadata: Any
) -> Iterator[Trace]:
    """요청 하나를 감싼다. Langfuse 가 꺼져 있어도 trace_id 는 항상 만든다."""
    client = _get_client()
    if client is None:
        yield Trace(None, uuid.uuid4().hex)
        return

    from langfuse import propagate_attributes

    clean = {k: v for k, v in metadata.items() if v is not None}
    with ExitStack() as stack:
        try:
            root = stack.enter_context(client.start_as_current_observation(name=name))
            stack.enter_context(
                propagate_attributes(user_id=user_id, session_id=session_id, metadata=clean or None)
            )
            trace_id = client.get_current_trace_id() or uuid.uuid4().hex
        except Exception:  # noqa: BLE001
            yield Trace(None, uuid.uuid4().hex)
            return
        try:
            yield Trace(client, trace_id)
        finally:
            del root
            try:
                # Cloud Run 은 요청이 끝나면 CPU 를 멈춘다. 여기서 보내지 않으면 유실된다
                client.flush()
            except Exception:  # noqa: BLE001
                pass


def get_prompt(name: str, label: str = "production") -> tuple[str, str]:
    """Langfuse Prompt 에서 프롬프트 본문과 버전을 가져온다 (SDD 8절).

    이름은 SDD 8절 표에 있는 것만 쓴다: converge/slot-extract, converge/vision-transcribe,
    converge/judge-ship, converge/judge-si, converge/eval-judge.
    """
    client = _get_client()
    if client is None:
        raise RuntimeError(f"Langfuse 가 꺼져 있어 프롬프트를 가져올 수 없습니다: {name}")
    prompt = client.get_prompt(name, label=label)
    return prompt.prompt, f"{name}@{prompt.version}"
