"""LLM 세 함수 실제 호출 확인 스크립트 (C-6·C-5·C-9 스모크 테스트).

services/llm.py의 judge()·pick_vessel()·answer_follow_up()을 실제 모델로 한 번씩 부른다.
사례는 모두 가공값이다. 실제 B/L·선박·고객 정보는 넣지 않는다.

    python -m scripts.eval.smoke_judge judge     # 2층 판정. 기대: watch (목적지만 어긋남, 여유 5일)
    python -m scripts.eval.smoke_judge pick      # 동명 선박 2척. 기대: 국적이 맞는 440999001 또는 애매하면 null
    python -m scripts.eval.smoke_judge follow    # 범위 밖 질문. 기대: in_scope false

모델은 .env의 LLM_MODEL. 프롬프트는 Langfuse(production), 안 되면 backend/app/prompts/ 파일.
한 번 실행 = LLM 호출 1회(과부하 재시도 시 2회).
"""
import argparse
import json
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv(".env")  # 레포 루트에서 실행한다. 키를 출력하지 않는다

from backend.app.schemas.agent import AgentResponse, VesselCandidate  # noqa: E402  .env를 먼저 읽어야 해서 아래에 둔다
from backend.app.schemas.customs import CustomsRecord, CustomsStage  # noqa: E402
from backend.app.schemas.signals import Signal, SignalSet  # noqa: E402
from backend.app.services import llm  # noqa: E402

NOW = datetime.now(timezone.utc)
SIGNAL_IDS = ["position_stale", "eta_conflict", "anchor_wait", "dest_changed",
              "navstat_mismatch", "customs_hold", "sales_date_exceeded"]


def _customs() -> CustomsRecord:
    """가공 통관 정보. 반입신고 단계."""
    return CustomsRecord(
        ship_name="TEST STAR", ship_nat="PA", voyage="0012W", entry_date=NOW + timedelta(days=2),
        stage_name="반입신고", shed_name="TEST터미널 CY",
        stage_history=[CustomsStage(code="", name="입항적재화물목록 제출", at=NOW - timedelta(days=3)),
                       CustomsStage(code="", name="반입신고", at=NOW - timedelta(hours=2))],
        bl_masked="TEST****0001", fetched_at=NOW,
    )


def _signals() -> SignalSet:
    """가공 신호. dest_changed만 켜짐 (AIS 목적지 CNSHA, 해수부 입항 신고는 부산)."""
    values = {"dest_changed": "destcode=CNSHA", "eta_conflict": "AIS ETA와 해수부 예정 차이 2시간"}
    signals = [Signal(id=i, state="triggered" if i == "dest_changed" else "clear",
                      value=values.get(i, "정상"), threshold="rules.md", source="test") for i in SIGNAL_IDS]
    return SignalSet(signals=signals, freshness="fresh", distance_nm=120.0, calc_eta=NOW + timedelta(days=2),
                     eta_gap_hours=2.0, computed_at=NOW)


def _print(answer: llm.LLMAnswer) -> None:
    r = answer.llm
    print(f"model: {r.model} | provider: {r.provider} | {r.latency_ms} ms | 시도 {r.attempts}회 | Langfuse 프롬프트 번호 {answer.prompt_version}")
    print(f"tokens: in {r.prompt_tokens} / out {r.completion_tokens}")
    print(json.dumps(answer.output.model_dump(mode="json"), ensure_ascii=False, indent=2))


def run_judge() -> None:
    _print(llm.judge(_signals(), _customs(), days_margin=5))


def run_pick() -> None:
    candidates = [
        VesselCandidate(mmsi=440999001, imo=9900001, name="TEST STAR", flag="PA", dest="KRPUS",
                        last_time=NOW - timedelta(hours=1), ship_type=70, match_reasons=[]),
        VesselCandidate(mmsi=440999002, imo=9900002, name="TEST STAR", flag="LR", dest="CNSHA",
                        last_time=NOW - timedelta(days=40), ship_type=80, match_reasons=[]),
    ]
    _print(llm.pick_vessel(candidates, _customs()))


def run_follow() -> None:
    response = AgentResponse(status="ok", verdict="watch", vessel_match="confirmed", days_margin=5,
                             decided_by="llm", vessel=None, position=None, eta=None, customs=None, berth=None,
                             evidence=[], answer="배는 부산으로 오고 있지만 목적지 표시가 달라 한 번 확인이 필요합니다.",
                             trace_id="smoke")
    _print(llm.answer_follow_up("비트코인 시세 알려줘", response))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLM 세 함수 실제 호출 확인 (가공값)")
    parser.add_argument("fn", choices=["judge", "pick", "follow"])
    {"judge": run_judge, "pick": run_pick, "follow": run_follow}[parser.parse_args().fn]()
