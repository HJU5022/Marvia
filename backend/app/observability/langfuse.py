"""프롬프트를 이름으로 가져온다 (작업 D4, SDD 5.6·5.11).

코드에 프롬프트 문자열을 두지 않는다 (CLAUDE.md). 어디서 가져오나:
  1. Langfuse 키가 있으면 Langfuse Prompt에서 label(기본 production)이 붙은 버전
  2. 키가 없거나, 연결·등록·설치 중 하나라도 실패하면 backend/app/prompts/<이름>.md
     채점자가 키 없이 재현할 때(REPLAY_MODE)와 테스트가 이 길을 탄다.
     이 파일은 Langfuse production 버전의 사본이다. 고칠 때는 Langfuse에서 먼저 고치고 여기에 복사한다 (C-11)
돌려주는 version은 트레이스의 prompt_version 자리에 들어간다 (SDD 5.11). 파일에서 왔으면 "local".

개발 중에는 모든 프롬프트가 v0이다. 배포 뒤 평가·확인을 거쳐야 v1로 올린다 (09-28 강사 지침).
Langfuse의 버전 1이 v0이다 (09-28 다시 등록). Langfuse는 고칠 때마다 번호가 자동으로 올라가서
version에 찍히는 숫자가 문서의 v0과 달라질 수 있다 (docs/prompt_versions.md).

prompts/를 backend/app/ 안에 둔 이유: Dockerfile이 backend/를 통째로 복사하므로 이미지에도 들어간다.

LLM 호출과 MCP 도구 호출 트레이스도 여기서 남긴다 (SDD 5.11). 아래 "트레이스" 절.
"""
from __future__ import annotations

import os
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend.app.observability.logging import current_request_id, log_failure

if TYPE_CHECKING:  # 타입 표시에만 쓴다. 실제로 import하면 llm.py와 서로 import하게 된다
    from backend.app.services.llm import LLMResult

PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"
LOCAL_VERSION = "local"



@dataclass
class Prompt:
    name: str
    text: str
    version: str  # Langfuse 버전 번호(문자열) 또는 "local"
    source: Any = None  # Langfuse에서 왔으면 그 PromptClient. 트레이스에 프롬프트를 연결할 때 쓴다 (start_generation)


def get_prompt(name: str, label: str = "production") -> Prompt:
    """이름으로 프롬프트를 가져온다. Langfuse가 안 되면 로컬 파일로 간다. 판정을 막지 않기 위해서다."""
    if os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"):
        try:
            # 키 없는 테스트 환경에는 langfuse가 설치돼 있지 않을 수 있어 여기서 import한다
            from langfuse import Langfuse

            remote = Langfuse().get_prompt(name, label=label)
            return Prompt(name=name, text=remote.prompt, version=str(remote.version), source=remote)
        except Exception as e:  # 미설치·연결 실패·미등록 모두 같은 처리: 로컬 파일
            # 레포 파일로 대신한다. 버전이 local로 찍히므로 Langfuse 버전과 다를 수 있다
            log_failure("langfuse_prompt", f"{type(e).__name__} fallback=local_file")

    path = PROMPT_DIR / f"{name}.md"
    return Prompt(name=name, text=path.read_text(encoding="utf-8"), version=LOCAL_VERSION)


# ── 트레이스 (SDD 5.11) ─────────────────────────────────────────
# LLM을 한 번 부를 때마다 Langfuse에 generation 하나를 남긴다. services/llm.py의 _ask_json()이 부른다.
# MCP 도구를 한 번 부를 때마다 tool 관측 하나도 남긴다. services/mcp_client.py의 call_tool()이 부른다 (10-02).
# 키가 없거나 Langfuse 쪽이 실패해도 판정은 막지 않는다. 트레이스만 빠진다 (get_prompt와 같은 원칙).
# SDD 5.11은 @traced 데코레이터로 적었지만, 결과(토큰·비용)와 실패를 둘 다 남기려고 시작·끝 함수 둘로 나눴다.


def _keys_set() -> bool:
    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"))


