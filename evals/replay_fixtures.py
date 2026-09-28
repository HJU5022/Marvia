"""평가셋 한 문항의 fixtures를 REPLAY_MODE 재생 파일 묶음으로 바꾼다 (D7·D8 공용, 09-28).

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
"""
from __future__ import annotations

import json
from pathlib import Path
from xml.sax.saxutils import escape

from backend.app.clients.replay import file_key

# 평가셋 UNI-PASS 단계 값에 붙은 표시. 실제 단계 이름에는 없으므로 떼고 쓴다 (예: "검사지정(평가용 요약)")
SUMMARY_MARK = "(평가용 요약)"


def write_replay_files(record: dict, out_dir: Path) -> None:
    """문항 하나(dataset.jsonl 한 줄을 dict로 읽은 것)의 재생 파일을 out_dir 아래에 쓴다."""
    fixtures = record["fixtures"]
    _write_unipass(record["request"]["bl_no"], fixtures.get("unipass") or {}, out_dir)
    _write_shipfinder(fixtures.get("shipfinder") or {}, out_dir)
    _write_mof(fixtures.get("mof") or {}, out_dir)


# ── UNI-PASS ────────────────────────────────────────────────

def _write_unipass(bl_no: str, u: dict, out_dir: Path) -> None:
    """요약값을 UNI-PASS XML로. tCnt 0(없는 B/L)이면 파일을 만들지 않는다.
    파일이 없으면 replay가 "없는 B/L"로 답한다 (replay.py _UNIPASS_NOT_FOUND)."""
    if not u or u.get("tCnt") == 0:
        return
    stage = (u.get("prgsStts") or "").replace(SUMMARY_MARK, "").strip()
    fields = {
        # 이력 줄이 없으면 서버는 csclPrgsStts를 단계 이름으로 쓴다 (services/customs.py FIELD_CANDIDATES)
        "csclPrgsStts": stage,
        "prgsStts": stage,
        "cargMtNo": u.get("cargMtNo"),
        "shipNm": u.get("shipNm"),
        "shipNat": u.get("shipNat"),
        "etprDt": u.get("etprDt"),
        "etprCstm": u.get("cstmNm"),
        "shedNm": u.get("shedNm"),
    }
    body = "".join(f"<{tag}>{escape(str(value))}</{tag}>" for tag, value in fields.items() if value)
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f"<cargCsclPrgsInfoQryRtnVo><ntceInfo></ntceInfo><cargCsclPrgsInfoQryVo>{body}</cargCsclPrgsInfoQryVo>"
        "<tCnt>1</tCnt></cargCsclPrgsInfoQryRtnVo>"
    )
    _write(out_dir / "unipass" / f"{file_key(bl_no)}.xml", xml)


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
    if s.get("position") and "mmsi" in s["position"]:
        positions[str(s["position"]["mmsi"])] = s["position"]
    for mmsi, pos in positions.items():
        _write(out_dir / "shipfinder" / "VesselPositionSingle" / f"{mmsi}.json",
               json.dumps({"status": 0, "msg": "", "data": pos}, ensure_ascii=False))

    for mmsi, country in (s.get("flag") or {}).items():
        _write(out_dir / "shipfinder" / "VesselFlagInfo" / f"{mmsi}.json",
               json.dumps({"status": 0, "msg": "", "data": {"registry": country}}, ensure_ascii=False))


# ── 해수부 ──────────────────────────────────────────────────

def _write_mof(m: dict, out_dir: Path) -> None:
    """평가셋은 신고·실적을 한 줄씩 평평하게 적었다. 실제 API는 배(item)마다 detail을 묶는다.
    호출부호별로 묶어 두 API 모양으로 쓴다. 호출부호 없이 부르면 _ALL.xml(전체)을 읽는다 (replay.py)."""
    plans = _group(m.get("arrival_reports") or [], ("vsslNm", "vsslNltyCd"),
                   lambda r: {"reqstSeNm": r.get("reqstSeNm"), "etryndNm": "입항", "etryptDt": r.get("etryptDt"),
                              "laidupFcltyNm": r.get("laidupFcltyNm"), "mrNum": r.get("mrNum")})
    calls = _group(m.get("control_events") or [], (),
                   lambda r: {"cntrlNm": r.get("cntrlNm"), "cntrlOpertDt": r.get("cntrlOpertDt"),
                              "fcltyNm": r.get("fcltyNm")})
    for api, items in (("VsslEtrynd5", plans), ("CntlVssl2", calls)):
        for call_sign, item in items.items():
            _write(out_dir / "mof" / api / f"{file_key(call_sign)}.xml", _mof_xml([item]))
        _write(out_dir / "mof" / api / "_ALL.xml", _mof_xml(list(items.values())))


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
