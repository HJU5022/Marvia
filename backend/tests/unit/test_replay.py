"""REPLAY_MODE 재생 테스트 (SDD 6.1). ShipFinder·해수부·UNI-PASS 클라이언트가 키 없이 evals/fixtures/replay/를 읽는지 본다.

재생 폴더는 tmp_path로 바꿔 끼워서, 레포의 재생 데이터가 바뀌어도 이 테스트는 흔들리지 않는다.
"""
import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from backend.app.clients import replay
from backend.app.clients.mof import MofClient
from backend.app.clients.shipfinder import ShipFinderClient, ShipFinderError
from backend.app.services.judge.customs import UnipassClient

FIXTURES = Path(__file__).resolve().parents[3] / "evals" / "fixtures"


@pytest.fixture
def replay_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("REPLAY_MODE", "true")
    monkeypatch.delenv("SHIPFINDER_KEY", raising=False)
    monkeypatch.delenv("DATA_GO_KR_KEY", raising=False)
    monkeypatch.setattr(replay, "REPLAY_DIR", tmp_path)
    ShipFinderClient.cache.clear()  # 다른 테스트가 담아 둔 캐시 값이 재생 결과를 가리지 않게
    return tmp_path


def _put(root: Path, rel: str, src: Path) -> None:
    dest = root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dest)


@pytest.mark.parametrize("value, expected", [("true", True), ("TRUE", True), ("1", True), ("false", False), ("", False)])
def test_replay_enabled_reads_env(monkeypatch, value, expected):
    monkeypatch.setenv("REPLAY_MODE", value)
    assert replay.replay_enabled() is expected


def test_file_key_normalizes_ship_name():
    assert replay.file_key(" test star ") == "TEST_STAR"
    assert replay.file_key("TEST-STAR.1") == "TEST_STAR_1"


def test_shipfinder_needs_no_key_and_reads_search(replay_dir):
    _put(replay_dir, "shipfinder/VesselSearch/TEST_STAR.json", FIXTURES / "shipfinder" / "search_same_name.json")
    hits = ShipFinderClient().search("test star").hits
    assert [h.mmsi for h in hits][:2] == [440999101, 440999102]


def test_shipfinder_reads_position_by_mmsi(replay_dir):
    _put(replay_dir, "shipfinder/VesselPositionSingle/440999001.json", FIXTURES / "shipfinder" / "position_busan_anchored.json")
    pos = ShipFinderClient().position(440999001)
    assert pos.dest == "BUSAN, KR" and pos.sog == 0.0


def test_shipfinder_missing_search_is_empty_not_error(replay_dir):
    """재생 파일이 없는 선명은 '검색 결과 없음'으로 본다. 라우터는 0척 되묻기로 간다 (SDD 4.1 3단계)."""
    assert ShipFinderClient().search("NO SUCH SHIP").hits == []


def test_shipfinder_missing_position_is_not_found(replay_dir):
    with pytest.raises(ShipFinderError) as e:
        ShipFinderClient().position(440999999)
    assert e.value.code == "not_found"


def test_shipfinder_missing_flag_is_not_found(replay_dir):
    """국적 재생 파일이 없으면 not_found. get_vessel_candidates(_fetch_details)가 이 실패를 빈 값으로 받아 후보는 남긴다."""
    with pytest.raises(ShipFinderError) as e:
        ShipFinderClient().flag(440999999)
    assert e.value.code == "not_found"


def test_mof_needs_no_key_and_reads_by_call_sign(replay_dir):
    _put(replay_dir, "mof/CntlVssl2/TEST01.xml", FIXTURES / "mof" / "control_busan.xml")
    calls = MofClient().control_records(date(2026, 9, 20), date(2026, 9, 22), call_sign="test01")
    assert calls and calls[0].call_sign == "TEST01"


def test_mof_missing_is_empty_list(replay_dir):
    client = MofClient()
    assert client.control_records(date(2026, 9, 20), date(2026, 9, 22), call_sign="NONE") == []
    assert client.sailing_plans(date(2026, 9, 22), date(2026, 9, 29), call_sign="NONE") == []


