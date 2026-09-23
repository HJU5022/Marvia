"""테스트 공통 설정.

ShipFinderClient.cache는 클래스 변수라 테스트 사이에 값이 남는다.
한 테스트가 캐시에 넣은 값이 다음 테스트의 실패 경로를 가리지 않도록 매번 비운다.
"""
import pytest

from backend.app.clients.shipfinder import ShipFinderClient


@pytest.fixture(autouse=True)
def clear_shipfinder_cache():
    ShipFinderClient.cache.clear()
    yield
    ShipFinderClient.cache.clear()
