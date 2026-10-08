"""도구 get_port_schedule (작업 B6). 부산항 입항 일정과 접안 시설을 가져온다.

해수부 API 두 개를 합쳐서 돌려준다 (B5 MofClient).

- 관제정보: 이미 일어난 실적. 실제 입항 시각과 접안 시설
- 선박운항정보: 입출항 신고. 아직 안 들어온 배의 입항 예정

UNI-PASS에는 MMSI가 없고 ShipFinder에는 접안 시설이 없어서, 둘을 잇는 값은
호출부호(call_sign)와 선명이다.

조회 기간은 지난 며칠(실적)과 앞으로 며칠(예정)을 함께 본다. 화물 추적에서 궁금한 것은
"이미 들어왔는가"와 "언제 들어오는가" 둘 다이기 때문이다.

출력 계약은 mcp_server/schemas.py의 PortScheduleResult다 (C4, SDD 3.4).

MCP 등록: 이 함수는 mcp_server/server.py create_mcp()가 도구로 등록한다 (데코레이터 없음).
"""
import re
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Annotated

from pydantic import Field

from backend.app.clients.mof import MofClient, MofError, SailingPlan, VesselCall
from backend.app.services.judge.rules import rule
from mcp_server.schemas import ControlEvent, PortScheduleResult, ToolError

# 조회 기간과 선명 비교 기준은 skills/port-busan/rules.md 프론트매터가 원본이다 (C6, 코드 숫자를 옮김).
# 도구 입력 스키마의 기본값이 되어야 해서 불러올 때 한 번 읽어 둔다
LOOKBACK_DAYS = rule("port_schedule_lookback_days")  # 실적을 며칠 전까지 볼지
LOOKAHEAD_DAYS = rule("port_schedule_lookahead_days")  # 입항 예정을 며칠 뒤까지 볼지
NAME_MATCH_RATIO = rule("port_schedule_name_match_ratio")  # 이 이상 닮았으면 같은 배로 본다
NAME_SEARCH_PAGES = 5  # 선명으로 찾을 때 볼 페이지 수. 부산은 하루 100건이 넘는다

make_client = MofClient  # 테스트가 fixture 클라이언트로 바꿔 끼우는 자리


def _normalize(name: str) -> str:
    """선명을 비교하기 좋게 다듬는다.

    해수부는 외국 선박을 영문으로, 국적선을 한글로 준다. ShipFinder는 영문이다.
    수입 화물은 대부분 외국 선박이라 영문끼리 비교되는데, 공백·점·하이픈이 제각각이고
    국적선은 "제203동인호"처럼 한글에 호가 붙는다. 그런 차이만 걷어낸다.
    """
    text = re.sub(r"[^0-9A-Z가-힣]", "", name.upper())
    return re.sub(r"호$", "", text)


def _by_name(records: list, ship_name: str | None) -> list:
    """선명으로 거른다. 선명만으로 조회했을 때 쓴다 (호출부호가 있으면 _same_ship이 호출부호로 먼저 거른다).

    정확히 같은 이름 → 한쪽이 다른 쪽을 품는 이름 → 많이 닮은 이름 순으로 찾는다.
    아무것도 못 찾으면 빈 목록을 돌려준다. 남의 배 입항 시각을 그 배 것처럼 답하는 쪽이
    아무 답도 없는 쪽보다 나쁘다.
    """
    if not ship_name:
        return records
    target = _normalize(ship_name)
    if not target:
        return records

    names = [(r, _normalize(r.ship_name)) for r in records]
    exact = [r for r, n in names if n == target]
    if exact:
        return exact
    partial = [r for r, n in names if n and (target in n or n in target)]
    if partial:
        return partial
    return [r for r, n in names if n and SequenceMatcher(None, target, n).ratio() >= NAME_MATCH_RATIO]


def _same_ship(records: list, call_sign: str | None, ship_name: str | None) -> list:
    """이 배의 기록만 남긴다. 호출부호로 조회했으면 호출부호가 같은 기록을 선명과 상관없이 쓴다.

    해수부는 국적선 선명을 한글로 준다(예: 테스트트윈사십팔). 세관·ShipFinder 선명은 영문이라, 호출부호로 정확히
    찾은 기록을 선명으로 다시 거르면 국적선의 입항 예정·실적이 모두 버려졌다 (데모 TESTBL48, mof_eta 없음 → partial).
    호출부호는 배마다 하나라 선명보다 정확하다. 비교 기준은 routers/agent.py _same_call_sign과 같다 (대소문자·앞뒤 공백 무시).
    호출부호가 같은 기록이 하나도 없으면(호출부호 칸이 빈 기록 등) 예전처럼 선명으로 거른다.
    선명만으로 조회했으면 지금까지와 같다 (_by_name).
    """
    if call_sign:
        wanted = call_sign.strip().upper()
        matched = [r for r in records if r.call_sign and r.call_sign.strip().upper() == wanted]
        if matched:
            return matched
    return _by_name(records, ship_name)


