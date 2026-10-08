"""라이브 시연 데모 10건 테스트. evals/fixtures/demo_live.jsonl을 키 없이 실제 요청 경로로 돌린다.

scripts/demo/make_demo.build_all이 쓴 재생 파일로 routers/agent.run_agent를 부른다 (test_demo_papers.py와 같은 방식).
판정 LLM은 쓰지 않는다. 평가 (a) 규칙만과 같이 llm.judge·llm.pick_vessel 자리에 evals/baseline_rules를 끼운다.
그래서 이 테스트가 보는 것은 코드의 몫이다: 1층 신호, 판정 표 등급(services/judge/verdict.table_verdict), 선박 식별, 품명·컨테이너 파싱.
(LLM이 쓰는 설명 문장은 여기서 안 본다. 등급은 회색 지대가 아니면 LLM이 못 바꾼다, routers/agent.py)

기준 시각을 셋으로 돌린다 (한국 시각 낮, 자정 직전, 자정 직후). make_demo가 시각을 옮기면 날짜 칸이 어긋나기 쉬운 시간대라서다.
여유 일수와 동명 선박 서류 대조(세관 입항일 = 해수부 입항 신고 날짜)가 어느 시각에 만들어도 같게 나와야 한다 (scripts/demo/demo_live.finalize).
재생 폴더는 tmp_path에 만든다. 레포의 evals/fixtures/replay/는 건드리지 않는다.
값은 전부 모의값이다 (DEMO B/L·선박, MMSI 440999201~211, 호출부호 DMO, 컨테이너 소유자 DEM, CLAUDE.md).
"""
import json
import re
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree

import pytest
from freezegun import freeze_time

from backend.app.clients import replay
from backend.app.clients.shipfinder import ShipFinderClient
from backend.app.services.judge import verdict
from backend.app.services.judge.evidence import KST
from evals import baseline_rules
from scripts.demo import demo_live, make_demo

ROOT = Path(__file__).resolve().parents[3]
RECORDING = ROOT / "evals" / "fixtures" / "replay" / "llm" / "marvia-judge.json"
CASES = make_demo.load_live()
# 키·DB·MCP 서버 없이 돈다 (test_demo_papers.py와 같은 목록)
KEYS = ("LLM_MODEL", "OPENROUTER_API_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY",
        "DATABASE_URL", "SHIPFINDER_KEY", "UNIPASS_KEY", "DATA_GO_KR_KEY", "MCP_URL")
FREEZE_IGNORE = ["langfuse", "opentelemetry", "google.auth"]  # evals/run_eval.py와 같다. 트레이스·토큰은 진짜 시각을 쓴다
NOWS = {
    "noon": datetime(2026, 10, 8, 3, 5, tzinfo=timezone.utc),       # 한국 10-08 12:05
    "before_midnight": datetime(2026, 10, 8, 14, 50, tzinfo=timezone.utc),  # 한국 10-08 23:50
    "after_midnight": datetime(2026, 10, 8, 15, 10, tzinfo=timezone.utc),   # 한국 10-09 00:10
}


@pytest.fixture(scope="module", params=list(NOWS), ids=list(NOWS))
def demo(request, tmp_path_factory):
    """기준 시각마다 재생 파일을 한 번 만든다. 서버처럼 라이브 10건과 평가셋 3건을 한 폴더에 쓴 상태로 돌린다."""
    now, out = NOWS[request.param], tmp_path_factory.mktemp("replay")
    with pytest.MonkeyPatch.context() as mp:
        for key in KEYS:
            mp.delenv(key, raising=False)
        mp.setenv("REPLAY_MODE", "true")
        mp.setenv("HTTP_BACKOFF_SEC", "0")
        mp.setattr(replay, "REPLAY_DIR", out)
        (out / "llm").mkdir()
        shutil.copy(RECORDING, out / "llm" / RECORDING.name)
        three, live = make_demo.build_all(now, out)
        yield {"now": now, "out": out, "three": {g["case_id"]: g for g in three}, "live": {g["case_id"]: g for g in live}}
    ShipFinderClient.cache.clear()


