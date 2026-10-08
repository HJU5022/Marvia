"""skills/*/rules.md 합쳐 읽기 (services/judge/rules.py, Skill 구조).

- 폴더마다 rules.md 프론트매터를 한 dict로 합친다. 부르는 쪽은 키가 어느 파일에 있는지 몰라도 된다
- 같은 키가 두 파일에 있으면 실패한다 (결정마다 권한자 하나, 강사 피드백)
- 통관 정상 단계 목록은 customs-stages/rules.md YAML에서 읽는다
- 부산 항구 코드는 코드 상수가 아니라 port-busan/rules.md busan_port_code다
- Skill 폴더마다 SKILL.md와 rules.md가 있고, SKILL.md 프론트매터 name은 폴더 이름과 같다 (Agent Skills 규격)
"""
import pytest

from backend.app.services.judge import rules
from backend.app.services.judge.rules import customs_stage_names, load_rules, rule, stage_key
from backend.app.services.judge.signals import _dest_changed


def _write_rules(folder, body: str) -> None:
    folder.mkdir(parents=True)
    (folder / "rules.md").write_text(f"---\n{body}\n---\n\n# 설명\n", encoding="utf-8")


def test_merges_every_skill_rules_file():
    merged = load_rules()
    # 폴더마다 대표 키 하나씩: 네 파일이 모두 합쳐졌는지
    assert merged["position_stale_hours"] == rule("position_stale_hours")  # ais-reliability
    assert "customs_stages" in merged                                     # customs-stages
    assert "busan_ref" in merged                                          # port-busan
    assert "margin_act_days" in merged                                    # cargo-verdict


def test_each_rules_file_has_its_own_keys():
    """키가 옮겨진 자리를 고정한다. 다른 파일로 옮기면 이 테스트를 같이 고친다."""
    expected = {
        "ais-reliability": {"position_stale_hours", "eta_conflict_hours", "anchor_speed_kn", "anchor_wait_hours",
                            "navstat_moored_max_kn", "navstat_underway_min_kn", "priority", "api_cache_ttl_hours"},
        "customs-stages": {"customs_hold_words", "customs_stages", "customs_subject_words", "customs_assessment_words",
                           "customs_done_words", "customs_done_stages", "customs_done_except_words"},
        "port-busan": {"busan_ref", "busan_radius_nm", "busan_port_code", "port_schedule_lookback_days",
                       "port_schedule_lookahead_days", "port_schedule_name_match_ratio"},
        "cargo-verdict": {"margin_act_days", "act_signals", "gray_signals", "ignore_signals", "ignore_dest_values",
                          "sale_date_words", "sale_passed_words", "plan_compare_words", "sale_compare_words"},
        "referrals": {"signal_referrals", "referral_order", "referral_max", "referral_prefix", "signal_referral_links",
                      "broker_referral", "out_of_scope"},
    }
    for folder, keys in expected.items():
        assert set(rules._front_matter(rules.SKILLS_DIR / folder / "rules.md")) == keys, folder


def test_merged_from_temp_folder(tmp_path):
    _write_rules(tmp_path / "a-skill", "x: 1")
    _write_rules(tmp_path / "b-skill", "y: [p, q]")
    assert load_rules(tmp_path) == {"x": 1, "y": ["p", "q"]}


def test_duplicate_key_in_two_files_fails(tmp_path):
    _write_rules(tmp_path / "a-skill", "same_key: 1")
    _write_rules(tmp_path / "b-skill", "same_key: 2")
    with pytest.raises(ValueError, match="same_key"):
        load_rules(tmp_path)


def test_missing_key_fails():
    with pytest.raises(KeyError):
        rule("no_such_key")


def test_customs_stage_names_come_from_rules_yaml():
    stages = rule("customs_stages")
    assert {stage_key(s["name"]) for s in stages} == customs_stage_names()
    # 목록 항목은 name·meaning·next·todo 네 칸이다. 반출신고는 끝 단계라 next가 null
    assert all(set(s) == {"name", "meaning", "next", "todo"} for s in stages)
    last = next(s for s in stages if s["name"] == "반출신고")
    assert last["next"] is None


def test_busan_port_code_is_read_from_rules():
    assert rule("busan_port_code") == "KRPUS"
    signal = _dest_changed({"destcode": rule("busan_port_code")})
    assert (signal.state, signal.threshold) == ("clear", rule("busan_port_code"))


def test_busan_port_code_change_is_followed(monkeypatch):
    """코드가 상수 대신 rules.md 값을 따르는지: 값을 바꾸면 판단도 바뀐다."""
    original = load_rules()
    monkeypatch.setattr(rules, "load_rules", lambda *a, **k: {**original, "busan_port_code": "KRXXX"})
    assert _dest_changed({"destcode": "KRPUS"}).state == "triggered"
    assert _dest_changed({"destcode": "KRXXX"}).state == "clear"


def test_every_skill_folder_has_skill_and_rules_with_spec_front_matter():
    folders = sorted(p for p in rules.SKILLS_DIR.iterdir() if p.is_dir())
    assert {f.name for f in folders} == {"ais-reliability", "customs-stages", "port-busan", "cargo-verdict", "referrals", "import-basics"}
    for folder in folders:
        # import-basics는 글만 있는 Skill이다 (코드가 읽는 재료 없음). rules.md가 없어도 load_rules가 건너뛴다
        assert (folder / "rules.md").is_file() or folder.name == "import-basics", folder.name
        front = rules._front_matter(folder / "SKILL.md")
        assert front["name"] == folder.name
        assert front["description"].strip()
