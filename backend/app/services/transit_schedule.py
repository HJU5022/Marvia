"""역의 첫차·막차. 서울 열린데이터광장 지하철 API. (SDD 6절 first_last_train)

바깥 호출은 services/ 에만 둔다 (BACKEND_GUIDE). geo.py·routes.py 와 같은 결로 쓴다.
MCP 도구 mcp_server/tools/first_last_train.py 가 이 파일의 first_last_seoul 을 감싼다.

왜 두 번 부르나 (SDD 6절 "역명→역코드 API 선행"):
  첫차·막차 API 는 역 이름을 받지 않고 내부 코드(STATION_CD, 예: 서울역 1호선 0150)를 받는다.
  외부 코드(FR_CODE, 133)를 넣으면 "데이터 없음"이 온다 (09-18 실측). 그래서 역 정보 API 로 코드를 먼저 얻는다.

API 두 개 (둘 다 http://openapi.seoul.go.kr:8088/{KEY}/json/{서비스}/{시작}/{끝}/...):
  SearchSTNBySubwayLineInfo/1/N/ /{역이름}          → 부분 일치 목록. STATION_CD·LINE_NUM("01호선")·FR_CODE
  SearchFirstAndLastTrainbyLineServiceNew/1/N/{호선}/{상하행}/{요일}/{STATION_CD}
                                                      → FSTT_HRM("052030")·LSTTM_HRM("244800")·행선지
  칸 순서는 호선 → 상하행(1 상행·2 하행) → 요일(1 평일·2 토·3 휴일) → 역코드다. 요일과 상하행을 바꿔 넣으면
  에러 없이 다른 답이 오므로 주의 (09-21 실측으로 순서 확정).

시각은 "HHMMSS" 6자리. 자정 넘는 막차는 24시·25시로 이어 센다 ("244800" = 24:48). 그대로 "HH:MM" 으로 자른다.
부산(SDD: 부산교통공사 API)은 공공데이터포털 활용신청 승인 뒤 붙인다. 지금은 서울만.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

SEOUL_BASE = "http://openapi.seoul.go.kr:8088"
TIMEOUT_SEC = 8.0
STATION_SEARCH_SIZE = 20  # 같은 이름이 호선마다 따로 나온다 (서울역: 1·4·경의선·GTX)

WEEKDAY_TAG = {"weekday": "1", "sat": "2", "holiday": "3"}
DIRECTION_TAG = {"up": "1", "down": "2"}


class ScheduleFailed(RuntimeError):
    """첫차·막차를 구하지 못했다. 역을 못 찾았거나 API 가 데이터 없음이라 했다."""


def _key() -> str:
    key = os.environ.get("SEOUL_OPENDATA_KEY")
    if not key:
        raise ScheduleFailed("SEOUL_OPENDATA_KEY 가 없습니다")
    return key


async def _seoul_get(client: httpx.AsyncClient, service: str, *segments: str) -> list[dict[str, Any]]:
    """열린데이터광장 호출 한 번. 결과 코드가 INFO-000 이 아니면 예외. 빈 결과는 빈 목록."""
    url = "/".join([SEOUL_BASE, _key(), "json", service, *segments])
    res = await client.get(url)
    res.raise_for_status()
    data = res.json()
    # 키가 틀리면 최상위에 RESULT 만 온다. 정상이면 {서비스명: {RESULT, row}} 다.
    if service not in data:
        msg = data.get("RESULT", {}).get("MESSAGE", "알 수 없는 응답")
        raise ScheduleFailed(f"서울 열린데이터광장: {msg}")
    body = data[service]
    code = body.get("RESULT", {}).get("CODE", "")
    if code == "INFO-200":  # 해당하는 데이터가 없습니다
        return []
    if code != "INFO-000":
        raise ScheduleFailed(f"서울 열린데이터광장 {code}: {body.get('RESULT', {}).get('MESSAGE', '')}")
    return body.get("row", [])


def _line_label(line: str) -> str:
    """"4" → "04호선". 역 정보 API 의 LINE_NUM 표기에 맞춘다. SDD 는 1~9호선만 다룬다."""
    return f"{int(line):02d}호선"


async def find_station(client: httpx.AsyncClient, name: str, line: str) -> dict[str, Any]:
    """역 이름 + 호선 → 역 한 건. 이름은 "서울역"·"서울"·"사당"처럼 온다.

    API 는 부분 일치라 "서울"에 서울대입구도 나온다. 그래서 호선으로 먼저 거르고, 그 안에서
    이름이 정확히 같은 것 → "역"을 뗀 것이 같은 것 → 첫 것 순으로 고른다.
    """
    rows = await _seoul_get(client, "SearchSTNBySubwayLineInfo", "1", str(STATION_SEARCH_SIZE), " ", name)
    same_line = [r for r in rows if r.get("LINE_NUM") == _line_label(line)]
    if not same_line:
        raise ScheduleFailed(f"'{name}' 역을 {int(line)}호선에서 찾지 못했습니다")
    bare = name.rstrip("역")
    for pick in (
        lambda r: r["STATION_NM"] == name,
        lambda r: r["STATION_NM"].rstrip("역") == bare,
    ):
        hit = next((r for r in same_line if pick(r)), None)
        if hit:
            return hit
    return same_line[0]


def _hhmm(hhmmss: str) -> str:
    """"052030" → "05:20". 6자리가 아니면 그대로 돌려준다 (API 가 바뀌어도 죽지 않게)."""
    return f"{hhmmss[:2]}:{hhmmss[2:4]}" if len(hhmmss) == 6 and hhmmss.isdigit() else hhmmss


async def first_last_seoul(
    client: httpx.AsyncClient, station_name: str, line: str, weekday: str, direction: str
) -> dict[str, Any]:
    """서울 지하철 한 역의 첫차·막차. 돌려주는 것:
        {"first": "05:20", "last": "24:48", "line": "1", "first_to": "동두천", "last_to": "동묘앞"}
    first_to·last_to 는 그 열차의 행선지. 막차가 종점까지 안 가는 경우가 있어 현장에선 이게 중요하다.
    """
    if weekday not in WEEKDAY_TAG:
        raise ScheduleFailed(f"weekday 는 {list(WEEKDAY_TAG)} 중 하나여야 합니다")
    if direction not in DIRECTION_TAG:
        raise ScheduleFailed(f"direction 은 {list(DIRECTION_TAG)} 중 하나여야 합니다")

    station = await find_station(client, station_name, line)
    rows = await _seoul_get(
        client,
        "SearchFirstAndLastTrainbyLineServiceNew",
        "1",
        "5",
        str(int(line)),
        DIRECTION_TAG[direction],
        WEEKDAY_TAG[weekday],
        station["STATION_CD"],
    )
    if not rows:
        raise ScheduleFailed(f"{station['STATION_NM']} {int(line)}호선 {direction} {weekday} 시각표가 없습니다")
    row = rows[0]
    return {
        "first": _hhmm(row["FSTT_HRM"]),
        "last": _hhmm(row["LSTTM_HRM"]),
        "line": str(int(line)),
        "first_to": row.get("FSTT_ARVL_STTN", ""),
        "last_to": row.get("LSTTM_ARVL_STTN", ""),
    }