def _ask(demo: dict, case: dict, monkeypatch, pick=None, **extra):
    """문항 하나를 실제 요청 경로로 묻는다. 판정 LLM 자리에 규칙만 끼우고, 계산된 신호를 엿본다. (응답, 신호 묶음)을 돌려준다.
    pick: 선박 선택 LLM 자리에 끼울 함수. 없으면 규칙 베이스라인(맨 앞 후보)이다."""
    from backend.app.routers import agent
    from backend.app.schemas.agent import AgentRequest

    seen = []
    real_compute = agent.signals_service.compute

    def spy(*args, **kwargs):
        seen.append(real_compute(*args, **kwargs))
        return seen[-1]

    monkeypatch.setattr(agent.signals_service, "compute", spy)
    monkeypatch.setattr(agent.llm, "judge", baseline_rules.judge)
    monkeypatch.setattr(agent.llm, "pick_vessel", pick or baseline_rules.pick_vessel)
    ShipFinderClient.cache.clear()
    guide = demo["live"][case["id"]]
    request = AgentRequest(bl_no=guide["bl_no"], bl_type="HOUSE", session_id=f"t-{case['id']}",
                           sale_due_date=guide["sale_due_date"], **extra)
    with freeze_time(demo["now"], tick=True, ignore=FREEZE_IGNORE):
        response = agent.run_agent(request)
    return response, (seen[-1] if seen else None)


def _iso6346_ok(number: str) -> bool:
    """컨테이너 번호 검사숫자를 빌더(demo_live.container_no)와 따로 다시 계산한다.
    글자값은 A=10부터 시작하고 11의 배수(11, 22, 33)는 건너뛴다. 앞 10글자 값에 2의 i제곱을 곱해 더하고 11로 나눈 나머지(10이면 0)가 검사숫자다."""
    if not re.fullmatch(r"[A-Z]{3}U\d{7}", number):
        return False
    values, value = {}, 10
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        value += value % 11 == 0
        values[letter] = value
        value += 1
    total = sum((values[c] if c.isalpha() else int(c)) << i for i, c in enumerate(number[:10]))
    return total % 11 % 10 == int(number[10])


def test_iso6346_known_example():
    # 공개된 ISO 6346 설명의 예(CSQU3054383, 검사숫자 3)로 검사 함수 자체를 확인한다. 소유자 코드가 DEM이 아니라 모의 컨테이너 번호는 아니다
    assert _iso6346_ok("CSQU3054383") and not _iso6346_ok("CSQU3054384")


def test_jsonl_matches_specs():
    # demo_live.jsonl은 SPECS를 펼친 결과다. SPECS만 고치고 파일을 안 다시 쓰면 서버 데모가 옛 값을 쓴다
    assert demo_live.OUTPUT.read_text(encoding="utf-8") == demo_live.render()