def _pick(calls: list[VesselCall], ship_name: str | None, call_sign: str | None = None) -> VesselCall | None:
    """실적 중 한 건. 입항 기록이 있는 것을 먼저 보고, 그중 가장 최근 입항을 쓴다.

    출항 기록만 있는 건은 "들어왔는가"라는 질문에 답하지 못하므로 뒤로 미룬다.
    """
    calls = _same_ship(calls, call_sign, ship_name)
    arrived = [c for c in calls if c.actual_arrival]
    if arrived:
        return max(arrived, key=lambda c: c.actual_arrival)
    if not calls:
        return None
    return max(calls, key=lambda c: c.reported_arrival or datetime.min.replace(tzinfo=timezone.utc))


def _pick_plan(plans: list[SailingPlan], ship_name: str | None, call_sign: str | None = None) -> SailingPlan | None:
    """예정 중 한 건. 가장 이른 입항 예정을 쓴다. 신고가 여러 번 바뀌어도 시각 기준으로 고른다.

    최종 신고는 뺀다. 입항 뒤 최종이 되면 시각이 실제 입항 시각으로 바뀌어 예정이 아니다
    (mof.py 모듈 설명, 2026-09-23 부산 실측).
    """
    plans = [p for p in _same_ship(plans, call_sign, ship_name) if p.expected_arrival]
    if not plans:
        return None
    return min(plans, key=lambda p: p.expected_arrival)


def get_port_schedule(
    call_sign: Annotated[str | None, Field(description="선박 호출부호. 예: TSTA1. get_vessel_candidates 결과의 call_sign을 그대로 넣으면 가장 정확하다")] = None,
    ship_name: Annotated[str | None, Field(description="선명. 예: TEST CARGO A. 호출부호를 모를 때 넣는다. 해수부는 국적선을 한글로 준다")] = None,
    lookback_days: Annotated[int, Field(description="실적을 며칠 전까지 볼지. 예: 3(기본값)", ge=1, le=30)] = LOOKBACK_DAYS,
    lookahead_days: Annotated[int, Field(description="입항 예정을 며칠 뒤까지 볼지. 예: 7(기본값). 0이면 예정은 보지 않는다", ge=0, le=30)] = LOOKAHEAD_DAYS,
) -> dict:
    """그 배가 부산항에 이미 들어왔는지, 언제 들어올 예정인지, 어느 부두에 대는지 해수부 기록으로 확인할 때 쓴다.

    call_sign이나 ship_name 중 하나는 반드시 준다. call_sign 쪽이 더 정확하다.
    해수부 관제정보(실제 입항·접안 실적)와 선박운항정보(입출항 신고의 입항 예정)를 합쳐 돌려준다.
    AIS 위치나 AIS ETA와 어긋날 때 어느 쪽을 쓸지는 이 도구가 정하지 않는다.
    돌려주는 값: planned_arrival(입항 예정), actual_arrival(실제 입항), facility(접안 시설),
    control_events(입항·접안·이안·출항), source, fetched_at.
    planned_arrival과 actual_arrival이 둘 다 비어 있으면 "안 온다"가 아니라
    "부산항 기록에 아직 신고도 입항도 없다"는 뜻이다.
    배의 현재 위치는 이 도구가 아니라 get_live_position으로 본다.
    """
    if not call_sign and not ship_name:
        return {"error": ToolError(code="bad_input", message="call_sign이나 ship_name 중 하나는 필요하다", retryable=False).model_dump()}

    today = date.today()
    # 호출부호가 있으면 API가 걸러 주므로 한 페이지면 된다. 선명으로 찾을 때는 뒤 페이지까지 본다
    pages = 1 if call_sign else NAME_SEARCH_PAGES
    # 클라이언트 만들기(키 없음 = bad_key)와 결과 조립까지 try 안에 둔다. 전에는 make_client()와
    # PortScheduleResult가 try 밖이라 예외가 도구 밖으로 새어 계약(C4)의 {error} 대신 MCP 오류 문장이 나갔다
    try:
        client = make_client()
        calls = client.control_records(today - timedelta(days=lookback_days), today, call_sign=call_sign, max_pages=pages)
        plans = (
            client.sailing_plans(today, today + timedelta(days=lookahead_days), call_sign=call_sign, max_pages=pages)
            if lookahead_days
            else []
        )

        fetched_at = datetime.now(timezone.utc)
        # 호출부호로 조회했으면 호출부호가 같은 기록을 선명과 상관없이 쓴다 (_same_ship)
        chosen = _pick(calls, ship_name, call_sign)
        plan = _pick_plan(plans, ship_name, call_sign)

        return PortScheduleResult(
            planned_arrival=plan.expected_arrival if plan else None,
            actual_arrival=chosen.actual_arrival if chosen else None,
            # 접안 시설은 실적이 있으면 실적 쪽을 쓴다. 예정은 바뀔 수 있다
            facility=(chosen.facility if chosen else None) or (plan.facility if plan else None),
            control_events=[ControlEvent(kind=e.kind, at=e.at, facility=e.facility) for e in (chosen.events if chosen else [])],
            fetched_at=fetched_at,
        ).model_dump(mode="json")
    except MofError as e:
        return {"error": ToolError(**e.to_dict()).model_dump()}
    except Exception as e:  # 응답 모양이 계약과 다름(ValidationError 등). 같은 응답이면 다시 불러도 같다
        return {"error": ToolError(code="bad_response", message=type(e).__name__, retryable=False).model_dump()}
