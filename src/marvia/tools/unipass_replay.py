"""키 없이 도는 재생 조회. fixtures/unipass/{번호}.json을 읽어 화물 상태로 돌려준다 (설계 7.2).

하지 않는 일: 실제 UNI-PASS 호출(계획 3에서 같은 함수 모양으로 붙인다), 판정.
fixture는 실제 응답과 형식만 흉내 낸 가공값이다. 실제 응답은 약관상 저장소에 넣지 않는다.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from marvia.identify.models import CargoFacts, ToolError

# src/marvia/tools/unipass_replay.py에서 세 단계 올라가면 저장소 루트다 → 루트의 fixtures/unipass/
FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "unipass"


def lookup_cargo(number: str) -> CargoFacts | ToolError:
    """번호 하나를 조회한다. 없으면 예외 대신 ToolError(not_found)를 돌려준다."""
    path = FIXTURES / f"{number}.json"
    if not path.exists():
        # [왜] 예외를 던지면 그래프가 멈춘다. 값으로 돌려주면 에이전트가 보고 다음 길을 고를 수 있다
        # [왜] 없는 번호는 다시 조회해도 없으니 retryable=False
        return ToolError(code="not_found", message="재생 데이터에 없는 번호입니다", retryable=False)
    data = json.loads(path.read_text(encoding="utf-8"))
    # [왜] 조회 시각은 UTC로 남긴다. 화면에서 한국 시간으로 바꿔 보여 준다
    return CargoFacts(number=number, fetched_at=datetime.now(UTC), **data)