def test_ten_cases_marked_as_mock():
    assert [c["request"]["bl_no"] for c in CASES] == [f"DEMO{code}26100{n:02d}" for n, code in
                                                      enumerate(["QD", "SH", "NB", "HC", "TJ", "DL", "KH", "HP", "SH", "QD"], start=1)]
    assert all(c["category"] == "demo_live" and c["labeler"] is None for c in CASES)
    text = demo_live.OUTPUT.read_text(encoding="utf-8") + (ROOT / "scripts" / "demo" / "demo_live.py").read_text(encoding="utf-8")
    assert chr(0x2014) not in text  # CLAUDE.md: 파일 안에서 em dash를 쓰지 않는다
    mmsis = {int(m) for c in CASES for m in c["fixtures"]["shipfinder"]["positions"]}
    assert mmsis == set(range(440999201, 440999212))  # 11척. 101~106은 이미 쓰는 번호라 겹치지 않는다
    for c in CASES:
        for hit in c["fixtures"]["shipfinder"]["search"]:
            assert hit["ship_name"].startswith("DEMO ") and hit["call_sign"].startswith("DMO")


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_case(demo, case, monkeypatch):
    response, signal_set = _ask(demo, case, monkeypatch)
    expect = case["expected_verdict"] or "insufficient"

    # 선박 식별과 상태
    assert response.status == case["expected_status"]
    assert response.vessel_match == case["expected_vessel_match"]
    assert response.verdict == case["expected_verdict"]
    if case["expected_vessel_match"] == "confirmed":
        assert [c.mmsi for c in response.vessel_candidates] == [case["expected_mmsi"]]
        # MRN으로 해수부 신고를 찾아 호출부호로 이은 배다 (이름이 아니라 번호로 확정, services/judge/identify.call_sign_from_mrn)
        assert "MRN 입항 신고의 호출부호 일치" in response.vessel_candidates[0].match_reasons
    unipass = case["fixtures"]["unipass"]
    mof_mrns = {r["mrNum"] for r in case["fixtures"]["mof"]["arrival_reports"] if r["mrNum"]}
    assert len(unipass["cargMtNo"]) == 19 and (unipass["cargMtNo"][:11] in mof_mrns or not mof_mrns or case["id"] == "L08")

    if case["id"] == "L10":
        # 반출 완료: 배를 찾지 않고 규칙으로 순항 (routers/agent._released)
        assert response.decided_by == "rule" and response.customs.stage_name == "반출신고" and signal_set is None
    elif expect == "insufficient":
        assert response.verdict is None and len(response.vessel_candidates) == 2
        assert response.missing_inputs == case["expected_missing_inputs"]
    else:
        triggered = sorted(s.id for s in signal_set.signals if s.state == "triggered")
        assert triggered == sorted(case["expected_signals"]), triggered
        # 코드 판정 표가 기대 등급을 낸다 (LLM 없이). 판정 LLM이 있어도 회색 지대가 아니면 이 등급이 고정이다
        assert verdict.table_verdict(signal_set, response.days_margin) == case["expected_verdict"]
        assert not verdict.is_gray(signal_set)
        assert response.days_margin == case["demo_margin"]

    if response.customs is not None:  # 반출 완료 화물은 규칙이 만든 응답에 통관 칸이 있다. 나머지는 LLM 해설이 있어야 채워진다
        assert response.customs.goods_name == unipass["prnm"] and response.customs.container_no == ", ".join(unipass["cntrNo"])


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_customs_record_parsed(demo, case):
    """세관 응답 파싱(services/judge/customs.UnipassClient.fetch, 라우터가 쓰는 길 그대로): 품명·컨테이너·포워더·선사·적재항·이력.
    판정 LLM이 통관 해설을 쓰지 않는 규칙 판정에서는 응답에 통관 칸이 안 채워져, 파싱 결과를 여기서 직접 본다."""
    from backend.app.services.judge.customs import UnipassClient

    unipass = case["fixtures"]["unipass"]
    record = UnipassClient().fetch(case["request"]["bl_no"], "HOUSE")
    assert record.goods_name == unipass["prnm"]
    numbers = record.container_no.split(", ")
    assert len(numbers) == len(unipass["cntrNo"]) and all(_iso6346_ok(n) and n.startswith("DEMU") for n in numbers)
    assert record.forwarder_name == (unipass["frwrEntsConm"] or None)
    assert (record.forwarder_name or "DEMO ").startswith("DEMO ") and record.carrier_name.startswith("DEMO ")
    assert (record.loading_port_name, record.discharge_port, record.discharge_port_name) == (unipass["ldprNm"], "KRPUS", "부산항")
    assert record.ship_name == unipass["shipNm"] and record.ship_nat == unipass["shipNat"] and record.voyage == unipass["vydf"]
    assert record.stage_name == unipass["history"][0]["cargTrcnRelaBsopTpcd"]  # 현재 단계 = 가장 최근 이력 줄
    assert len(record.display_rows) == len(unipass["history"]) and len(record.stage_history) == len(unipass["history"])
    assert record.mrn == unipass["cargMtNo"][:11]


