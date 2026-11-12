"""항만 표 시험 (계획 8a). 항만마다 다른 값은 rules/ports.yaml에서만 온다."""

import re
from pathlib import Path

from marvia.tools.ports import Port, port
from marvia.tools.rules import load_rules

SRC = Path(__file__).resolve().parents[2] / "src" / "marvia"


def test_busan_row_carries_every_value_v1_had_fixed_in_code():
    busan = port("KRPUS")
    assert isinstance(busan, Port) and busan.name == "부산" and busan.verified
    assert busan.mof_office == "020"
    assert busan.ref is not None and (busan.ref.lat, busan.ref.lng) == (35.10, 129.05)
    assert busan.stop_radius_nm == 30
    assert (busan.schedule_lookback_days, busan.schedule_lookahead_days, busan.mrn_search_days) == (3, 7, 1)


def test_incheon_row_is_marked_unverified_and_leaves_unknown_cells_empty():
    incheon = port("KRINC")
    assert isinstance(incheon, Port) and incheon.name == "인천" and not incheon.verified
    assert incheon.mof_office == "030"  # v1 기록(09-23)의 청코드. 실제 응답으로는 확인하지 않았다
    # [왜] 기준점과 반경을 부산 값으로 채우면 인천 앞 배를 부산 기준으로 잰다
    assert incheon.ref is None and incheon.stop_radius_nm is None


def test_a_port_outside_the_table_is_none_not_busan():
    assert port("JPOSA") is None and port(None) is None and port("") is None
    assert port("krpus") == port("KRPUS")  # 코드는 대문자로 맞춰 읽는다


def test_no_busan_value_is_written_in_the_code():
    # [왜] v1은 부산 항구 코드, 청코드, 기준점을 코드와 Skill에 고정했다. v2는 표에서만 받는다
    for path in (SRC / "tools").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        code = "\n".join(
            line.split("#")[0] for line in text.splitlines() if not line.lstrip().startswith(('"""', "#"))
        )
        # 찾는 값은 항만 표에서 읽는다. 따옴표 꼴이나 소수 끝자리가 달라도 잡는다
        for row in load_rules("ports")["ports"].values():
            if row.get("mof_office"):
                assert not re.search(rf"""["']{row["mof_office"]}["']""", code), (
                    path.name,
                    row["mof_office"],
                )
            for number in (row.get("ref") or {}).values():
                digits = f"{number:.2f}".rstrip("0")
                assert not re.search(rf"(?<![\d.]){re.escape(digits)}0*(?![\d])", code), (path.name, number)
        for port_code in load_rules("ports")["ports"]:
            assert port_code not in code, (path.name, port_code)
