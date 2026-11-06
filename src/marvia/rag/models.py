"""RAG가 주고받는 자료 모양 (설계 5.2·5.4).

하지 않는 일: 자르기·검색. 모양만 정한다.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class Unit(BaseModel):
    """코퍼스의 조문 단위 하나. 색인과 인용의 기준이다."""

    unit_id: str  # L001556@20261002#제2조.4호.가목 (설계 5.2)
    doc_id: str  # 법령은 L + 법령ID, 고시·규정은 A + 행정규칙ID (국가법령정보센터 번호)
    law_name: str  # 관세법
    kind: str  # 법률·시행령·시행규칙·고시
    effective: date  # 시행일
    source_url: str  # 받은 페이지 주소
    heading: str  # 관세법 > 제1장 총칙 > 제1절 통칙 > 제2조(정의)
    # [왜] 잎 글만 두면 "가. 외국으로부터…"처럼 혼자서는 뜻이 안 통한다. 조 머리말과 윗 항·호 글을 앞에 붙인다
    text: str
    sha256: str  # text의 sha256. 글이 바뀌었는지 볼 때 쓴다


class Evidence(BaseModel):
    """검색이 돌려주는 근거 하나 (설계 5.4의 7번)."""

    unit_id: str
    law_name: str
    heading: str
    effective: date
    source_url: str
    text: str
    score: float  # 마지막 단계의 점수. 클수록 질문과 가깝다
    # 어디서 온 후보인가: hybrid(벡터·키워드 RRF), graph(그래프 이웃, 계획 3b). 평가가 그래프 후보 수를 센다
    origin: str = "hybrid"


class SearchFailed(Exception):
    """검색 길(그래프·MCP)이 실패했다. 글은 코드가 정한 짧은 이름뿐이라 기록에 그대로 남겨도 된다."""
