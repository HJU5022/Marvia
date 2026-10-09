"""평가셋 한 문항의 fixtures를 REPLAY_MODE 재생 파일 묶음으로 바꾼다 (D7·D8 공용).

왜 필요한가:
  dataset.jsonl의 fixtures는 사람이 읽기 쉽게 요약한 모양이다 (C7, evals/schema.py).
  서버의 REPLAY_MODE(backend/app/clients/replay.py)는 실제 API 응답과 같은 모양의 파일을 폴더에서 읽는다.
  이 파일이 둘 사이를 잇는다. 문항마다 폴더 하나를 만들어 두고 replay.REPLAY_DIR를 그 폴더로 바꿔 끼우면,
  서버 코드를 고치지 않고 실제 요청과 같은 경로(클라이언트 파싱·식별·신호 계산)로 문항을 돌릴 수 있다.

만드는 파일 (이름 규칙은 evals/fixtures/replay/README.md):
  unipass/<B/L>.xml                                 UNI-PASS 화물통관진행정보
  shipfinder/VesselSearch/<검색어>.json             선명과 호출부호 둘 다 (도구가 호출부호로도 검색한다)
  shipfinder/VesselPositionSingle/<MMSI>.json       위치
  shipfinder/VesselFlagInfo/<MMSI>.json             국적
  mof/VsslEtrynd5/<호출부호>.xml, _ALL.xml          선박운항정보(입항 예정). _ALL은 MRN으로 훑을 때 쓴다
  mof/CntlVssl2/<호출부호>.xml, _ALL.xml            관제정보(입항 실적)

값은 전부 fixtures에 있는 가공값 그대로다. 실제 응답 원본은 쓰지 않는다 (CLAUDE.md).

실패 문항:
  위치 조회가 에러 응답(F04 권한 없음 {"status": 21, ...})이면 그 응답을 그대로 파일로 쓴다.
  타임아웃(F02)은 응답이 안 오는 것이라 파일로 흉내 낼 수 없다. TIMEOUT_MARKER를 파일에 쓰고,
  use_error_replay()가 평가 동안만 ShipFinder 재생 transport를 감싸 그 파일을 만나면 타임아웃 예외를 낸다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from xml.sax.saxutils import escape

import httpx

from backend.app.clients import shipfinder as shipfinder_client
from backend.app.clients.replay import file_key, shipfinder_transport

# 평가셋 UNI-PASS 단계 값에 붙은 표시. 실제 단계 이름에는 없으므로 떼고 쓴다 (예: "검사지정(평가용 요약)")
SUMMARY_MARK = "(평가용 요약)"
# 이 내용의 재생 파일을 만나면 타임아웃을 낸다 (use_error_replay). 실제 API 응답에는 없는 모양이다
TIMEOUT_MARKER = '{"_replay": "timeout"}'
# 해수부 오류 응답 견본 (공식 오류 형식과 같은 모양의 가공값). sailing_plan_errors가 있을 때만 쓴다 (_write_mof)
MOF_ERROR_SAMPLE = Path(__file__).resolve().parent / "fixtures" / "mof" / "invalid_parameter.xml"


def use_error_replay() -> None:
    """ShipFinder 재생 transport를 감싸서 TIMEOUT_MARKER 파일이면 타임아웃 예외를 내게 한다.

    평가 실행기에서만 부른다. 서버 코드(clients/replay.py)는 고치지 않는다.
    shipfinder.py가 shipfinder_transport를 이름으로 가져다 쓰므로 그 자리를 바꿔 끼운다.
    클라이언트는 실제 타임아웃과 같은 예외를 받아 같은 재시도·실패 경로를 탄다.
    """
    def transport() -> httpx.MockTransport:
        inner = shipfinder_transport()

        def handle(request: httpx.Request) -> httpx.Response:
            response = inner.handle_request(request)
            if response.read().decode() == TIMEOUT_MARKER:
                raise httpx.ReadTimeout("replay: 평가셋이 타임아웃으로 정한 호출", request=request)
            return response

        return httpx.MockTransport(handle)

    shipfinder_client.shipfinder_transport = transport


def write_replay_files(record: dict, out_dir: Path) -> None:
    """문항 하나(dataset.jsonl 한 줄을 dict로 읽은 것)의 재생 파일을 out_dir 아래에 쓴다."""
    fixtures = record["fixtures"]
    _write_unipass(record["request"]["bl_no"], fixtures.get("unipass") or {}, out_dir)
    _write_shipfinder(fixtures.get("shipfinder") or {}, out_dir)
    _write_mof(fixtures.get("mof") or {}, out_dir)
    _write_positions(fixtures, out_dir)


def _write_positions(fixtures: dict, out_dir: Path) -> None:
    """워커 위치 이력(worker_positions)을 positions/<MMSI>.json으로 쓴다 (라이브 데모).

    서버는 재생 모드에서 이 파일을 DB 이력 대신 읽어 anchor_wait의 정지 시간을 잰다 (clients/replay.position_history).
    worker_positions는 두 모양이다. 리스트면 shipfinder.position의 배 한 척 것(평가셋 모양), 딕셔너리면 {MMSI: 리스트}(배 여러 척, 라이브 데모).
    이력이 비어 있으면 파일을 만들지 않는다. 파일이 없는 배는 서버가 DB 길로 가서 지금까지와 같다."""
    history = fixtures.get("worker_positions") or []
    if isinstance(history, list):
        mmsi = ((fixtures.get("shipfinder") or {}).get("position") or {}).get("mmsi")
        history = {str(mmsi): history} if mmsi and history else {}
    for mmsi, rows in history.items():
        if rows:
            _write(out_dir / "positions" / f"{mmsi}.json", json.dumps(rows, ensure_ascii=False))


# ── UNI-PASS ────────────────────────────────────────────────

def _write_unipass(bl_no: str, u: dict, out_dir: Path) -> None:
    """요약값을 UNI-PASS XML로. tCnt 0(없는 B/L)이면 파일을 만들지 않는다.
    파일이 없으면 replay가 "없는 B/L"로 답한다 (replay.py _UNIPASS_NOT_FOUND).

    추가분 (라이브 데모 10건, evals/fixtures/demo_live.jsonl): 요약 칸 말고도 실제 API001 응답처럼 상단 칸(UNIPASS_EXTRA)과
    컨테이너 번호(cntrNo 리스트), 처리 이력 줄(history 리스트, 최신이 위)을 쓸 수 있다. 평가셋 문항에는 이 칸들이 없어 재생 파일이 전과 같다."""
    if not u or u.get("tCnt") == 0:
        return
    stage = (u.get("prgsStts") or "").replace(SUMMARY_MARK, "").strip()
    fields = {
        # 이력 줄이 없으면 서버는 csclPrgsStts를 단계 이름으로 쓴다 (services/judge/customs.py FIELD_CANDIDATES)
        "csclPrgsStts": u.get("csclPrgsStts") or stage,
        "prgsStts": stage,
        "cargMtNo": u.get("cargMtNo"),
        "shipNm": u.get("shipNm"),
        "shipNat": u.get("shipNat"),
        "etprDt": u.get("etprDt"),
        "etprCstm": u.get("cstmNm"),
        "dsprCd": u.get("dsprCd"),  # 양륙항. 부산(KRPUS)이 아니면 서버가 unsupported로 끝낸다 (F05)
        "shedNm": u.get("shedNm"),
        # 적재항 코드·이름 (서류 대조 데모 evals/fixtures/demo_papers.jsonl용).
        # 평가셋 문항에는 이 칸이 없어 아래 빈 값 걸러내기로 빠진다. 그래서 평가셋 재생 파일은 전과 같다
        "ldprCd": u.get("ldprCd"),
        "ldprNm": u.get("ldprNm"),
    }
    body = "".join(f"<{tag}>{escape(str(value))}</{tag}>" for tag, value in fields.items() if value)
    # 라이브 데모 칸. 값이 ""여도 태그는 쓴다(실제 응답도 빈 칸을 빈 태그로 준다. 예: 포워더가 비어 오는 화물)
    body += "".join(f"<{tag}>{escape(str(u[tag]))}</{tag}>" for tag in UNIPASS_EXTRA if u.get(tag) is not None)
    body += "".join(f"<cntrNo>{escape(no)}</cntrNo>" for no in u.get("cntrNo") or [])  # 컨테이너 여러 개면 태그가 여러 개 (customs._join_all)
    rows = "".join(_history_row(r) for r in u.get("history") or [])
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f"<cargCsclPrgsInfoQryRtnVo><ntceInfo></ntceInfo><cargCsclPrgsInfoQryVo>{body}</cargCsclPrgsInfoQryVo>"
        f"<tCnt>{len(u.get('history') or []) or 1}</tCnt>{rows}</cargCsclPrgsInfoQryRtnVo>"
    )
    _write(out_dir / "unipass" / f"{file_key(bl_no)}.xml", xml)


# 라이브 데모가 쓰는 API001 상단 칸 (연계가이드 v4.1, evals/fixtures/unipass/progress_ok.xml 순서). 서버는 이 중 일부만 읽고 나머지는 실제 응답 모양을 맞추려고 둔다
UNIPASS_EXTRA = ("prgsStCd", "mblNo", "hblNo", "shipNatNm", "vydf", "etprCstm", "lodCntyCd", "dsprNm", "prnm", "ttwg", "wghtUt",
                 "cargTp", "rlseDtyPridPassTpcd", "dclrDelyAdtxYn", "cntrGcnt", "shcoFlcoSgn", "shcoFlco", "frwrSgn", "frwrEntsConm")
# 이력 한 줄의 13칸 (services/judge/customs.py DETAIL_FIELDS와 같은 이름). 실제 응답처럼 빈 칸도 빈 태그로 쓴다
HISTORY_TAGS = ("cargTrcnRelaBsopTpcd", "prcsDttm", "dclrNo", "rlbrDttm", "rlbrBssNo", "rlbrCn", "bfhnGdncCn", "shedNm", "shedSgn",
                "pckGcnt", "pckUt", "wght", "wghtUt")


def _history_row(row: dict) -> str:
    return "<cargCsclPrgsInfoDtlQryVo>" + "".join(f"<{t}>{escape(str(row.get(t) or ''))}</{t}>" for t in HISTORY_TAGS) + "</cargCsclPrgsInfoDtlQryVo>"


# ── ShipFinder ──────────────────────────────────────────────

def _write_shipfinder(s: dict, out_dir: Path) -> None:
    """검색 결과·위치·국적을 ShipFinder 응답 모양({"status": 0, "data": ...})으로 감싼다.
    평가셋의 search·position 항목은 실제 응답의 data 칸과 같은 키를 쓴다 (evals/fixtures/shipfinder/ 견본과 대조)."""
    hits = s.get("search") or []
    search = json.dumps({"status": 0, "msg": "", "total": len(hits), "data": hits}, ensure_ascii=False)
    # 도구는 선명으로도, 호출부호로도 검색한다 (mcp_server/tools/vessel_candidates.py). 같은 결과를 두 이름으로 둔다
    for key in {h.get("ship_name") for h in hits} | {h.get("call_sign") for h in hits}:
        if key:
            _write(out_dir / "shipfinder" / "VesselSearch" / f"{file_key(key)}.json", search)

    # 위치: 한 척이면 position, 동명 선박 문항은 positions에 여러 척
    positions = dict(s.get("positions") or {})
    position = s.get("position")
    if position and "error" in position:
        # 실패 문항. 에러 칸에는 MMSI가 없으므로 검색 결과의 배로 둔다 (F02·F04는 검색 1척)
        _write(out_dir / "shipfinder" / "VesselPositionSingle" / f"{hits[0]['mmsi']}.json", _position_error(position["error"]))
    elif position:
        positions[str(position["mmsi"])] = position
    for mmsi, pos in positions.items():
        _write(out_dir / "shipfinder" / "VesselPositionSingle" / f"{mmsi}.json",
               json.dumps({"status": 0, "msg": "", "data": pos}, ensure_ascii=False))

    for mmsi, country in (s.get("flag") or {}).items():
        _write(out_dir / "shipfinder" / "VesselFlagInfo" / f"{mmsi}.json",
               json.dumps({"status": 0, "msg": "", "data": {"registry": country}}, ensure_ascii=False))


def _position_error(error) -> str:
    """위치 조회 실패 응답. "timeout"이면 표시만 쓰고(use_error_replay가 예외로 바꾼다),
    {"status": 21, ...}처럼 ShipFinder 에러 본문이면 그대로 쓴다 (evals/fixtures/shipfinder/no_permission.json과 같은 모양)."""
    if error == "timeout":
        return TIMEOUT_MARKER
    return json.dumps(error, ensure_ascii=False)


# ── 해수부 ──────────────────────────────────────────────────

def _write_mof(m: dict, out_dir: Path) -> None:
    """평가셋은 신고·실적을 한 줄씩 평평하게 적었다. 실제 API는 배(item)마다 detail을 묶는다.
    호출부호별로 묶어 두 API 모양으로 쓴다. 호출부호 없이 부르면 _ALL.xml(전체)을 읽는다 (replay.py).

    추가분 (서류 대조 데모용, 평가셋 문항에는 없는 칸이라 평가셋 재생 파일은 전과 같다):
      - prvsDpmprtPrtNm: 직전 기항지. 실제 API처럼 item 칸에 둔다 (clients/mof.py _to_plan)
      - sailing_plan_errors: 호출부호 목록. 그 호출부호의 선박운항정보 조회를 해수부 오류 응답으로 만든다"""
    plans = _group(m.get("arrival_reports") or [], ("vsslNm", "vsslNltyCd", "prvsDpmprtPrtNm"),
                   lambda r: {"reqstSeNm": r.get("reqstSeNm"), "etryndNm": "입항", "etryptDt": r.get("etryptDt"),
                              "laidupFcltyNm": r.get("laidupFcltyNm"), "mrNum": r.get("mrNum")})
    calls = _group(m.get("control_events") or [], (),
                   lambda r: {"cntrlNm": r.get("cntrlNm"), "cntrlOpertDt": r.get("cntrlOpertDt"),
                              "fcltyNm": r.get("fcltyNm")})
    for api, items in (("VsslEtrynd5", plans), ("CntlVssl2", calls)):
        for call_sign, item in items.items():
            _write(out_dir / "mof" / api / f"{file_key(call_sign)}.xml", _mof_xml([item]))
        _write_all(out_dir / "mof" / api / "_ALL.xml", list(items.values()))
    # 해수부 오류 응답은 evals/fixtures/mof/invalid_parameter.xml 견본을 그대로 쓴다 (resultCode가 00이 아니면
    # clients/mof.py가 MofError를 낸다). _ALL.xml에는 넣지 않는다: 그 호출부호로 부를 때만 실패한다
    for call_sign in m.get("sailing_plan_errors") or []:
        _write(out_dir / "mof" / "VsslEtrynd5" / f"{file_key(call_sign)}.xml", MOF_ERROR_SAMPLE.read_text(encoding="utf-8"))


def _write_all(path: Path, items: list[str]) -> None:
    """호출부호 없이 부를 때 읽는 전체 목록(_ALL.xml)을 쓴다. 이미 있으면 그 안의 item 뒤에 이어 붙인다.

    전에는 문항마다 덮어써서 마지막에 쓴 문항 것만 남았다 (scripts/demo/make_demo.py 머리 주석 "N01이 마지막이어야"). 한 폴더에
    여러 문항을 쓰는 서버 데모(13건)에서는 MRN으로 훑는 조회(identify_mrn)가 앞에 쓴 문항의 배를 못 찾았다.
    같은 item 글자는 한 번만 넣는다. 평가 실행기는 문항마다 새 폴더라 이어 붙일 것이 없어 결과가 전과 같다."""
    old = re.findall(r"<item>.*?</item>", path.read_text(encoding="utf-8"), re.S) if path.is_file() else []
    _write(path, _mof_xml(old + [i for i in items if i not in old]))


def _group(rows: list[dict], item_keys: tuple[str, ...], detail) -> dict[str, str]:
    """호출부호별로 item XML 조각을 만든다. item_keys는 item 칸으로 올릴 값, detail은 한 줄을 detail로 바꾸는 함수."""
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row.get("clsgn") or "", []).append(row)
    items = {}
    for call_sign, group in grouped.items():
        head = {"prtAgCd": "020", "clsgn": call_sign, **{k: group[0].get(k) for k in item_keys}}
        details = "".join(f"<detail>{_tags(detail(r))}</detail>" for r in group)
        items[call_sign] = f"<item>{_tags(head)}<details>{details}</details></item>"
    return items


def _mof_xml(items: list[str]) -> str:
    """해수부 두 API가 같이 쓰는 응답 틀 (evals/fixtures/mof/ 견본과 같은 모양)."""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        "<response><header><resultCode>00</resultCode><resultMsg>NORMAL_SERVICE</resultMsg></header>"
        f"<body><items>{''.join(items)}</items><numOfRows>50</numOfRows><pageNo>1</pageNo>"
        f"<totalCount>{len(items)}</totalCount></body></response>"
    )


def _tags(values: dict) -> str:
    """{"a": 1} → "<a>1</a>". 빈 값은 칸을 만들지 않는다 (실제 응답도 빈 칸이 빠지곤 한다)."""
    return "".join(f"<{k}>{escape(str(v))}</{k}>" for k, v in values.items() if v not in (None, ""))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
