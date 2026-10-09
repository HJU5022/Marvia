"""backend/tests 공통 픽스처.

테스트는 키도 DB도 없이 돈다 (CLAUDE.md "테스트는 키 없이 돈다").
"""
import psycopg
import pytest


@pytest.fixture(autouse=True)
def _no_real_db(monkeypatch):
    """테스트에서 실제 DB 접속은 기다리지 않고 바로 실패하게 한다.

    많은 테스트가 DATABASE_URL을 postgresql://fake 같은 가짜 주소로 두고, 쓰는 곳의 connect만 가짜로 바꿔 끼운다.
    그런데 바꿔 끼우지 않은 길(앱 수명의 main._migrate, 요청마다 도는 auth._suspended)은 가짜 호스트에 실제로
    붙으려다 이름 찾기 실패까지 약 3초를 기다렸다. test_memory_router.py 하나가 15건에 86초가 걸려
    전체 pytest가 멈춘 것처럼 보였다.
    두 길 모두 접속 실패를 잡아 DB 없이 계속하게 짜여 있으므로, 실패가 바로 오면 동작은 같고 기다림만 없어진다.
    테스트가 connect·open_conn을 가짜로 바꿔 끼운 곳은 여기까지 오지 않아 영향이 없다.
    """
    def refuse(*args, **kwargs):
        raise psycopg.OperationalError("테스트에서는 실제 DB에 붙지 않는다 (backend/tests/conftest.py)")

    monkeypatch.setattr(psycopg, "connect", refuse)


@pytest.fixture(autouse=True)
def _clear_memory_notices():
    """다음 답에 붙일 기억 알림(services/account/memory._notices)은 프로세스 메모리에 있다. 테스트끼리 새지 않게 비운다."""
    from backend.app.services.account import memory

    memory._notices.clear()
    yield
    memory._notices.clear()