def test_mof_without_call_sign_reads_all_file(replay_dir):
    """선명으로 찾을 때는 호출부호가 없어서 기간 전체 목록(_ALL)을 돌려준다. 거르기는 도구가 한다."""
    _put(replay_dir, "mof/VsslEtrynd5/_ALL.xml", FIXTURES / "mof" / "sailing_busan.xml")
    plans = MofClient().sailing_plans(date(2026, 9, 22), date(2026, 9, 29))
    assert {p.call_sign for p in plans} >= {"TEST01"}


def test_replay_off_still_requires_key(monkeypatch):
    monkeypatch.setenv("REPLAY_MODE", "false")
    monkeypatch.delenv("SHIPFINDER_KEY", raising=False)
    with pytest.raises(ShipFinderError) as e:
        ShipFinderClient()
    assert e.value.code == "bad_key"


def test_replay_never_calls_network(replay_dir, monkeypatch):
    """재생 중에는 실제 호출이 한 번도 나가지 않는다. 실제 transport를 부르면 실패하게 막아 둔다."""
    import httpx

    def boom(*args, **kwargs):
        raise AssertionError("재생 중 실제 네트워크 호출")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", boom)
    ShipFinderClient().search("ANY")
    MofClient().control_records(date(2026, 9, 20), date(2026, 9, 22), call_sign="ANY")


def test_replay_response_is_json_for_shipfinder(replay_dir):
    """재생 파일이 없을 때 ShipFinder 기본 응답도 실제와 같은 모양(status·data)이다."""
    body = json.loads(replay._shipfinder_default("VesselSearch").content)
    assert body == {"status": 0, "msg": "", "data": []}


def test_unipass_needs_no_key_and_reads_by_bl(replay_dir, monkeypatch):
    monkeypatch.delenv("UNIPASS_KEY", raising=False)
    _put(replay_dir, "unipass/TESTBL01.xml", FIXTURES / "unipass" / "progress_ok.xml")
    record = UnipassClient().fetch("testbl01", "HOUSE")
    assert record is not None and record.ship_name == "TEST STAR"


def test_unipass_missing_bl_is_none(replay_dir, monkeypatch):
    """재생 파일이 없는 B/L은 '없는 B/L'(tCnt 0). 라우터가 insufficient로 되묻는다 (SDD 4.1)."""
    monkeypatch.delenv("UNIPASS_KEY", raising=False)
    assert UnipassClient().fetch("TESTBL99", "MASTER") is None


def test_unipass_kind_specific_file_wins(replay_dir, monkeypatch):
    """<번호>.hbl.xml이 "없음"이고 <번호>.mbl.xml이 있으면, 하우스는 못 찾고 마스터만 찾는다 (실제 마스터 B/L의 모양)."""
    monkeypatch.delenv("UNIPASS_KEY", raising=False)
    _put(replay_dir, "unipass/TESTBL01.mbl.xml", FIXTURES / "unipass" / "progress_ok.xml")
    _put(replay_dir, "unipass/TESTBL01.hbl.xml", FIXTURES / "unipass" / "not_found.xml")
    assert UnipassClient().fetch("TESTBL01", "HOUSE") is None
    record = UnipassClient().fetch("TESTBL01", "MASTER")
    assert record is not None and record.ship_name == "TEST STAR"


def test_replay_fixture_dir_env_overrides_default(tmp_path):
    """REPLAY_FIXTURE_DIR을 주면 모듈을 불러올 때 그 폴더를 읽는다. 서버를 켜기 전에 정한다."""
    import subprocess, sys
    code = "from backend.app.clients import replay; print(replay.REPLAY_DIR)"
    env = {**__import__("os").environ, "REPLAY_FIXTURE_DIR": str(tmp_path)}
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True,
                         cwd=Path(__file__).resolve().parents[3]).stdout.strip()
    assert out == str(tmp_path)
