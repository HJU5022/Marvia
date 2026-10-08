"""B7 estimate_distance 단위 테스트. searoute는 로컬 계산이라 외부 호출 없음."""
from backend.app.services.judge.rules import rule
from mcp_server.tools.distance import estimate_distance


def test_southampton_to_busan_matches_prd_check():
    # PRD 6.6 검증값: 사우샘프턴 → 부산 10,694해리
    r = estimate_distance(50.90, -1.40)
    assert 10_600 < r["distance_nm"] < 10_800
    assert r["source"] == "searoute" and r["fetched_at"]
    assert set(r) == {"distance_nm", "calc_hours_at_sog", "source", "fetched_at"}  # 계약 C4 그대로


def test_vessel_at_busan_north_port_is_near_zero():
    # fixture position_busan_anchored와 같은 좌표 (부산 북항)
    r = estimate_distance(35.1, 129.05)
    assert r["distance_nm"] < 5


def test_calc_hours_only_when_moving():
    assert estimate_distance(34.0, 128.5, sog=12)["calc_hours_at_sog"] > 0
    assert estimate_distance(34.0, 128.5, sog=0)["calc_hours_at_sog"] is None
    assert estimate_distance(34.0, 128.5)["calc_hours_at_sog"] is None


def test_out_of_range_returns_error_not_exception():
    r = estimate_distance(123.0, 129.0)
    assert r["error"]["code"] == "bad_input" and r["error"]["retryable"] is False


def test_busan_ref_comes_from_rules_md(monkeypatch):
    """기준점은 코드 상수가 아니라 rules.md busan_ref가 원본이다 (C6)."""
    from mcp_server.tools import distance

    base = estimate_distance(34.0, 128.5)["distance_nm"]
    monkeypatch.setattr(distance, "_busan_ref", lambda: (rule("busan_ref")["lat"] + 1.0, rule("busan_ref")["lng"]))
    distance._busan_node.cache_clear()
    assert estimate_distance(34.0, 128.5)["distance_nm"] != base
