"""키 없이 도는 서버 데모 13건(라이브 모의 화물 10건 + 평가셋 3건)의 재생 파일을 만든다 (SDD 6.1, CLAUDE.md "REPLAY_MODE=true면 키 없이 데모").

    python -m scripts.demo.make_demo                              # 로컬: 만든 뒤 REPLAY_MODE=true로 서버를 켠다
    docker compose exec api python -m scripts.demo.make_demo      # compose: 떠 있는 api 컨테이너 안에서 만든다

데모 3건 (평가셋 evals/dataset.jsonl의 문항을 그대로 쓴다. 사람이 라벨링한 입력이다):
  TESTBL01  정상    N01  순항(fine)
  TESTBL04  되묻기  B01  같은 이름 배 2척 → 어느 배인지 되묻기(insufficient)
  TESTBL26  실패    F04  위치 조회 권한 없음 → 판정 보류(partial)

왜 날짜를 옮기나:
  평가셋은 "09-22 12:00" 기준 시각(clock)으로 적혀 있다. 평가 실행기는 시계를 그 시각에 고정하지만
  서버는 실제 현재 시각을 쓴다. 그대로 두면 오늘 돌릴 때 위치가 며칠 전 것(오래된 위치)이 되고
  입항 예정일도 이미 지난 날짜가 된다. 그래서 모든 시각을 "지금 - clock"만큼 뒤로 옮겨 쓴다 (서버 시계는 건드리지 않는다).
  - 시각(ISO 문자열, epoch 초): 차이만큼 그대로 옮긴다. 배 위치는 늘 "30분 전 수신"이 된다
  - 날짜만 있는 값(판매 예정일, UNI-PASS 입항일): 한국 날짜 기준 일수만 옮긴다. 그래야 여유 일수가 평가셋과 같게(N01은 4일) 나온다

유효 시간:
  위치 수신 시각이 만든 시점 기준 30분 전이라, rules.md position_stale_hours(6시간)를 넘기면 "오래된 위치"가 된다.
  약 5시간 반 안에 확인하고, 넘기면 이 스크립트를 다시 돌린다.

F04만 배를 바꾼다:
  평가셋의 N01과 F04는 같은 가공 배(MMSI 440999001)를 쓴다. 재생 폴더는 하나라서 같은 MMSI에
  정상 위치와 "권한 없음"을 같이 둘 수 없다. 데모 사본의 F04만 다른 가공 배(TEST CARGO F)로 이름을 바꾼다.
  평가셋 파일은 고치지 않는다 (CLAUDE.md: 평가셋은 사람만 고친다).

판정 LLM:
  LLM_MODEL이 비어 있으면 evals/fixtures/replay/llm/marvia-judge.json의 녹화 답을 쓴다 (services/llm.py _replay_answer).
  녹화 답은 이 데모 입력(판매 예정일을 안내한 날짜로 넣거나 비움)에만 맞다.

라이브 데모 10건 (발표 서버용):
  DEMOQD2610001 ~ DEMOQD2610010. 순항·주의·긴급 세 등급과 되묻기, 반출 완료를 실제 API 응답처럼 필드를 다 채운 모의 화물로 보여 준다.
  시나리오 목록은 scripts/demo/demo_live.py의 SPECS이고, 그것을 펼친 문항이 evals/fixtures/demo_live.jsonl이다 (평가셋이 아니다).
  평가셋 3건(TESTBL01·04·26)은 그대로 같이 쓴다. 10건과 3건은 한 폴더에 같이 써서 해수부 _ALL.xml이 모두의 배를 담는다
  (evals/replay_fixtures._write_all. 전에는 마지막에 쓴 문항만 남아 N01이 마지막이어야 했다).
  위치 이력(6시간 간격)은 positions/<MMSI>.json으로 써서 서버가 DB 대신 읽는다 (clients/replay.position_history).

서류 대조 데모 10건 (서버 데모에는 안 쓴다):
  TESTBL41~50. 동명 선박 중 세관 입항일·적재항과 해수부 입항 신고가 맞는 배를 확정하는 기능
  (services/judge/identify.match_by_papers)과 그 경계를 보여 준다. 문항은 evals/fixtures/demo_papers.jsonl
  (평가셋이 아니다). 기능 확인은 backend/tests/integration/test_demo_papers.py가 build_with_papers로 계속 한다.
  서버 데모에 안 넣는 이유: 라이브 시연은 위 10건으로 정했다. 이 문항 파일과 테스트는 기능 근거로 남겨 둔다.
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from backend.app.clients.replay import REPLAY_DIR
from backend.app.services.judge.evidence import KST
from evals.replay_fixtures import write_replay_files
from scripts.demo import demo_live

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "evals" / "dataset.jsonl"
PAPERS = ROOT / "evals" / "fixtures" / "demo_papers.jsonl"  # 서류 대조 데모 10건 (평가셋 아님, 모듈 설명)
LIVE = ROOT / "evals" / "fixtures" / "demo_live.jsonl"  # 라이브 데모 10건 (평가셋 아님. scripts/demo/demo_live.py가 만든다)

# (평가셋 문항 id, 화면에 보일 이름, 기대 결과). 쓰는 순서도 이 순서다. N01을 마지막에 둬서
# 해수부 _ALL.xml(호출부호 없이 부를 때 읽는 전체 목록)이 정상 건의 배로 남게 한다 (evals/replay_fixtures.py _write_mof)
# 그래서 F04는 MRN으로 훑는 조회(identify_mrn)가 not_found 경고를 남긴다. 위치 조회 실패로 판정 보류하는 결과는 평가와 같다
DEMO_CASES = [
    ("F04", "실패", "partial: 위치 조회 권한 없음, 판정 보류"),
    ("B01", "되묻기", "insufficient: 같은 이름 배 2척, 어느 배인지 되묻기"),
    ("N01", "정상", "ok: 순항(fine)"),
]

# F04 데모 사본의 배 바꾸기 (위 "F04만 배를 바꾼다"). 전부 가공값이다
F04_RENAME = {
    "TEST CARGO A": "TEST CARGO F",
    "TSTA1": "TSTF1",
    "26TSTA0001I": "26TSTF0001I",  # MRN. 적하목록 번호(cargMtNo) 앞부분에도 들어 있다
    "440999001": "440999004",
    "9900001": "9900004",
}

GENERATED = ("shipfinder", "mof", "unipass", "positions")  # 이 스크립트가 만드는 폴더. llm/(녹화 답)과 README는 건드리지 않는다
EPOCH_KEYS = {"last_time", "eta"}  # ShipFinder 응답의 epoch 초 칸
ISO_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")


def shift_value(key: str, value, delta: timedelta, days: timedelta):
    """값 하나를 옮긴다. 시각은 delta만큼, 날짜만 있는 값은 days만큼. 나머지는 그대로."""
    if isinstance(value, dict):
        return {k: shift_value(k, v, delta, days) for k, v in value.items()}
    if isinstance(value, list):
        return [shift_value(key, v, delta, days) for v in value]
    if key in EPOCH_KEYS and isinstance(value, int):
        return value + int(delta.total_seconds())
    if isinstance(value, str) and ISO_DATETIME.match(value):
        return (datetime.fromisoformat(value) + delta).isoformat()
    if key in ("prcsDttm", "rlbrDttm") and isinstance(value, str) and len(value) == 14:  # UNI-PASS 처리일시 YYYYMMDDHHMMSS (한국 시각)
        return (datetime.strptime(value, "%Y%m%d%H%M%S") + delta).strftime("%Y%m%d%H%M%S")
    if key == "etprDt" and isinstance(value, str) and len(value) == 8:  # UNI-PASS 입항일 YYYYMMDD
        return (datetime.strptime(value, "%Y%m%d").date() + days).strftime("%Y%m%d")
    return value


def shift_record(record: dict, now: datetime) -> dict:
    """문항 하나를 now 기준으로 옮긴 사본. clock이 now가 되게 fixtures의 모든 시각과 판매 예정일을 옮긴다."""
    clock = datetime.fromisoformat(record["fixtures"]["clock"])
    delta = timedelta(seconds=int((now - clock).total_seconds()))  # 초 단위로 자른다. epoch 칸이 정수라서
    days = timedelta(days=(now.astimezone(KST).date() - clock.astimezone(KST).date()).days)
    shifted = dict(record)
    shifted["fixtures"] = shift_value("fixtures", record["fixtures"], delta, days)
    request = dict(record["request"])
    if request.get("sale_due_date"):
        request["sale_due_date"] = (date.fromisoformat(request["sale_due_date"]) + days).isoformat()
    shifted["request"] = request
    return shifted


def rename_vessel(record: dict, mapping: dict[str, str]) -> dict:
    """문항 사본의 배 이름·호출부호·MMSI 등을 글자 그대로 바꾼다. 숫자 MMSI도 JSON 글자로는 같아서 한 번에 바뀐다."""
    text = json.dumps(record, ensure_ascii=False)
    for old, new in mapping.items():
        text = text.replace(old, new)
    return json.loads(text)


def _clear(out_dir: Path) -> None:
    """지난번에 만든 재생 파일이 남아 섞이지 않게 지운다."""
    for name in GENERATED:
        shutil.rmtree(out_dir / name, ignore_errors=True)


def build(now: datetime, out_dir: Path = REPLAY_DIR) -> list[dict]:
    """데모 3건의 재생 파일을 out_dir에 새로 쓰고, 화면에 넣을 입력값을 돌려준다."""
    _clear(out_dir)
    return _write_three(now, out_dir)


def build_all(now: datetime, out_dir: Path = REPLAY_DIR) -> tuple[list[dict], list[dict]]:
    """서버 데모 전부를 새로 쓴다: 라이브 10건을 먼저, 평가셋 3건을 나중에 (순서는 이제 결과에 영향이 없다. 해수부 _ALL.xml이 이어 붙는다).
    (3건 안내, 라이브 10건 안내)를 돌려준다. 서류 대조 10건은 더 이상 쓰지 않는다 (build_with_papers)."""
    _clear(out_dir)
    live = _write_live(now, out_dir)
    return _write_three(now, out_dir), live


def build_with_papers(now: datetime, out_dir: Path = REPLAY_DIR) -> tuple[list[dict], list[dict]]:
    """서류 대조 10건(TESTBL41~50)과 평가셋 3건을 쓴다. 서버 데모는 아니고, 서류 대조 기능 테스트(test_demo_papers.py)가 쓴다.
    (3건 안내, 10건 안내)를 돌려준다. 10건의 MRN 조회는 늘 못 찾고 이름 검색과 서류 대조로 간다 (모듈 설명)."""
    _clear(out_dir)
    papers = _write_papers(now, out_dir)
    return _write_three(now, out_dir), papers


def load_live() -> list[dict]:
    """라이브 데모 문항을 읽는다. '#'로 시작하는 줄은 머리 설명이라 건너뛴다."""
    lines = LIVE.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip() and not line.startswith("#")]


def _write_live(now: datetime, out_dir: Path) -> list[dict]:
    """라이브 데모 10건을 now 기준으로 옮겨 쓴다. 3건과 같은 shift_record·write_replay_files를 쓴다.

    시각을 옮긴 뒤 demo_live.finalize로 세관 입항일과 판매 예정일을 다시 계산한다. 일 수만 옮기면 자정 전후에
    여유 일수가 하루 어긋난다 (scripts/demo/demo_live.py 머리 주석)."""
    guide = []
    for original in load_live():
        record = demo_live.finalize(shift_record(original, now))
        write_replay_files(record, out_dir)
        guide.append({"bl_no": record["request"]["bl_no"], "label": record["demo_title"], "case_id": record["id"],
                      "ship": record["fixtures"]["shipfinder"]["search"][0]["ship_name"],
                      "sale_due_date": record["request"]["sale_due_date"], "expected": live_expected_text(record),
                      "expected_verdict": record.get("demo_final_verdict") or record["expected_verdict"]})
    return guide


def live_expected_text(record: dict) -> str:
    """표에 보일 기대 결과 한 줄 (라이브 10건). 같은 값을 두 곳에 적지 않으려고 문항의 expected_*에서 만든다."""
    names = {"fine": "순항(fine)", "watch": "주의(watch)", "act": "긴급(act)"}
    if record["expected_status"] == "insufficient":
        final = names[record["then"]["expected_verdict"]]
        return f"insufficient: 같은 이름 배 2척 되묻기 -> 배를 고르면 {final}"
    return f"{record['expected_status']}: {names[record['expected_verdict']]}"


def load_papers() -> list[dict]:
    """서류 대조 데모 문항을 읽는다. '#'로 시작하는 줄은 머리 설명이라 건너뛴다."""
    lines = PAPERS.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip() and not line.startswith("#")]


def expected_text(record: dict) -> str:
    """표에 보일 기대 결과 한 줄. 문항의 expected_* 칸에서 만든다 (같은 값을 두 곳에 적지 않으려고)."""
    if record["expected_vessel_match"] == "confirmed":
        return f"confirmed: MMSI {record['expected_mmsi']} 확정, 판정 진행"
    return f"{record['expected_status']}·{record['expected_vessel_match']}: 어느 배인지 되묻기"


def _write_papers(now: datetime, out_dir: Path) -> list[dict]:
    """서류 대조 10건을 now 기준으로 옮겨 쓴다. 3건과 같은 shift_record·write_replay_files를 쓴다."""
    guide = []
    for original in load_papers():
        record = shift_record(original, now)
        write_replay_files(record, out_dir)
        guide.append({"bl_no": record["request"]["bl_no"], "label": record["demo_title"], "case_id": record["id"],
                      "sale_due_date": record["request"].get("sale_due_date"), "expected": expected_text(record),
                      "entry_date": record["fixtures"]["unipass"]["etprDt"],
                      "loading_port": record["fixtures"]["unipass"]["ldprNm"],
                      "expected_mmsi": record["expected_mmsi"]})
    return guide


def _write_three(now: datetime, out_dir: Path) -> list[dict]:
    """기존 데모 3건을 쓴다. 지우지 않는다 (지우는 것은 부르는 쪽이 _clear로)."""
    records = {r["id"]: r for r in map(json.loads, DATASET.read_text(encoding="utf-8").splitlines()) if r}
    guide = []
    for case_id, label, expected in DEMO_CASES:
        record = shift_record(records[case_id], now)
        if case_id == "F04":
            record = rename_vessel(record, F04_RENAME)
        write_replay_files(record, out_dir)
        guide.append({"bl_no": record["request"]["bl_no"], "label": label, "case_id": case_id,
                      "sale_due_date": record["request"].get("sale_due_date"), "expected": expected})
    return guide


def refresh(out_dir: Path = REPLAY_DIR) -> datetime:
    """서버가 도는 중에 데모 재생 파일을 새로 만든다 (재생 모드 배포는 4시간마다 자동으로, backend/app/main.py).

    _clear로 지우고 다시 쓰면 그 사이(수 밀리초) 들어온 요청이 파일을 못 찾는다. 그래서 옆 임시 폴더에 다 만든 뒤
    폴더 이름을 바꿔 끼운다. 녹화 LLM 답(llm/)처럼 이 스크립트가 만들지 않는 폴더는 건드리지 않는다.
    돌려주는 값: 이번 파일이 오래된 위치가 되기 전까지의 시각 (로그용).
    """
    now = datetime.now(timezone.utc)
    staging = out_dir.parent / f".{out_dir.name}_staging"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    build_all(now, staging)
    for name in GENERATED:
        new, old, trash = staging / name, out_dir / name, out_dir / f".{name}_old"
        if not new.exists():
            continue
        shutil.rmtree(trash, ignore_errors=True)
        if old.exists():
            old.rename(trash)
        new.rename(old)
        shutil.rmtree(trash, ignore_errors=True)
    shutil.rmtree(staging, ignore_errors=True)
    return now + timedelta(hours=5, minutes=30)


def main() -> None:
    now = datetime.now(timezone.utc)
    guide, live = build_all(now)
    until = (now + timedelta(hours=5, minutes=30)).astimezone(KST)
    print(f"데모 재생 파일을 만들었습니다: {REPLAY_DIR.relative_to(ROOT)}")
    print(f"위치가 '오래된 위치'가 되기 전까지: {until:%m-%d %H:%M} (한국 시각). 넘으면 다시 실행하세요\n")
    print("라이브 데모 10건 (모의 화물. scripts/demo/demo_live.py, evals/fixtures/demo_live.jsonl)\n")
    print("| B/L | 배 | 시나리오 | 판매 예정일 | 기대 결과 |")
    print("|---|---|---|---|---|")
    for g in live:
        print(f"| {g['bl_no']} | {g['ship']} | {g['label']} | {g['sale_due_date']} | {g['expected']} |")
    print("\n판매 예정일은 위 날짜를 넣어야 표의 등급이 나옵니다. 그 입력에는 판정 LLM 녹화 답이 없어 LLM_MODEL이 비어 있으면 partial로 끝납니다 (README).")

    print("\n평가셋 데모 3건 (evals/dataset.jsonl 문항 그대로)\n")
    print("| B/L | 시나리오 | 판매 예정일(선택) | 기대 결과 |")
    print("|---|---|---|---|")
    for g in reversed(guide):  # 정상 → 되묻기 → 실패 순으로 보여 준다
        print(f"| {g['bl_no']} | {g['label']} ({g['case_id']}) | {g['sale_due_date'] or '-'} | {g['expected']} |")
    print("\n판매 예정일은 비워도 됩니다. 넣을 때는 위 날짜를 넣어야 키 없는 녹화 답과 맞습니다.")


if __name__ == "__main__":
    main()
