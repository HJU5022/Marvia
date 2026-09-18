"""DB 첫 접속 재시도 (store.get_pool). 진짜 DB 없이 돈다 (TEST_GUIDE).

이 PC 에서 Supabase pooler 첫 접속이 가끔 DNS 에서 실패했다 (09-18 실측). 재시도가 없으면
앱이 기동조차 못 하므로, 일시적 실패는 다시 해 보고 설정 오류는 바로 올리는지 본다.
"""
from __future__ import annotations

import asyncio

import pytest

from backend.app.services import store


@pytest.fixture(autouse=True)
def _no_wait(monkeypatch):
    """테스트가 실제로 1·2·4초를 기다리지 않게 한다."""
    async def instant(_seconds):
        return None

    monkeypatch.setattr(store.asyncio, "sleep", instant)


def test_일시적_실패는_다시_해_본다(monkeypatch):
    calls = {"n": 0}

    async def flaky(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("getaddrinfo failed")
        return "pool"

    monkeypatch.setattr(store.asyncpg, "create_pool", flaky)
    assert asyncio.run(store._create_pool_with_retry("postgresql://x")) == "pool"
    assert calls["n"] == 3


def test_계속_실패하면_마지막_오류를_올린다(monkeypatch):
    calls = {"n": 0}

    async def always_fail(*_args, **_kwargs):
        calls["n"] += 1
        raise OSError("getaddrinfo failed")

    monkeypatch.setattr(store.asyncpg, "create_pool", always_fail)
    with pytest.raises(OSError):
        asyncio.run(store._create_pool_with_retry("postgresql://x"))
    assert calls["n"] == len(store._RETRY_WAITS_SEC) + 1  # 첫 시도 + 재시도 횟수


def test_설정_오류는_다시_해_보지_않는다(monkeypatch):
    calls = {"n": 0}

    async def bad_password(*_args, **_kwargs):
        calls["n"] += 1
        raise ValueError("password authentication failed")

    monkeypatch.setattr(store.asyncpg, "create_pool", bad_password)
    with pytest.raises(ValueError):
        asyncio.run(store._create_pool_with_retry("postgresql://x"))
    assert calls["n"] == 1  # 기다린다고 달라지지 않는다
