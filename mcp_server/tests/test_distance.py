"""B7 estimate_distance 단위 테스트. searoute는 로컬 계산이라 외부 호출 없음."""
from mcp_server.rules import rule
from mcp_server.tools.distance import estimate_distance


def test_southampton_to_busan_matches_prd_check():
    # PRD 6.6 검증값: 사우샘프턴 → 부산 10,694해리
    r = estimate_distance(50.90, -1.40)
    assert 10_600 < r["distance_nm"] < 10_800
    assert r["source"] == "searoute" and r["fetched_at"]


def test_vessel_at_busan_north_port_is_near_zero():
    # fixture position_busan_anchored와 같은 좌표 (부산 북항)
    r = estimate_distance(35.12157, 129.053445)
    assert r["distance_nm"] < 5


def test_calc_hours_only_when_moving():
    assert estimate_distance(34.0, 128.5, sog=12)["calc_hours_at_sog"] > 0
    assert estimate_distance(34.0, 128.5, sog=0)["calc_hours_at_sog"] is None
    assert estimate_distance(34.0, 128.5)["calc_hours_at_sog"] is None


def test_out_of_range_returns_error_not_exception():
    r = estimate_distance(123.0, 129.0)
    assert r["error"]["code"] == "bad_input" and r["error"]["retryable"] is False


def test_busan_ref_comes_from_rules_md():
    """기준점은 코드 상수가 아니라 rules.md busan_ref가 원본이다 (C6)."""
    r = estimate_distance(34.0, 128.5)
    assert r["busan_ref"] == rule("busan_ref")