def test_signals_and_grades_table(demo, monkeypatch):
    """10건을 한 번에 돌려 (신호, 등급) 표를 만든다. 보고서에 붙이는 표와 같다 (pytest -s로 보면 출력된다)."""
    rows = []
    for case in CASES:
        response, signal_set = _ask(demo, case, monkeypatch)
        on = [s.id for s in signal_set.signals if s.state == "triggered"] if signal_set else []
        grade = verdict.table_verdict(signal_set, response.days_margin) if signal_set else response.verdict
        rows.append((case["request"]["bl_no"], response.status, on, grade, response.days_margin))
    print()
    for row in rows:
        print(row)
    assert [r[3] for r in rows] == [c["expected_verdict"] for c in CASES[:7]] + [None, "fine", "fine"]


def test_second_step_after_picking_a_ship(demo, monkeypatch):
    """8번: 같은 이름 배 2척을 되묻고, 사용자가 후보를 고르면(resolved_mmsi) 그 배로 정상 판정한다 -> 순항.

    같은 이름 두 척 중 해수부 부산 신고가 있는 배(첫 배)를 고르면 입항 예정·신호가 그 배 값으로 나온다."""
    case = next(c for c in CASES if c["id"] == "L08")
    first, _ = _ask(demo, case, monkeypatch)
    assert first.status == "insufficient" and {c.mmsi for c in first.vessel_candidates} == {440999208, 440999209}
    then = case["then"]
    second, signal_set = _ask(demo, case, monkeypatch, **then["request"])
    assert (second.status, second.verdict, second.vessel_match) == ("ok", then["expected_verdict"], "confirmed")
    assert not [s.id for s in signal_set.signals if s.state == "triggered"]
    assert verdict.table_verdict(signal_set, second.days_margin) == "fine" and second.days_margin == case["demo_margin"]
    assert second.vessel.mmsi == then["expected_mmsi"] and second.position.lat == case["fixtures"]["shipfinder"]["positions"]["440999208"]["lat"]


def test_second_step_with_arrival_notice_date(demo, monkeypatch):
    """8번: 도착 통지서(A/N) 사진에서 읽은 입항 예정일(forwarder_eta)을 같이 보내는 길. 코드는 이때 서류 대조(match_by_papers)를 건너뛰고
    선박 선택 LLM에 맡긴다 (routers/agent._identify. match_by_papers는 근거를 안 준 첫 조회에서만 돈다).
    진짜 LLM은 안 부르므로 LLM 자리에 '첫 배를 확신 high로 고름'을 끼워, 확정 뒤 판정 흐름이 이어지는지만 본다.
    LLM이 실제로 올바른 배를 고르는지는 이 테스트가 보장하지 않는다 (유료 호출이라 안 돌린다)."""
    case = next(c for c in CASES if c["id"] == "L08")
    # 포워더 입항 예정일 = 서버 데모 해수부 예정일(한국 날짜). 시각을 옮긴 뒤의 재생 파일에서 읽는다
    plan_file = (demo["out"] / "mof" / "VsslEtrynd5" / "DMO08.xml").read_text(encoding="utf-8")
    plan_day = datetime.fromisoformat(re.search(r"<etryptDt>([^<]+)</etryptDt>", plan_file).group(1)).astimezone(KST).date()
    asked = []

    def pick(candidates, customs, voyage_no=None, forwarder_eta=None, **kwargs):
        asked.append((len(candidates), forwarder_eta))
        return baseline_rules.pick_vessel([c for c in candidates if c.mmsi == 440999208], customs)

    response, _ = _ask(demo, case, monkeypatch, pick=pick, forwarder_eta=plan_day)
    assert asked == [(2, plan_day)]  # 후보 2척과 A/N 날짜가 LLM으로 갔다
    assert (response.status, response.verdict, response.vessel_match) == ("ok", "fine", "confirmed")