def session_scope(session_id: str, user_id: str | None = None) -> AbstractContextManager:
    """이 with 안에서 남기는 트레이스에 session_id를 붙인다. 라우터가 요청 하나를 이걸로 감싼다.

    같은 세션의 조회·후속 질문을 Langfuse Sessions 화면에서 한 줄로 볼 수 있다.
    로그인했으면 user_id도 붙인다 (G3). Supabase 사용자 ID(무작위 UUID)라 이메일·이름은 Langfuse에 가지 않는다.
    잘못된 값(ASCII가 아니거나 200자 초과)은 langfuse가 경고만 남기고 버린다. 요청은 막히지 않는다.
    """
    if not _keys_set():
        return nullcontext()
    try:
        from langfuse import propagate_attributes

        return propagate_attributes(session_id=session_id, user_id=user_id)
    except ImportError:  # 키 없는 테스트 환경처럼 langfuse가 설치돼 있지 않을 때
        return nullcontext()


def start_generation(name: str, input: Any, prompt: Any = None) -> Any:
    """generation 기록을 시작한다. 끝낼 때 돌려받은 값을 end_generation()에 넘긴다. 못 남기면 None.

    trace_id는 요청 ID(응답의 trace_id)를 씨앗으로 만든다. 그러면
      - 같은 요청 안의 pick_vessel·judge가 한 트레이스로 묶이고
      - 응답에 찍힌 trace_id로 Langfuse에서 찾을 수 있다 (metadata.request_id로도 검색된다)
    HTTP 요청 밖(scripts/의 스모크 등)은 요청 ID가 비어 있어 매번 새 트레이스가 된다.

    prompt: get_prompt()가 Langfuse에서 받은 PromptClient. 주면 generation에 연결돼 Langfuse 프롬프트 화면에서
    어느 호출이 어느 버전을 썼는지 보인다 (가이드 9-2 "트레이스에 프롬프트 버전 연결"). 로컬 파일이면 None
    """
    extra = {"prompt": prompt} if prompt is not None else {}
    return _start_observation(name, "generation", input, **extra)


def _start_observation(name: str, as_type: str, input: Any, **extra: Any) -> Any:
    """generation·tool 기록을 여는 공통 부분. 요청 ID로 trace_id를 만들어 같은 요청의 기록을 한 트레이스로 묶는다.

    start_generation()과 start_tool()이 같이 쓴다. 키가 없거나 실패하면 None (트레이스만 빠진다).
    """
    if not _keys_set():
        return None
    try:
        from langfuse import get_client

        client = get_client()
        request_id = current_request_id()
        trace_context = {"trace_id": client.create_trace_id(seed=request_id)} if request_id else None
        return client.start_observation(
            name=name, as_type=as_type, input=input,
            trace_context=trace_context, metadata={"request_id": request_id or None}, **extra,
        )
    except Exception as e:  # 미설치·설정 오류 모두 같은 처리: 트레이스 없이 진행
        log_failure("langfuse_trace_start", f"{type(e).__name__} no_trace")
        return None


def start_tool(name: str, input: Any) -> Any:
    """MCP 도구 호출 기록(tool 관측)을 시작한다 (SDD 5.11 "MCP 도구 호출에 적용"). 못 남기면 None.

    services/mcp_client.py의 call_tool()이 부른다. LLM generation과 같은 트레이스(요청 ID)에 묶인다.
    끝낼 때 돌려받은 값을 end_tool()에 넘긴다.
    """
    return _start_observation(name, "tool", input)


def end_tool(tool: Any, output: Any, metadata: dict[str, Any], error: str | None = None) -> None:
    """start_tool()이 연 기록에 결과를 적고 닫는다. tool이 None이면 아무것도 안 한다.

    output: 결과 요약만 넣는다. ShipFinder 약관상 응답 원본은 저장하지 않는다 (CLAUDE.md "할 것")
    error:  오류 코드. 있으면 level=ERROR로 남아 Langfuse에서 걸러 볼 수 있다
    """
    if tool is None:
        return
    try:
        fields: dict[str, Any] = {"output": output, "metadata": metadata}
        if error:
            fields["level"] = "ERROR"
            fields["status_message"] = error
        tool.update(**fields)
        tool.end()
    except Exception as e:
        log_failure("langfuse_trace_end", type(e).__name__)


