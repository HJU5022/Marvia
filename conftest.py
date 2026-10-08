"""테스트 공통 설정.

- ShipFinderClient.cache는 클래스 변수라 테스트 사이에 값이 남는다. 한 테스트가 캐시에 넣은
  값이 다음 테스트의 실패 경로를 가리지 않도록 매번 비운다.
- ShipFinder 하루 한도 소진 표시(status 38)도 모듈 변수라 남는다. 한 테스트가 38을 받으면 같은 날 다른 테스트의
  호출이 모두 막히므로 같이 지운다 (clients/shipfinder.py reset_quota_block).
- 재시도 백오프는 0으로 둔다. 실제 대기는 운영에서만 의미가 있고 테스트는 빨라야 한다.
"""
import pytest

from backend.app.clients import mof, retry
from backend.app.clients.shipfinder import ShipFinderClient, reset_quota_block


@pytest.fixture(autouse=True)
def clear_shipfinder_cache():
    ShipFinderClient.cache.clear()
    reset_quota_block()
    yield
    ShipFinderClient.cache.clear()
    reset_quota_block()


@pytest.fixture(autouse=True)
def reset_mof_circuit():
    """MOF 연결 실패 차단기도 모듈 변수라 테스트 사이에 남는다 (clients/mof.py)."""
    mof.reset_circuit()
    yield
    mof.reset_circuit()


@pytest.fixture(autouse=True)
def no_retry_backoff(monkeypatch):
    monkeypatch.setattr(retry, "BACKOFF_SEC", 0)


@pytest.fixture
def anyio_backend():
    """anyio 표시가 붙은 비동기 테스트는 asyncio로만 돌린다 (trio는 쓰지 않는다)."""
    return "asyncio"