def test_track_points(demo):
    """배마다 6시간 간격 위치 이력 8~12점이 재생 폴더에 있다. 지도가 이미 지나온 길을 그린다. 마지막 점이 현재 위치다."""
    for case in CASES:
        for mmsi, position in case["fixtures"]["shipfinder"]["positions"].items():
            rows = json.loads((demo["out"] / "positions" / f"{mmsi}.json").read_text(encoding="utf-8"))
            assert 8 <= len(rows) <= 12, (case["id"], mmsi, len(rows))
            times = [datetime.fromisoformat(r["at"]) for r in rows]
            assert all(b - a == timedelta(hours=6) for a, b in zip(times, times[1:]))
            assert (rows[-1]["lat"], rows[-1]["lng"], rows[-1]["sog"]) == (round(position["lat"], 4), round(position["lng"], 4), position["sog"])
            # 위치 수신 시각(last_time)이 마지막 점이다. 새 위치 파일이 옮겨진 시각과 같게 움직인다
            shifted = json.loads((demo["out"] / "shipfinder" / "VesselPositionSingle" / f"{mmsi}.json").read_text(encoding="utf-8"))["data"]
            assert times[-1] == datetime.fromtimestamp(shifted["last_time"], timezone.utc)


def test_replay_files_have_real_shape(demo):
    """UNI-PASS 파일이 실제 API001 응답 모양이다: 상단 칸, 컨테이너 여러 태그, 이력 줄은 최신이 위, 이력 13칸. 포워더 빈 칸은 빈 태그."""
    root = ElementTree.parse(demo["out"] / "unipass" / "DEMOSH2610009.xml").getroot()
    top = root.find("cargCsclPrgsInfoQryVo")
    for tag in ("csclPrgsStts", "prgsStts", "prgsStCd", "cargMtNo", "shipNm", "shipNat", "vydf", "etprDt", "dsprCd", "dsprNm", "prnm",
                "ldprCd", "ldprNm", "lodCntyCd", "shcoFlco", "frwrEntsConm", "cntrGcnt"):
        assert top.find(tag) is not None, tag
    assert top.findtext("frwrEntsConm") == "" and top.findtext("cntrGcnt") == "3" and len(top.findall("cntrNo")) == 3
    rows = root.findall("cargCsclPrgsInfoDtlQryVo")
    stamps = [r.findtext("prcsDttm") for r in rows]
    assert stamps == sorted(stamps, reverse=True) and rows[0].findtext("cargTrcnRelaBsopTpcd") == "수입신고수리"
    assert len(rows[0]) == 13
    # 반출 완료 화물은 이력 10줄이고 맨 위(최신)가 반출신고다
    released = ElementTree.parse(demo["out"] / "unipass" / "DEMOQD2610010.xml").getroot().findall("cargCsclPrgsInfoDtlQryVo")
    assert len(released) == 10 and released[0].findtext("cargTrcnRelaBsopTpcd") == "반출신고"


def test_existing_three_unchanged(demo, monkeypatch):
    """라이브 10건과 같이 써도 평가셋 데모 3건(TESTBL01·04·26)의 결과는 그대로다 (_ALL.xml 이어 붙이기 뒤에도)."""
    from backend.app.routers import agent
    from backend.app.schemas.agent import AgentRequest

    monkeypatch.setattr(agent.llm, "judge", baseline_rules.judge)
    monkeypatch.setattr(agent.llm, "pick_vessel", baseline_rules.pick_vessel)

    def ask(case_id: str):
        g = demo["three"][case_id]
        ShipFinderClient.cache.clear()
        with freeze_time(demo["now"], tick=True, ignore=FREEZE_IGNORE):
            return agent.run_agent(AgentRequest(bl_no=g["bl_no"], bl_type="HOUSE", session_id=f"t-{case_id}", sale_due_date=g["sale_due_date"]))

    normal = ask("N01")
    assert (normal.status, normal.verdict, normal.days_margin) == ("ok", "fine", 4)
    assert ask("B01").status == "insufficient"
    assert ask("F04").status == "partial"