def end_generation(generation: Any, result: LLMResult | None, prompt_version: str,
                   output: Any = None, error: str | None = None) -> None:
    """start_generation()이 연 기록에 결과를 적고 닫는다. generation이 None이면 아무것도 안 한다.

    result: chat()이 돌려준 값. 호출 자체가 실패했으면 None (그때는 error만 남는다)
    output: 검사를 통과한 출력 (dict). 실패면 None
    error:  실패 이유. 있으면 level=ERROR로 남아 Langfuse에서 걸러 볼 수 있다
    지연(latency)은 따로 적지 않는다. 시작~끝 시간이 곧 지연이고, 재시도 대기까지 포함된다.
    """
    if generation is None:
        return
    try:
        fields: dict[str, Any] = {"output": output, "metadata": {"prompt_version": prompt_version}}
        if result is not None:
            fields["model"] = result.model
            fields["usage_details"] = {"input": result.prompt_tokens or 0, "output": result.completion_tokens or 0}
            if result.cost is not None:
                fields["cost_details"] = {"total": result.cost}  # OpenRouter가 준 실제 금액 (크레딧 = USD)
            fields["metadata"].update({
                "retry_count": result.attempts - 1,  # 첫 시도는 재시도가 아니다
                # 입력 중 캐시에서 읽은 토큰 (09-30). usage_details가 아니라 metadata에 둔다. usage에 넣으면 Langfuse가
                # 모델 가격표로 비용을 계산할 때 입력 토큰과 겹쳐 두 번 셀 수 있어서다 (가격표 키 대응은 확인 안 함)
                "cached_tokens": result.cached_tokens,
                "provider": result.provider,
                "openrouter_id": result.request_id,
            })
        if error:
            fields["level"] = "ERROR"
            fields["status_message"] = error
        generation.update(**fields)
        generation.end()
    except Exception as e:
        log_failure("langfuse_trace_end", type(e).__name__)


def end_web_search(generation: Any, found: list[dict] | None, usage: Any = None, model: str | None = None,
                   error: str | None = None) -> None:
    """llm.web_search()가 연 generation(start_generation)에 결과를 적고 닫는다. generation이 None이면 아무것도 안 한다 (10-05).

    웹 검색도 OpenRouter 호출이라 돈이 든다(검색 한 번 약 $0.008). 요청 트레이스에 보이게 남긴다.
    output: 결과 제목·URL 목록만. 본문(text)은 길고 외부 글이라 저장하지 않는다
    usage:  OpenRouter 응답의 usage (토큰·cost). 없으면 비용·토큰은 비운다
    error:  실패 이유. 있으면 level=ERROR. 검색어(input)는 호출하는 쪽이 이미 가린 것이다
    """
    if generation is None:
        return
    try:
        fields: dict[str, Any] = {"metadata": {"result_count": len(found or [])}}
        if found is not None:
            fields["output"] = [{"title": r.get("title"), "url": r.get("url")} for r in found]
        if model:
            fields["model"] = model
        if usage is not None:
            fields["usage_details"] = {"input": getattr(usage, "prompt_tokens", None) or 0,
                                       "output": getattr(usage, "completion_tokens", None) or 0}
            cost = getattr(usage, "cost", None)
            if isinstance(cost, (int, float)):
                fields["cost_details"] = {"total": cost}  # OpenRouter가 준 실제 금액 (크레딧 = USD)
        if error:
            fields["level"] = "ERROR"
            fields["status_message"] = error
        generation.update(**fields)
        generation.end()
    except Exception as e:
        log_failure("langfuse_trace_end", type(e).__name__)


def flush() -> None:
    """모아 둔 트레이스를 지금 Langfuse로 보낸다. 서버가 꺼질 때 main.py lifespan이 부른다.

    Langfuse SDK는 트레이스를 모았다가 뒤에서 보낸다. 보내기 전에 서버가 꺼지면 그 트레이스는 사라진다
    (09-29 데모: 서류 사진 두 번째 요청 직후 서버를 끄자 그 트레이스가 Langfuse에 없었다).
    Cloud Run은 요청이 없으면 인스턴스를 끄므로 배포에서 더 자주 생긴다. 실패해도 종료는 막지 않는다.
    """
    if not _keys_set():
        return
    try:
        from langfuse import get_client

        get_client().flush()
    except Exception as e:
        log_failure("langfuse_flush", type(e).__name__)
