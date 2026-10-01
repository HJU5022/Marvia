"""A8 UNI-PASS 클라이언트·정제 테스트. fixture XML로 키 없이 돈다."""
from pathlib import Path

import httpx
import pytest

from backend.app.schemas.customs import mask_bl
from backend.app.services.customs import CustomsError, UnipassClient

FIXTURES = Path(__file__).resolve().parents[2] / "evals" / "fixtures" / "unipass"


def _client(fixture: str, calls: list | None = None) -> UnipassClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        return httpx.Response(200, text=(FIXTURES / fixture).read_text(encoding="utf-8"))

    return UnipassClient(key="test-key", transport=httpx.MockTransport(handler))


def test_master_bl_uses_mbl_param():
    calls = []
    _client("progress_ok.xml", calls).fetch("TEST-MBL 0000001", bl_type="MASTER", bl_year=2026)

    params = calls[0].url.params
    assert params["mblNo"] == "TESTMBL0000001"  # 공백·하이픈 제거, 대문자
    assert params["blYy"] == "2026" and params["crkyCn"] == "test-key"
    assert "hblNo" not in params


def test_house_bl_uses_hbl_param():
    calls = []
    _client("progress_ok.xml", calls).fetch("TESTHBL0000001", bl_type="HOUSE")
    assert "hblNo" in calls[0].url.params and "mblNo" not in calls[0].url.params


def test_refines_contract_fields():
    record = _client("progress_ok.xml").fetch("TESTMBL0000001")

    assert (record.ship_name, record.ship_nat, record.voyage) == ("TEST STAR", "PA", "0012W")
    assert record.entry_date.strftime("%Y%m%d") == "20260925"
    # stage_name은 가장 최근 이력 줄의 처리구분이다. 상단 csclPrgsStts는 "수입신고수리"에서 멈춰서
    # 이미 반출된 화물도 수리 단계로 보였다 (09-28 실제 B/L). stage_code는 진행상태코드(prgsStCd)
    assert (record.stage_name, record.stage_code) == ("반출신고", "CAGE12")
    assert record.shed_name == "TEST터미널 CY"  # 상단엔 장치장이 없어 최신 이력 줄의 값을 쓴다
    assert record.discharge_port == "KRPUS"  # 양륙항 코드. 부산 외면 unsupported (09-28, 실제 부산 화물 1건도 KRPUS)
    assert record.fetched_at is not None


def test_stage_name_falls_back_to_status_without_history():
    """이력 줄이 없으면 상단 통관진행상태(csclPrgsStts)를 단계 이름으로 쓴다."""
    xml = (FIXTURES / "progress_ok.xml").read_text(encoding="utf-8")
    start, end = xml.index("<cargCsclPrgsInfoDtlQryVo>"), xml.rindex("</cargCsclPrgsInfoDtlQryVo>")
    no_history = xml[:start] + xml[end + len("</cargCsclPrgsInfoDtlQryVo>"):]
    client = UnipassClient(key="test-key", transport=httpx.MockTransport(lambda r: httpx.Response(200, text=no_history)))

    record = client.fetch("TESTMBL0000001")

    assert record.stage_history == [] and record.stage_name == "수입신고수리"


def test_stage_history_is_sorted_by_time():
    """실제 응답은 최신 이력이 위에 온다. 이력 줄의 단계 이름은 처리구분(cargTrcnRelaBsopTpcd)에 있다 (09-27 실측)."""
    stages = _client("progress_ok.xml").fetch("TESTMBL0000001").stage_history
    assert [s.name for s in stages] == [
        "입항적재화물목록 제출", "하선신고 수리", "입항보고 수리", "반입신고", "수입신고", "수입신고수리", "반출신고",
    ]
    assert all(s.code == "" for s in stages)  # 이력 줄에는 단계 코드 칸이 없다
    assert all(a.at < b.at for a, b in zip(stages, stages[1:]))


def test_excluded_fields_are_not_carried():
    """품명·중량·세관명은 계약 C5에 자리가 없어 LLM에 갈 수 없다 (SDD 3.5)."""
    record = _client("progress_ok.xml").fetch("TESTMBL0000001")
    dumped = record.model_dump_json()
    for leaked in ("의류", "1200", "부산세관"):
        assert leaked not in dumped


def test_bl_number_is_masked():
    record = _client("progress_ok.xml").fetch("TESTMBL0000001")
    assert record.bl_masked == "TEST****0001"
    assert "TESTMBL0000001" not in record.model_dump_json()


def test_not_found_returns_none():
    """없는 B/L은 예외가 아니다. 라우터가 insufficient로 안내한다 (SDD 4.1)."""
    assert _client("not_found.xml").fetch("NOSUCHBL000001") is None


def test_param_error_raises_bad_input():
    with pytest.raises(CustomsError) as e:
        _client("param_error.xml").fetch("TESTMBL0000001")
    assert e.value.code == "bad_input" and "필수입력" in e.value.message


def test_timeout_is_retryable():
    def boom(request):
        raise httpx.ReadTimeout("slow", request=request)

    client = UnipassClient(key="test-key", transport=httpx.MockTransport(boom))
    with pytest.raises(CustomsError) as e:
        client.fetch("TESTMBL0000001")
    assert (e.value.code, e.value.retryable) == ("timeout", True)


def test_mask_bl_hides_short_numbers_entirely():
    assert mask_bl("SHORT123") == "********"


def test_mrn_is_first_11_chars_of_cargo_number():
    """화물관리번호 19자리 중 앞 11자리가 MRN이다. 해수부 mrNum과 이어 배를 특정한다 (09-23 실측)."""
    record = _client("progress_ok.xml").fetch("TESTMBL0000001")
    assert record.mrn == "26TEST0099I"


def test_reads_loading_and_discharge_ports():
    """어디서 어디로 (10-01). 실제 응답 상단 칸 이름: ldprCd·ldprNm·lodCntyCd·dsprNm. 값은 가공 예시"""
    xml = (FIXTURES / "progress_ok.xml").read_text(encoding="utf-8")
    xml = xml.replace("<dsprCd>", "<ldprCd>CNTAO</ldprCd><ldprNm>Qingdao</ldprNm><lodCntyCd>CN</lodCntyCd><dsprCd>", 1)
    client = UnipassClient(key="test-key", transport=httpx.MockTransport(lambda r: httpx.Response(200, text=xml)))
    record = client.fetch("TESTMBL0000001")
    assert (record.loading_port, record.loading_port_name, record.loading_country) == ("CNTAO", "Qingdao", "CN")
    assert record.route_fields()["loading_port_name"] == "Qingdao" and record.discharge_port_name is not None
