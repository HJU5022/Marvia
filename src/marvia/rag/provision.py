"""조문 이름표("관세법 제241조제3항")로 코퍼스 단위를 곧바로 찾는다 (설계 5.3, 5.6).

하지 않는 일: 검색·채점·LLM 호출. 임베딩도 쓰지 않는다. 별표처럼 코퍼스에 없는 이름표는 찾지 못한다.
[왜] 계산 결과의 basis는 조문 이름표일 뿐 인용이 아니다. 인용에 쓸 unit_id를 RAG 한 바퀴 없이 얻는 길이다.
"""

from __future__ import annotations

import re
from datetime import date

import psycopg

from marvia.rag.models import Evidence

# 법령 이름 + 제N조(의N)  뒤에 제N항·제N호가 이어질 수 있다. 예: 관세법 제9조제1항제1호
LABEL = re.compile(r"^(?P<law>.+?)\s+제(?P<article>\d+조(?:의\d+)?)(?P<rest>(?:제\d+(?:의\d+)?[항호])*)$")
PART = re.compile(r"제(\d+(?:의\d+)?)([항호])")

# [왜] unit_id는 L001556@20261002#제241조.3항 꼴이다. '#' 뒤 키가 조(.항.호)와 같거나 그 아래 단위면 맞는다
# [주의] 키 뒤에 '.'를 붙여 비교해 제241조가 제241조의2를 끌어오지 않는다
PROVISION_SQL = """
SELECT unit_id, law_name, heading, effective, source_url, body FROM corpus_units
WHERE law_name = %s AND effective <= %s
  AND (split_part(unit_id, '#', 2) = %s OR split_part(unit_id, '#', 2) LIKE %s)
ORDER BY unit_id
"""


def parse_label(label: str) -> tuple[str, str] | None:
    """이름표를 (법령 이름, unit_id의 '#' 뒤 키)로 바꾼다. 조문 이름표가 아니면 None."""
    match = LABEL.match(label.strip())
    if not match:
        return None
    key = f"제{match['article']}" + "".join(f".{n}{kind}" for n, kind in PART.findall(match["rest"]))
    return match["law"], key


def find_provision(conn: psycopg.Connection, label: str, as_of: date) -> list[Evidence]:
    """이름표가 가리키는 조문 단위(그 아래 항·호 포함)를 돌려준다. 못 찾으면 빈 목록."""
    parsed = parse_label(label)
    if parsed is None:
        return []
    law, key = parsed
    try:
        rows = conn.execute(PROVISION_SQL, (law, as_of, key, f"{key}.%")).fetchall()
    except psycopg.Error:
        conn.rollback()  # [왜] 실패한 트랜잭션이 남으면 다음 질의가 모두 죽는다 (rag/search.py와 같다)
        raise
    # [왜] 검색 점수가 없는 직접 조회라 가장 높은 1.0을 준다
    return [
        Evidence(
            unit_id=r[0], law_name=r[1], heading=r[2], effective=r[3], source_url=r[4], text=r[5], score=1.0
        )
        for r in rows
    ]
