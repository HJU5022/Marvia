"""요청 처리 단계 소식 (docs/specs/chat-progress.md).

판정 흐름이 실제로 다음 단계에 들어갈 때 step("customs")처럼 한 줄 알린다. 듣는 쪽(POST /api/chat/stream)이
listening()으로 등록했을 때만 전달되고, 없으면 아무 일도 하지 않는다. 그래서 /api/agent, /api/chat, 평가 실행기,
기존 테스트의 동작과 결과는 그대로다.

왜 ContextVar인가: 단계 지점(routers/agent._assess 등)과 듣는 쪽(스트림 라우터) 사이에 함수 인자를 줄줄이 넘기면
판정 코드의 함수 모양이 다 바뀐다. 요청 하나 안에서만 보이는 변수에 듣는 함수를 두면 판정 코드는 step 한 줄만 늘어난다.
요청 ID(observability/logging.request_id_var)도 같은 방식이다.

화면에 타이머로 단계를 꾸며 넘기지 않기 위한 장치다 (가이드 8-3 즉각 피드백). 판정 문장 자체는
흘려보내지 않는다. 검증(V1~V10)을 통과한 최종 응답만 나간다 (특강 스트리밍 응답 처리 레벨 3).
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

# 단계 이름. 화면(web/lib/progress.ts)이 이 이름을 한국어 라벨로 바꾼다. 여기 없는 이름은 보내지 않는다
STAGES = (
    "understand",  # 질문 이해와 도구 고르기 (services/chat/chat.py, 에이전트 LLM. 대비 경로는 route_chat)
    "customs",     # 통관 정보 조회 (UNI-PASS, routers/agent._fetch_customs)
    "identify",    # 선박 식별 (routers/agent._identify)
    "position",    # 위치·입항 일정 조회 (ShipFinder·해수부·searoute)
    "judge",       # 판정 설명 작성과 검증 (LLM judge + validate)
    "answer",      # 후속 질문 답 작성 (routers/agent._follow_up)
    "schedule",    # 부산 입항 예정 조회 (해수부, services/chat/chat.search_vessels)
    "ports",       # 질문한 지역의 항구 고르기 (LLM match_ports)
    # 채팅 에이전트가 고른 읽기 전용 MCP 도구 (services/chat/chat.py MCP_STAGES). 고른 순서대로 화면에 보인다
    "tool_candidates",  # 선박 후보 검색 (get_vessel_candidates)
    "tool_position",    # 선박 실시간 위치 (get_live_position)
    "tool_schedule",    # 부산 입항 기록 (get_port_schedule)
    "tool_distance",    # 남은 항로 거리 (estimate_distance)
    # 기억 뽑기가 저장할 것을 찾았을 때만 (services/account/memory._write_from_text). 답 만들기와 같이 돌아 다른 단계와 겹칠 수 있다
    "memory",
)

_listener: ContextVar[Callable[[str], None] | None] = ContextVar("progress_listener", default=None)


def step(stage: str) -> None:
    """지금 이 단계에 들어갔다고 알린다. 듣는 쪽이 없으면 아무것도 안 한다.

    듣는 쪽이 실패해도(연결이 끊긴 화면 등) 판정은 계속돼야 하므로 예외를 밖으로 내보내지 않는다.
    """
    if stage not in STAGES:
        return
    listener = _listener.get()
    if listener is None:
        return
    try:
        listener(stage)
    except Exception:  # noqa: BLE001 - 소식 전달 실패가 조회를 멈추면 안 된다
        pass


@contextmanager
def listening(listener: Callable[[str], None]) -> Iterator[None]:
    """이 with 안에서 일어나는 step()을 listener로 받는다. 끝나면 원래대로 돌린다."""
    token = _listener.set(listener)
    try:
        yield
    finally:
        _listener.reset(token)
