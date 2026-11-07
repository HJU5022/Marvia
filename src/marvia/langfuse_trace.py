"""Langfuse로 내보내는 트레이스를 네 겹으로 가린다 (설계 11절·12절, 계획 6b, done 3.9).

⓪ should_export_span=is_langfuse_span: Langfuse SDK가 만든 span만 내보낸다. 다른 라이브러리의 OTel span
   (MCP 서버의 gen_ai span 등)은 ①·③을 거치지 않고 예외 사건·상태 설명을 그대로 싣는다.
① mask=scrub: span의 input·output·metadata를 JSON으로 바꾸기 전에 가린다(trace.scrub).
② mask_otel_spans=scrub_spans: 내보내기 직전 span 속성 중 ①이 맡지 않는 글(status_message 등)을 가린다.
③ ScrubbedHandler: 오류를 가린 사본으로 넘긴다. span 상태 설명(status.description)은 ①·②가 닿지 않는다.
하나라도 빼면 tests/graph/test_trace.py의 문 시험이 실패한다(test_removing_any_one_layer_leaves_its_numbers).
[주의] 네 겹은 span 이름, 사건(event), 자원(resource)을 바꾸지 않는다. 이름은 코드가 정한 글만 쓴다
(run_name을 사용자 글로 만들지 않는다). SDK span에는 사건이 없고,
자원은 SDK 기본값과 운영자의 OTEL_* 환경 변수가 정한다.
하지 않는 일: 켜고 끄기와 키 읽기(trace.tracer_callbacks). 이 모듈은 키가 셋 다 있을 때만 불러온다.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any

from langchain_core.messages import ToolMessage
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler
from langfuse.span_filter import is_langfuse_span
from langfuse.types import MaskOtelSpansParams, MaskOtelSpansResult, OtelSpanPatch
from langgraph.errors import GraphBubbleUp
from opentelemetry.sdk.trace.export import SpanExporter

from marvia.trace import MASK, scrub, scrub_text

# [왜] ①이 JSON으로 바꾸기 전에 가린 칸이다. ②가 JSON 글을 다시 가리면 \u 이스케이프가 깨진다
#      (11-07 실측: "제241조"를 적은 \uc81c241이 번호 후보로 가려져 JSON을 읽을 수 없게 된다)
#      trace.metadata는 여기 없다: SDK가 propagate_attributes로 적어 ①을 거치지 않고, thread_id처럼
#      사용자가 정한 글이 든다. ②는 JSON 값을 읽어서 가리고 다시 적는다(_clean)
PAYLOAD = (
    "langfuse.observation.input",
    "langfuse.observation.output",
    "langfuse.observation.metadata",
)


# [왜] SDK가 JSON으로 적는 시각 속성은 그대로 둔다. 번호 덩어리 규칙은 날짜와 시를 한 덩어리로 가려
#      시각이 아니게 만든다. 이 속성 하나에만, 읽히는 시각일 때만 둔다(다른 곳의 시각 모양 글은 가린다).
#      소수부는 isoformat이 쓰는 6자리까지만 받는다
TIME_ATTRIBUTE = "langfuse.observation.completion_start_time"
ISO_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})?", re.ASCII)


def _is_time(text: str) -> bool:
    """SDK가 적은 JSON 시각 글인가: 글 하나이고 ISO 모양이며 fromisoformat이 읽는다."""
    try:
        value = json.loads(text)
        return (
            isinstance(value, str) and bool(ISO_TIME.fullmatch(value)) and bool(datetime.fromisoformat(value))
        )
    except ValueError:
        return False


def _number(literal: str) -> Any:
    """JSON 수 글자 하나를 읽는다. 번호처럼 생긴 수(12자리 B/L 등)는 MASK 글로 바꾼다."""
    # [왜] 읽기 전 글자로 본다. 읽은 뒤의 수는 글자 모양이 바뀔 수 있다(0.0000000123 → 1.23e-08)
    return MASK if scrub_text(literal) != literal else json.loads(literal)


def _clean_json(value: Any) -> Any:
    """JSON에서 읽은 값의 글을 가린다(수는 _number가 읽을 때 가렸다)."""
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, list):
        return [_clean_json(item) for item in value]
    if isinstance(value, dict):
        # [주의] 가린 뒤 겹치는 키는 뒤 값만 남는다(트레이스 값을 잃을 뿐 번호는 나가지 않는다)
        return {scrub_text(key): _clean_json(item) for key, item in value.items()}
    return value


def _no_repeated_key(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    # [왜] 같은 키가 두 번이면 읽은 값에서 앞 값이 사라져 "바뀐 것 없음"으로 보인다. 글로 가리게 넘긴다
    if len({key for key, _ in pairs}) != len(pairs):
        raise ValueError("repeated key")
    return dict(pairs)


def _clean_text(text: str) -> str:
    """글 하나를 가린다. SDK가 JSON으로 적은 값(trace metadata, 시각)은 읽어서 가린 뒤 다시 적는다."""
    # [왜] JSON 글을 그대로 가리면 \n 같은 이스케이프 뒤 덩어리가 \[가림]이 되어 JSON이 깨진다 (계획 6c)
    try:
        value = json.loads(text, object_pairs_hook=_no_repeated_key)
    except ValueError:
        return scrub_text(text)  # JSON이 아닌 글(status_message 등)
    cleaned = _clean_json(json.loads(text, parse_int=_number, parse_float=_number))
    # [왜] 가릴 것이 없으면 SDK가 적은 글을 그대로 둔다(띄어쓰기 모양도 바꾸지 않는다)
    return text if cleaned == value else json.dumps(cleaned, ensure_ascii=False)


def _clean(value: Any, name: str = "") -> Any:
    """속성 값 하나를 가린다. 글 목록(OTel은 tuple로 둔다)은 글만 가린다. 시각 속성의 읽히는 시각은 둔다."""
    if isinstance(value, str):
        if name == TIME_ATTRIBUTE and _is_time(value):
            return value
        return _clean_text(value)
    if isinstance(value, (list, tuple)):
        return tuple(_clean_text(item) if isinstance(item, str) else item for item in value)
    return value


def scrub_spans(*, params: MaskOtelSpansParams) -> MaskOtelSpansResult:
    """② 내보내기 직전 span 속성의 글을 가린다. 바뀐 속성만 고친다.

    [주의] 여기서 예외가 나면 Langfuse는 그 묶음을 통째로 버린다(아무것도 나가지 않는다).
    """
    patches = {}
    for key, span in params.spans.items():
        changed = {
            name: _clean(value, name)
            for name, value in span.attributes.items()
            if not name.startswith(PAYLOAD) and _clean(value, name) != value
        }
        if changed:
            patches[key] = OtelSpanPatch(set_attributes=changed)
    return MaskOtelSpansResult(span_patches=patches)


class ScrubbedError(Exception):
    """가린 오류 글만 지닌 예외. 원래 예외는 Langfuse에 넘기지 않는다."""


def _scrubbed(error: BaseException) -> BaseException:
    """오류를 가린 사본으로 바꾼다. 끼어들기(GraphBubbleUp)는 그대로 둔다."""
    # [왜] 끼어들기는 Langfuse가 오류 단계로 보지 않아(DEFAULT) span 상태 설명을 쓰지 않는다.
    #      질문 글이 드는 status_message 속성은 ②가 가린다
    if isinstance(error, GraphBubbleUp):
        return error
    # [왜] 예외 이름은 코드가 정한 글이라 남긴다. 글은 scrub이 str()이 죽는 예외까지 받아 가린다
    return ScrubbedError(f"{type(error).__name__}: {scrub(error)}")


class ScrubbedHandler(CallbackHandler):
    """③ 오류와 오류 도구 결과를 가린 사본으로 받는 Langfuse 콜백."""

    def on_chain_error(self, error: BaseException, **kwargs: Any) -> Any:
        return super().on_chain_error(_scrubbed(error), **kwargs)

    def on_tool_error(self, error: BaseException, **kwargs: Any) -> Any:
        return super().on_tool_error(_scrubbed(error), **kwargs)

    def on_llm_error(self, error: BaseException, **kwargs: Any) -> Any:
        return super().on_llm_error(_scrubbed(error), **kwargs)

    def on_retriever_error(self, error: BaseException, **kwargs: Any) -> Any:
        return super().on_retriever_error(_scrubbed(error), **kwargs)

    def on_tool_end(self, output: Any, **kwargs: Any) -> Any:
        # [왜] 도구가 오류 결과(status="error")를 내면 Langfuse가 그 글을 span 상태 설명에도 넣는다
        if isinstance(output, ToolMessage) and output.status == "error":
            output = output.model_copy(update={"content": scrub(output.content)})
        return super().on_tool_end(output, **kwargs)


def build(
    public_key: str, secret_key: str, host: str, exporter: SpanExporter | None = None
) -> CallbackHandler:
    """가린 Langfuse 클라이언트를 만들고 그 콜백을 돌려준다. exporter는 시험이 메모리로 받을 때만 준다."""
    # [왜] 키와 주소는 인자로만 넘긴다. 인자가 없으면 SDK가 LANGFUSE_* 환경 변수를 읽는다
    # [주의] SDK는 전역 OTel TracerProvider가 없으면 자기 것을 전역으로 놓는다(resource_manager.py).
    #        그 뒤 다른 라이브러리의 span도 여기로 오고, 기본 거름은 gen_ai 속성이 있으면 내보낸다
    # [왜] 사진이나 붙여 넣은 data URI에 화물 번호가 있을 수 있다. SDK는 ①이 가리기 전의 원본 입력에서
    #      data:...;base64, 글을 찾아 올린다(연결이 생긴다).
    #      끄는 길은 이 환경 변수뿐이고 클라이언트를 만들 때 읽는다.
    #      서버 시작 검사가 LANGFUSE_* 이름을 거절하는 일은 build보다 앞이라 이 설정은 걸리지 않는다
    os.environ["LANGFUSE_MEDIA_UPLOAD_ENABLED"] = "false"
    Langfuse(
        public_key=public_key,
        secret_key=secret_key,
        base_url=host,
        should_export_span=is_langfuse_span,
        mask=scrub,
        mask_otel_spans=scrub_spans,
        span_exporter=exporter,
    )
    # [왜] 콜백은 공개키로 위 클라이언트를 찾는다(langfuse.get_client의 공개키별 등록부)
    return ScrubbedHandler(public_key=public_key)
