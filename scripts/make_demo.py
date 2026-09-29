"""키 없이 도는 데모 B/L 3건의 재생 파일을 만든다 (SDD 6.1, CLAUDE.md "REPLAY_MODE=true면 키 없이 데모 3건", 09-29).

    python -m scripts.make_demo                              # 로컬: 만든 뒤 REPLAY_MODE=true로 서버를 켠다
    docker compose exec api python -m scripts.make_demo      # compose: 떠 있는 api 컨테이너 안에서 만든다

데모 3건 (평가셋 evals/dataset.jsonl의 문항을 그대로 쓴다. 사람이 라벨링한 입력이다):
  TESTBL01  정상    N01  괜찮음(fine)
  TESTBL04  되묻기  B01  같은 이름 배 2척 → 어느 배인지 되묻기(insufficient)
  TESTBL26  실패    F04  위치 조회 권한 없음 → 판정 보류(partial)

왜 날짜를 옮기나:
  평가셋은 "09-22 12:00" 기준 시각(clock)으로 적혀 있다. 평가 실행기는 시계를 그 시각에 고정하지만
  서버는 실제 현재 시각을 쓴다. 그대로 두면 오늘 돌릴 때 위치가 며칠 전 것(오래된 위치)이 되고
  입항 예정일도 이미 지난 날짜가 된다. 그래서 모든 시각을 "지금 - clock"만큼 뒤로 옮겨 쓴다 (09-29 결정: 서버 시계는 건드리지 않는다).
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
  MODEL_A가 비어 있으면 evals/fixtures/replay/llm/marvia-judge.json의 녹화 답을 쓴다 (services/llm.py _replay_answer).
  녹화 답은 이 데모 입력(판매 예정일을 안내한 날짜로 넣거나 비움)에만 맞다.
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from backend.app.clients.replay import REPLAY_DIR
from backend.app.services.evidence import KST
from evals.replay_fixtures import write_replay_files

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals" / "dataset.jsonl"

# (평가셋 문항 id, 화면에 보일 이름, 기대 결과). 쓰는 순서도 이 순서다. N01을 마지막에 둬서
# 해수부 _ALL.xml(호출부호 없이 부를 때 읽는 전체 목록)이 정상 건의 배로 남게 한다 (evals/replay_fixtures.py _write_mof)
# 그래서 F04는 MRN으로 훑는 조회(identify_mrn)가 not_found 경고를 남긴다. 위치 조회 실패로 판정 보류하는 결과는 평가와 같다
DEMO_CASES = [
    ("F04", "실패", "partial: 위치 조회 권한 없음, 판정 보류"),
    ("B01", "되묻기", "insufficient: 같은 이름 배 2척, 어느 배인지 되묻기"),
    ("N01", "정상", "ok: 괜찮음(fine)"),
]

# F04 데모 사본의 배 바꾸기 (위 "F04만 배를 바꾼다"). 전부 가공값이다
F04_RENAME = {
    "TEST CARGO A": "TEST CARGO F",
    "TSTA1": "TSTF1",
    "26TSTA0001I": "26TSTF0001I",  # MRN. 적하목록 번호(cargMtNo) 앞부분에도 들어 있다
    "440999001": "440999004",
    "9900001": "9900004",
}

GENERATED = ("shipfinder", "mof", "unipass")  # 이 스크립트가 만드는 폴더. llm/(녹화 답)과 README는 건드리지 않는다
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


def build(now: datetime, out_dir: Path = REPLAY_DIR) -> list[dict]:
    """데모 3건의 재생 파일을 out_dir에 새로 쓰고, 화면에 넣을 입력값을 돌려준다."""
    records = {r["id"]: r for r in map(json.loads, DATASET.read_text(encoding="utf-8").splitlines()) if r}
    for name in GENERATED:  # 지난번에 만든 것이 남아 섞이지 않게 지운다
        shutil.rmtree(out_dir / name, ignore_errors=True)
    guide = []
    for case_id, label, expected in DEMO_CASES:
        record = shift_record(records[case_id], now)
        if case_id == "F04":
            record = rename_vessel(record, F04_RENAME)
        write_replay_files(record, out_dir)
        guide.append({"bl_no": record["request"]["bl_no"], "label": label, "case_id": case_id,
                      "sale_due_date": record["request"].get("sale_due_date"), "expected": expected})
    return guide


def main() -> None:
    now = datetime.now(timezone.utc)
    guide = build(now)
    until = (now + timedelta(hours=5, minutes=30)).astimezone(KST)
    print(f"데모 재생 파일을 만들었습니다: {REPLAY_DIR.relative_to(ROOT)}")
    print(f"위치가 '오래된 위치'가 되기 전까지: {until:%m-%d %H:%M} (한국 시각). 넘으면 다시 실행하세요\n")
    print("| B/L | 시나리오 | 판매 예정일(선택) | 기대 결과 |")
    print("|---|---|---|---|")
    for g in reversed(guide):  # 정상 → 되묻기 → 실패 순으로 보여 준다
        print(f"| {g['bl_no']} | {g['label']} ({g['case_id']}) | {g['sale_due_date'] or '-'} | {g['expected']} |")
    print("\n판매 예정일은 비워도 됩니다. 넣을 때는 위 날짜를 넣어야 키 없는 녹화 답과 맞습니다.")


if __name__ == "__main__":
    main()
