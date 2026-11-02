"""Unit을 DB에 색인한다: 키워드 tsvector + 임베딩 (+ 맥락 문장) (설계 5.3).

하지 않는 일: API 호출 방법. 임베딩 함수와 맥락 문장 함수를 받아서 쓴다(테스트는 가짜 함수를 넣는다).
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg

from marvia.rag.keywords import keywords
from marvia.rag.models import Unit
from marvia.tools.rules import load_rules

Embed = Callable[[list[str]], list[list[float]]]  # 글 목록 → 벡터 목록
Contextualize = Callable[[Unit], str]  # 단위 → 맥락 문장 (Task 9)

# [왜] ON CONFLICT … DO UPDATE: 같은 unit_id가 이미 있으면 새 값으로 덮어쓴다. 다시 돌려도 줄이 늘지 않는다
# [왜] %s::vector: 파이썬 숫자 목록을 pgvector의 vector 타입으로 바꾼다
UPSERT = """
INSERT INTO corpus_units
    (unit_id, doc_id, law_name, kind, effective, source_url,
     heading, body, context, keywords, embedding, sha256)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, to_tsvector('simple', %s), %s::vector, %s)
ON CONFLICT (unit_id) DO UPDATE SET
    doc_id = EXCLUDED.doc_id, law_name = EXCLUDED.law_name, kind = EXCLUDED.kind,
    effective = EXCLUDED.effective, source_url = EXCLUDED.source_url, heading = EXCLUDED.heading,
    body = EXCLUDED.body, context = EXCLUDED.context, keywords = EXCLUDED.keywords,
    embedding = EXCLUDED.embedding, sha256 = EXCLUDED.sha256
"""


def read_units(folder: Path) -> list[Unit]:
    """corpus/units/*.jsonl을 읽는다."""
    units: list[Unit] = []
    for path in sorted(folder.glob("*.jsonl")):
        units += [
            Unit.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line
        ]
    return units


def embed_text(unit: Unit, context: str) -> str:
    """임베딩할 글: 제목 경로 + 맥락 문장(있으면) + 조문 글."""
    return "\n".join(part for part in (unit.heading, context, unit.text) if part)


def index_units(
    conn: psycopg.Connection, units: list[Unit], embed: Embed, contextualize: Contextualize | None = None
) -> int:
    """단위들을 묶음으로 임베딩해 넣는다. 같은 unit_id는 덮어쓴다. 넣은 개수를 돌려준다."""
    cfg = load_rules("rag")["index"]
    # [왜] 맥락 문장은 단위마다 LLM을 한 번씩 부른다. 기다리는 시간이 길어 여러 개를 동시에 부른다
    with ThreadPoolExecutor(max_workers=cfg["workers"]) as pool:
        for start in range(0, len(units), cfg["batch"]):
            chunk = units[start : start + cfg["batch"]]
            contexts = list(pool.map(contextualize, chunk)) if contextualize else [""] * len(chunk)
            vectors = embed([embed_text(u, c) for u, c in zip(chunk, contexts, strict=True)])
            rows = [
                (
                    u.unit_id,
                    u.doc_id,
                    u.law_name,
                    u.kind,
                    u.effective,
                    u.source_url,
                    u.heading,
                    u.text,
                    c,
                    " ".join(keywords(f"{u.heading} {c} {u.text}")),
                    v,
                    u.sha256,
                )
                for u, c, v in zip(chunk, contexts, vectors, strict=True)
            ]
            with conn.cursor() as cur:
                cur.executemany(UPSERT, rows)
            conn.commit()  # [왜] 묶음마다 저장한다. 중간에 끊겨도 앞 묶음은 남는다
    return len(units)