def test_merged_all_file_lists_every_demo_ship(demo):
    """해수부 _ALL.xml이 마지막 문항만이 아니라 모든 문항의 배를 담는다 (MRN으로 훑는 조회가 어느 데모 배도 찾는다)."""
    text = (demo["out"] / "mof" / "VsslEtrynd5" / "_ALL.xml").read_text(encoding="utf-8")
    for n in (1, 2, 3, 4, 5, 6, 7, 9):
        assert f"26DMO{chr(64 + n)}{n:04d}I" in text
    assert "TSTA1" in text  # 평가셋 N01의 배도 남아 있다
    assert text.count("<item>") == int(re.search(r"<totalCount>(\d+)</totalCount>", text).group(1))


def _mof_times(out: Path, api: str, call: str, tag: str) -> list[datetime]:
    """재생 폴더의 해수부 파일에서 한 칸(tag)의 시각들을 읽는다. 파일이 없으면 빈 목록."""
    path = out / "mof" / api / f"{call}.xml"
    return [datetime.fromisoformat(t) for t in re.findall(rf"<{tag}>([^<]+)</{tag}>", path.read_text(encoding="utf-8"))] if path.is_file() else []


def test_date_fields_stay_consistent(demo):
    """시각을 옮긴 뒤에도 날짜 칸이 서로 맞는다: 세관 입항일 = 믿을 도착(해수부 실적, 없으면 예정)의 한국 날짜 (8번만 하루 앞),
    판매 예정일 = 그 날짜 + 여유 일수 (10번은 오늘 + 3일). 어느 기준 시각에서 만들어도 같다."""
    today = demo["now"].astimezone(KST).date()
    for case in CASES:
        call = case["fixtures"]["shipfinder"]["search"][0]["call_sign"]
        actual = _mof_times(demo["out"], "CntlVssl2", call, "cntrlOpertDt")  # 입항·접안·투묘·출항 시각 (관제 이벤트 이름은 따로 안 가른다)
        # 해수부 실적은 입항·접안 이벤트의 가장 이른 시각이다. 이벤트 이름을 안 가르려고 4번·9번(입항 -19h)·10번(-122h)만 실적을 쓴다
        arrival = min(actual) if case["id"] in ("L04", "L09", "L10") else _mof_times(demo["out"], "VsslEtrynd5", call, "etryptDt")[0]
        trusted_day = arrival.astimezone(KST).date()
        text = (demo["out"] / "unipass" / f"{case['request']['bl_no']}.xml").read_text(encoding="utf-8")
        entry = datetime.strptime(re.search(r"<etprDt>(\d{8})</etprDt>", text).group(1), "%Y%m%d").date()
        assert entry == trusted_day - timedelta(days=1 if case["id"] == "L08" else 0), case["id"]
        if case.get("demo_anchor"):  # 화면이 채울 수 있게 믿을 도착일이 늘 "오늘 + 일"이다
            assert trusted_day == today + timedelta(days=case["demo_anchor"]["day"]), case["id"]
        sale = date.fromisoformat(demo["live"][case["id"]]["sale_due_date"])
        expected = trusted_day + timedelta(days=case["demo_margin"]) if case["demo_margin"] is not None else today + timedelta(days=3)
        assert sale == expected, case["id"]


def test_web_examples_match_demo_dates():
    """화면 예시 메뉴(web/lib/api.ts liveExamples)가 채우는 판매 예정일(sale_in_days)이 jsonl의 demo_sale_in_days와 같다.
    같지 않으면 화면이 넣은 날짜로는 표의 등급과 여유 일수가 안 나온다. 입항이 끝난 화물과 반출 완료는 채우지 않는다."""
    text = (ROOT / "web" / "lib" / "api.ts").read_text(encoding="utf-8")
    web = {m[0]: int(m[1]) for m in re.findall(r"bl_no: '(DEMO\w+)', bl_type: 'HOUSE' as const, sale_in_days: (\d+)", text)}
    expected = {c["request"]["bl_no"]: c["demo_sale_in_days"] for c in CASES if c.get("demo_anchor")}
    assert web == expected and len(web) == 6
    # 예시 메뉴에 라이브 10건이 다 있다
    assert all(c["request"]["bl_no"] in text for c in CASES)
