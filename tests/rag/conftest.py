"""tests/rag 공용 준비물. 이 폴더의 테스트 함수가 인자 이름(db, make_unit, fake_embed)으로 받아 쓴다."""

import hashlib
from datetime import date

import psycopg
import pytest

from marvia.config import Settings
from marvia.db import apply_migrations
from marvia.rag.models import Unit

URL = Settings().database_url
VOCAB = ["신고", "검사", "반입", "보세"]  # 가짜 벡터의 칸 이름


@pytest.fixture
def db():
    """시험용 스키마에 표를 만들고 끝나면 스키마째 지운다. 로컬 DB가 꺼져 있으면 건너뛴다."""
    try:
        conn = psycopg.connect(URL, connect_timeout=2)
    except psycopg.OperationalError:
        pytest.skip("로컬 Postgres가 꺼져 있음 (docker compose up -d db)")
    # [왜] 스키마는 DB 안의 폴더 같은 것. 실제 색인(public)과 섞이지 않게 marvia_test에 따로 만든다
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector SCHEMA public")
    conn.execute("DROP SCHEMA IF EXISTS marvia_test CASCADE")
    conn.execute("CREATE SCHEMA marvia_test")
    conn.execute("SET search_path TO marvia_test, public")  # 표 이름을 marvia_test에서 먼저 찾는다
    apply_migrations(conn)
    yield conn
    conn.rollback()
    conn.execute("DROP SCHEMA marvia_test CASCADE")
    conn.commit()
    conn.close()


def _make_unit(label: str, text: str, effective: date = date(2026, 10, 2)) -> Unit:
    return Unit(
        unit_id=f"LTEST@{effective:%Y%m%d}#{label}",
        doc_id="LTEST",
        law_name="시험법",
        kind="법률",
        effective=effective,
        source_url="https://example.test",
        heading=f"시험법 > {label}",
        text=text,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


@pytest.fixture
def make_unit():
    """make_unit("제1조", "글")로 시험용 Unit을 만든다."""
    return _make_unit


def _fake_embed(texts: list[str]) -> list[list[float]]:
    out = []
    for text in texts:
        vector = [0.0] * 1024
        for i, word in enumerate(VOCAB):
            if word in text:
                vector[i] = 1.0
        vector[-1] = 0.1  # [왜] 모두 0인 벡터는 코사인 거리를 잴 수 없다
        out.append(vector)
    return out


@pytest.fixture
def fake_embed():
    """VOCAB 낱말이 글에 있으면 그 칸을 1로 하는 가짜 임베딩. [왜] 키 없이 '가까운 글'을 정해 둘 수 있다"""
    return _fake_embed
