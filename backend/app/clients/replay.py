"""REPLAY_MODE 재생 transport. 외부 API 대신 evals/fixtures/replay/의 가공 응답을 돌려준다 (SDD 6.1).

채점자가 키 없이 compose up만으로 데모를 돌려 보게 하려는 장치다 (CLAUDE.md "REPLAY_MODE=true면 키 없이").
클라이언트는 그대로 두고 httpx transport만 바꿔 끼운다. 그래서 파싱·상태 코드 매핑·재시도 경로가
실제 호출과 똑같이 돈다. 테스트가 MockTransport로 fixture를 먹이는 방식과 같다.

재생하는 외부 API는 ShipFinder, 해수부, UNI-PASS다. searoute는 원래 외부 호출이 없다.
LLM은 여기서 재생하지 않는다. LLM_MODEL이 비어 있으면 services/llm.py가 replay/llm/의 녹화 답을 쓴다 (_replay_answer).

재생 파일 위치 (값은 전부 실제와 형식만 같은 가공값, SDD 7절):
  shipfinder/<엔드포인트>/<키>.json   VesselSearch는 keywords, VesselPositionSingle·VesselFlagInfo는 mmsi가 키
  mof/<API>/<호출부호>.xml            CntlVssl2(관제), VsslEtrynd5(선박운항정보). 호출부호가 없으면 _ALL.xml
  unipass/<B/L 번호>.xml              mblNo 또는 hblNo. 모의 번호만 쓴다
  positions/<MMSI>.json               워커가 6시간마다 모은 위치 이력 [{"at","lat","lng","sog"}] (라이브 데모용. position_history)
파일이 없으면 "그런 대상 없음"으로 답한다. 검색은 빈 목록, 위치·국적은 status 3, 해수부는 빈 결과, UNI-PASS는 tCnt 0.
실제 API가 모르는 배에 답하는 모양과 같아서, 라우터는 0척 되묻기 같은 평소 경로를 탄다.
"""
import json
import os
import re
from pathlib import Path

import httpx

# REPLAY_FIXTURE_DIR이 있으면 그 폴더를 읽는다 (데모용). 실제 응답을 찍어 둔 로컬 스냅숏(.local/demo_replay/<시각>/)을
# 코드 수정·커밋 없이 가리키려는 것이다. 모듈을 불러올 때 한 번 읽으므로 서버를 켜기 전에 정해 둔다.
REPLAY_DIR = Path(os.environ.get("REPLAY_FIXTURE_DIR") or Path(__file__).resolve().parents[3] / "evals" / "fixtures" / "replay")

# 엔드포인트별로 어느 파라미터가 파일 이름이 되는가
_SHIPFINDER_KEY_PARAM = {"VesselSearch": "keywords", "VesselPositionSingle": "mmsi", "VesselFlagInfo": "mmsi"}

# ShipFinder "대상 없음" 응답 (evals/fixtures/shipfinder/not_found.json과 같은 모양)
_SHIPFINDER_NOT_FOUND = '{"status": 3, "msg": "Operation target does not exist"}'

# 해수부 빈 결과 (evals/fixtures/mof/control_empty.xml과 같은 모양). 두 API가 형식을 공유한다
_MOF_EMPTY = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    "<response><header><resultCode>00</resultCode><resultMsg>NORMAL_SERVICE</resultMsg></header>"
    "<body><items/><numOfRows>50</numOfRows><pageNo>1</pageNo><totalCount>0</totalCount></body></response>"
)


# UNI-PASS 없는 B/L 응답 (evals/fixtures/unipass/not_found.xml과 같은 모양)
_UNIPASS_NOT_FOUND = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    "<cargCsclPrgsInfoQryRtnVo><ntceInfo></ntceInfo><tCnt>0</tCnt></cargCsclPrgsInfoQryRtnVo>"
)


def replay_enabled() -> bool:
    """REPLAY_MODE가 켜져 있나. .env.example 기본값은 false (C8)."""
    return os.environ.get("REPLAY_MODE", "").strip().lower() in ("1", "true", "yes")


def file_key(value: str) -> str:
    """조회 값을 파일 이름으로. 선명의 공백·점·하이픈 표기가 제각각이라 대문자와 밑줄로 맞춘다."""
    return re.sub(r"[^0-9A-Z가-힣]+", "_", value.strip().upper()).strip("_") or "_"


