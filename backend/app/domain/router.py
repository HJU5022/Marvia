"""소형·대형 모델 선택. 계산만 한다. (SDD 5절 라우팅)

왜 나누나 (docs/PRD.md 3절):
  쉬운 건은 대형 모델을 부르지 않는다. 참석자가 둘 이하고 목적지가 분명하고 제약이 없으면
  순위는 규칙 점수로 정해도 답이 같다. 그만큼 비용과 지연이 줄고, 줄어든 양을 request_logs 로 보여준다.

여기서 하지 않는 것:
  슬롯 추출 모델 선택. 추출은 어느 경우든 소형 모델이 한다 (SDD 5절). 소형이 스키마를 못 맞추면
  그때만 llm.py 가 대형으로 승격한다. 그건 실패 처리라 이 파일의 관심사가 아니다.
"""
from __future__ import annotations

from typing import Literal

from backend.app.schemas.slots import Slots

RoutedTo = Literal["small", "large"]

SMALL_MAX_PARTICIPANTS = 2


def route(slots: Slots) -> RoutedTo:
    """이 건을 규칙 점수로 끝낼지(small), 대형 모델에 순위를 맡길지(large) 정한다.

    small 조건은 전부 만족해야 한다 (SDD 5절):
      참석자 2명 이하 · 목적지 있음 · 제약 없음 · 집결지 없음 · 출입조치가 없거나 이미 신청됨

    하나라도 어긋나면 large. 제약(도착 지연, 입항지 변경, 업체 순회, 서로 배려)이나 집결지가 끼면
    후보끼리 우열이 규칙 점수만으로 갈리지 않기 때문이다.
    """
    if len(slots.participants) > SMALL_MAX_PARTICIPANTS:
        return "large"
    if not slots.destination:
        return "large"
    if slots.constraints:
        return "large"
    if slots.rendezvous is not None:
        return "large"
    # 출입조치 정보가 있는데 아직 신청 전(None·False)이면 후보가 열리는지 자체가 갈린다
    if slots.access is not None and slots.access.applied is not True:
        return "large"
    return "small"
