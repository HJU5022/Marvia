"""라우팅 전후 비용·지연 측정. (체크리스트 40번, SDD 5절 라우팅)

무엇을 재나:
  같은 문장을 두 번 뽑는다. 한 번은 로컬 GGUF(비용 0), 한 번은 대형 모델(토큰 요금).
  슬롯이 서로 같은지도 본다. 값이 같다면 "싼 쪽으로 보내도 답이 같다"가 근거로 남는다.

왜 스크립트인가:
  진짜 API 를 부른다. pytest 는 키 없이 돌아야 하므로 (TEST_GUIDE) 여기 둔다.

    python scripts/measure_routing.py                 # 기본 문장 4개
    python scripts/measure_routing.py --repeat 3      # 문장마다 3회
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 함정 2건, SI 2건. 부대명·고객사명은 문서 규칙대로 "진해 기지", "여의도 고객사" 수준까지만 쓴다
SENTENCES = [
    "목요일 아침 8시 진해 기지에서 레이더 정기점검. 저는 창원시청에서 차로, 최동료는 마산역에서 대중교통으로 옵니다. 출입조치는 신청했습니다.",
    "금요일 9시 진해 기지 정비 미팅. 박업체 과장님이 부산 사상에서 차로 오시면서 김해시청 앞에서 이업체 기사님을 태우고 오십니다.",
    "오늘 밤 10시 여의도 고객사 야간 배포. 저는 강남역에서 지하철, 윤업체는 판교역에서 지하철로 옵니다. 1층에서 인솔받습니다.",
    "내일 오후 2시 여의도 고객사 미팅. 저는 수원시청에서 차로 가고 한동료는 강남역에서 지하철로 옵니다.",
]


def load_env() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            # setdefault 가 아니라 덮어쓴다. 셸에 남은 낡은 키를 타면 402 가 난다 (09-20 실측)
            os.environ[key.strip()] = value.split(" #")[0].strip().strip('"')


def slot_fingerprint(slots) -> str:
    """두 모델의 답이 같은지 비교할 지문. 화면·계산에 쓰이는 값만 본다."""
    return json.dumps(
        {
            "preset": slots.preset,
            "datetime": slots.datetime,
            "destination": slots.destination,
            "participants": [
                [p.name, p.origin, p.transport, p.pickup, p.pickup_at, p.role] for p in slots.participants
            ],
            "constraints": sorted(slots.constraints),
            "missing": sorted(slots.missing),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


async def run_once(text: str, use_local: bool) -> dict:
    from backend.app.services import llm, slot_model

    original = slot_model.available
    if not use_local:
        slot_model.available = lambda: False  # 대형 모델로 강제
    try:
        started = time.time()
        slots = await llm.extract_slots(text)
        meta = llm.last_meta()
        return {
            "ok": True,
            "seconds": time.time() - started,
            "model": meta.get("model"),
            "cost_usd": meta.get("cost_usd") or 0.0,
            "tokens_in": meta.get("tokens_in") or 0,
            "tokens_out": meta.get("tokens_out") or 0,
            "attempts": meta.get("attempts"),
            "fingerprint": slot_fingerprint(slots),
        }
    except Exception as e:  # noqa: BLE001  한 건 실패해도 나머지를 잰다
        return {"ok": False, "seconds": time.time() - started, "error": f"{type(e).__name__}: {e}"}
    finally:
        slot_model.available = original


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()

    load_env()
    from backend.app.services import llm, slot_model

    if not slot_model.available():
        print("로컬 GGUF 가 없다. backend/app/models/ 에 모델·prompt.json·grammar.gbnf 가 있어야 한다.")
        return 1
    print(f"소형: {slot_model.model_name()}   대형: {llm.model_large()}")
    print()

    rows: list[dict] = []
    for index, text in enumerate(SENTENCES, start=1):
        for _ in range(args.repeat):
            small = await run_once(text, use_local=True)
            large = await run_once(text, use_local=False)
            same = small.get("fingerprint") == large.get("fingerprint")
            rows.append({"index": index, "small": small, "large": large, "same": same})
            mark = "같음" if same else "다름"
            print(
                f"[{index}] 소형 {small['seconds']:5.1f}s ${small.get('cost_usd', 0):.6f}"
                f"   대형 {large['seconds']:5.1f}s ${large.get('cost_usd', 0):.6f}   슬롯 {mark}"
            )

    ok = [r for r in rows if r["small"].get("ok") and r["large"].get("ok")]
    if not ok:
        print("성공한 측정이 없다")
        return 1

    small_cost = sum(r["small"]["cost_usd"] for r in ok)
    large_cost = sum(r["large"]["cost_usd"] for r in ok)
    small_sec = [r["small"]["seconds"] for r in ok]
    large_sec = [r["large"]["seconds"] for r in ok]
    agree = sum(1 for r in ok if r["same"])

    print()
    print(f"측정 {len(ok)}건 (문장 {len(SENTENCES)}개 x {args.repeat}회)")
    print(f"  비용 합계   소형 ${small_cost:.6f}   대형 ${large_cost:.6f}")
    print(f"  요청당 평균 소형 ${small_cost / len(ok):.6f}   대형 ${large_cost / len(ok):.6f}")
    print(f"  지연 중앙값 소형 {statistics.median(small_sec):.1f}s   대형 {statistics.median(large_sec):.1f}s")
    print(f"  슬롯 일치   {agree}/{len(ok)}")
    if large_cost > 0:
        print(f"  절감률      {(1 - small_cost / large_cost) * 100:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