def _read(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.is_file() else None


def position_history(mmsi: int) -> list[dict] | None:
    """재생 폴더의 위치 이력(positions/<MMSI>.json)을 읽는다. 파일이 없으면 None (라이브 데모 10건).

    왜 필요한가: 서버는 이력을 DB(positions 표, 워커 6시간 수집)에서 읽는데, 재생 모드 서버에는 데모 배의 이력이 없다.
    그러면 부산 앞에서 30시간 멈춘 배(데모 5번)도 anchor_wait이 "정지 시간 미확인"(unknown)이 되어 긴급이 안 나온다.
    그래서 make_demo가 데모 배마다 6시간 간격 이력 파일을 쓰고, 라우터(_position_history)가 재생 모드일 때 이 파일을 먼저 본다.
    """
    body = _read(REPLAY_DIR / "positions" / f"{mmsi}.json")
    return json.loads(body) if body is not None else None


def _shipfinder_default(endpoint: str) -> httpx.Response:
    """재생 파일이 없을 때. 검색은 결과 0건, 단건 조회는 대상 없음(status 3)."""
    if endpoint == "VesselSearch":
        return httpx.Response(200, text='{"status": 0, "msg": "", "data": []}', headers={"content-type": "application/json"})
    return httpx.Response(200, text=_SHIPFINDER_NOT_FOUND, headers={"content-type": "application/json"})


def shipfinder_transport() -> httpx.MockTransport:
    """ShipFinderClient가 REPLAY_MODE일 때 쓰는 transport. 요청 경로 끝이 엔드포인트 이름이다."""

    def handle(request: httpx.Request) -> httpx.Response:
        endpoint = request.url.path.rstrip("/").split("/")[-1]
        param = _SHIPFINDER_KEY_PARAM.get(endpoint)
        value = request.url.params.get(param, "") if param else ""
        body = _read(REPLAY_DIR / "shipfinder" / endpoint / f"{file_key(value)}.json") if value else None
        if body is None:
            return _shipfinder_default(endpoint)
        return httpx.Response(200, text=body, headers={"content-type": "application/json"})

    return httpx.MockTransport(handle)


def mof_transport() -> httpx.MockTransport:
    """MofClient가 REPLAY_MODE일 때 쓰는 transport. URL의 API 이름(CntlVssl2, VsslEtrynd5)과 호출부호로 파일을 고른다.

    페이지를 넘겨도 같은 파일을 주면 목록이 중복되므로 2페이지부터는 빈 결과를 준다.
    """

    def handle(request: httpx.Request) -> httpx.Response:
        parts = request.url.path.strip("/").split("/")
        api = parts[-2] if len(parts) >= 2 else "_"
        if request.url.params.get("pageNo", "1") != "1":
            return httpx.Response(200, text=_MOF_EMPTY)
        call_sign = request.url.params.get("clsgn")
        name = file_key(call_sign) if call_sign else "_ALL"
        body = _read(REPLAY_DIR / "mof" / api / f"{name}.xml")
        return httpx.Response(200, text=body if body is not None else _MOF_EMPTY)

    return httpx.MockTransport(handle)


def unipass_transport() -> httpx.MockTransport:
    """UnipassClient가 REPLAY_MODE일 때 쓰는 transport. B/L 번호(mblNo 또는 hblNo)로 파일을 고른다.

    파일이 없으면 tCnt 0(없는 B/L)으로 답한다. 라우터는 insufficient로 B/L 확인을 되묻는다 (SDD 4.1).
    재생 파일에도 실제 B/L 번호는 쓰지 않는다. TESTBL01 같은 모의 번호만 쓴다 (CLAUDE.md).
    """

    def handle(request: httpx.Request) -> httpx.Response:
        mbl, hbl = request.url.params.get("mblNo"), request.url.params.get("hblNo")
        bl_no = mbl or hbl or ""
        body = None
        if bl_no:
            # 구분별 파일(<번호>.mbl.xml / <번호>.hbl.xml)을 먼저 본다. 실제 UNI-PASS는 마스터·하우스 번호가 서로 달라
            # 같은 번호를 다른 구분으로 부르면 "없음"이 온다. 구분 없는 <번호>.xml은 예전처럼 둘 다에 답한다
            kind = "mbl" if mbl else "hbl"
            key = file_key(bl_no)
            body = _read(REPLAY_DIR / "unipass" / f"{key}.{kind}.xml") or _read(REPLAY_DIR / "unipass" / f"{key}.xml")
        return httpx.Response(200, text=body if body is not None else _UNIPASS_NOT_FOUND)

    return httpx.MockTransport(handle)
