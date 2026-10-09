"""채팅 창구의 결과 모양(ChatResult)과 오류, 지켜보기·카카오 훅 묶음 (services/chat/chat.py에서 옮김)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from backend.app.schemas.agent import AgentResponse, AgentRequest

class ChatError(Exception):
    """kind: too_long / empty."""

    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind

@dataclass
class ChatResult:
    kind: str                       # cargo / vessels / message
    reply: str
    agent: AgentResponse | None = None
    request: AgentRequest | None = None
    vessels: list[dict] = field(default_factory=list)
    place: str | None = None
    ports: list[str] = field(default_factory=list)
    days: int | None = None
    # 이번 문장에서 도구가 실제로 가져온 선박 실시간 위치 (미니 지도용). 도구 결과에서만 만든다 (_map_payload)
    map: dict | None = None
    # 한 문장에 B/L이 2~3개일 때 조회한 화물 한 줄씩 (말풍선 표용). 한 개짜리 답은 비어 있다.
    # agent·request는 첫 B/L의 것이고(오른쪽 칸과 다음 문장의 문맥), 줄마다 자기 agent·request를 들고 있어 표에서 고르면 화면이 바뀐다
    cargos: list[dict] = field(default_factory=list)
    # 대화로 지켜보기. watch_offer: 코드가 쓴 "지켜볼까요?" 제안 {"bl_no","reason","logged_in"} (화면이 버튼으로 보여 준다).
    # watch_set: 이번 문장으로 지켜보기를 켜거나 껐을 때 {"bl_no","on"} (화면이 토글을 새로 읽는다). 둘 다 없으면 None
    watch_offer: dict | None = None
    watch_set: dict | None = None
    # 배 지켜보기: 이번 문장으로 배 한 척을 감시 목록에 넣거나 뺐을 때 {"mmsi","name","on"} (화면이 그 배의 버튼을 새로 읽는다)
    watch_vessel_set: dict | None = None
    # 답 문장 속 근거 표시 (services/chat/citations.py). evidence_items: 이번 문장에서 모은 근거 목록
    # [{id, source, fetched_at, values:[{field,value}], url?, title?}] (B/L·컨테이너 번호는 가려진 값). citations: 검증을 통과한 [E#] 표시의
    # 위치 [{id, start, end, evidence_ref}] (start/end는 reply 안 "[E1]"의 자리). 코드 문장·고정 문구는 citations가 비고 evidence_items만 있다
    evidence_items: list[dict] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)

@dataclass
class VesselHooks:
    """로그인한 사용자의 배 지켜보기(B/L 없이 배만)를 읽고 쓰는 함수 셋. 라우터가 DB 연결을 열어 만든다 (routers/chat._vessel_hooks).
    resolve(call_sign, name): {"mmsi"} 또는 {"error": VesselWatchError.kind}. 입항 예정 목록은 MMSI가 없어 호출부호로 찾는다.
    add(mmsi, name, flag, dest, eta, call_sign): {"mmsi"} 또는 {"error": kind}. remove(mmsi): {"mmsi"} 또는 {"error": kind}."""

    resolve: Callable[[str, str | None], dict]
    add: Callable[..., dict]
    remove: Callable[[int], dict]

@dataclass
class WatchHooks:
    """로그인한 사용자의 지켜보기를 실제로 읽고 쓰는 함수 셋. 라우터가 DB 연결을 열어 만들어 넘긴다 (routers/chat._watch_hooks).
    서비스가 DB를 몰라야 가짜 함수로 시험할 수 있다 (run_tool과 같은 방식).
    tool(bl_no, on): {"on": 바뀐 뒤 상태} 또는 {"error": WatchError.kind 또는 "db"}. state(bl_no): {"saved", "watch"}.
    worry(bl_no): 그 화물에 사용자가 적어 둔 걱정 메모 글 (없으면 None)."""

    tool: Callable[[str, bool], dict]
    state: Callable[[str], dict]
    worry: Callable[[str], str | None]
    vessel: VesselHooks | None = None  # 배 지켜보기 (watch_vessel 도구). 없으면 배는 못 지켜본다고 안내한다

@dataclass
class KakaoHooks:
    """로그인한 사용자의 카카오톡으로 지금 상태를 보내는 함수 둘. 라우터가 DB 연결을 열어 만들어 넘긴다 (routers/chat._kakao_hooks).
    row(bl_no): 그 화물의 저장된 줄(services/watch/cargo.get_row 모양 dict), 없으면 None.
    send(text): {"sent": True} 또는 {"error": KakaoLinkError.kind / KakaoError.kind / "db"}. 화면 주소는 라우터가 붙인다.
    linked(): 이 사용자가 카카오톡을 연결해 두었나 (지켜보기 답에서 카톡 얘기가 나왔을 때 사실대로 말하려고)."""

    row: Callable[[str], dict | None]
    send: Callable[[str], dict]
    linked: Callable[[], bool] | None = None  # 카카오톡을 연결했나 (services/watch/kakao.is_linked). 없으면 모른다
