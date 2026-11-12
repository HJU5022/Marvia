"""배 추적 기반(계획 8a)은 그래프에 연결하지 않는다. 측정 커밋(48ca3c5)의 평가 조건이 그대로임을 고정한다.

묶음마다 파일 이름과 내용을 이어 sha256 하나로 묶었다. 값은 측정 커밋의 것이다.
연결하는 계획(도구 목록·지시문·화물 줄을 바꾸는 계획)은 바뀐 묶음의 값을 함께 바꾸고 그 까닭을 적는다.
이 시험이 실패하면 값을 고치기 전에 어느 묶음의 무엇이 바뀌었는지부터 본다.
"""

import hashlib
from datetime import date
from pathlib import Path

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

from marvia.graph.answer import cargo_lines
from marvia.graph.tools import make_tools

ROOT = Path(__file__).resolve().parents[1]
# 묶음 이름 → (파일을 고르는 glob 목록, 측정 커밋의 sha256)
GROUPS: dict[str, tuple[list[str], str]] = {
    "지시문": (["prompts/*.md"], "56a43bb60bac04e7796db22cf85a2c10f31152eaccba730f36ccb61d584029d3"),
    "규칙(에이전트·검색·기한·재수입·식별·평가)": (
        [f"rules/{name}.yaml" for name in ("agent", "rag", "deadlines", "reimport", "identify", "eval")],
        "0725b7cd0f475d61a4ec72860ec42546672074bfa664121308bb78fa0725bb12",
    ),
    "그래프": (["src/marvia/graph/*.py"], "ff0635075c9c63f217dedee43cb2e882816513920b53533782ab5bcf9e3d09f5"),
    "검색": (["src/marvia/rag/*.py"], "fcab4969270619777247aeee8325aa3db33f4116350fd25ace3342214e355eac"),
    "가림과 번호 읽기": (
        ["src/marvia/identify/mask.py", "src/marvia/identify/parse.py"],
        "eebbce94caa86d2138a1fd164ea1eab1d0ec3721ef5ec147621a5475fc2c62e4",
    ),
    "계산 도구": (
        ["src/marvia/tools/deadlines.py", "src/marvia/tools/reimport.py"],
        "051f399af17e05ee5a78d96e5f83fbd127c250dd93df99a133aa30d315766cc4",
    ),
    "모델 길": (
        ["src/marvia/llm.py", "src/marvia/cli_model.py"],
        "91ac1ac2ec147c7d791c16f016510432d3e583b5899f6fb114531a61bd760b02",
    ),
    "평가셋 v3": (["eval/set_v3.yaml"], "e222b902acec89b9ba121e3c4b3361827ec37161e0b9c98b6f63ee63b0a8b705"),
    "재생 화물": (
        ["fixtures/unipass/*.json"],
        "6e67943f9416bd31e256b5c04c553fa746c55e5844b962967df08b1005f8385b",
    ),
}
# 모델이 보는 도구 이름과 설명을 한 줄씩 이어 sha256
TOOLS_SHA = "7f9bab1a8e427c493f149681334714125e9d1edd8084d48008f7db62b3670185"
# 그래프, 서버, 평가 실행기 쪽. 여기서 아래 새 모듈을 가져다 쓰면 연결된 것이다
WIRED_DIRS = ["src/marvia/graph", "src/marvia/rag", "src/marvia/identify", "src/marvia/eval"]
WIRED_FILES = [
    "src/marvia/server.py",
    "src/marvia/watch.py",
    "src/marvia/view.py",
    "src/marvia/llm.py",
    "src/marvia/cli_model.py",
    "scripts/run_eval.py",
]
# [왜] 판정 평가 문항을 돌리는 코드는 판정 함수를 부르는 것이 일이다. 에이전트 평가 실행기(run.py)와
#      다른 파일이다
ALLOWED = {"src/marvia/eval/verdict_set.py"}
NEW_MODULES = ["ports", "vessel", "signals", "judge", "vessel_match", "mof", "shipfinder"]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _group_sha(patterns: list[str]) -> tuple[str, int]:
    files = sorted({p for pattern in patterns for p in ROOT.glob(pattern)})
    return _sha("".join(f"{p.relative_to(ROOT)}\n{p.read_text(encoding='utf-8')}" for p in files)), len(files)


def test_every_measured_file_group_is_that_of_the_measurement_commit():
    changed = []
    for name, (patterns, recorded) in GROUPS.items():
        found, count = _group_sha(patterns)
        assert count >= len(patterns), name  # 폴더 이름이 바뀌어 아무것도 안 보는 일을 막는다
        if found != recorded:
            changed.append(name)
    assert changed == []


def test_tool_names_and_descriptions_are_those_of_the_measurement_commit():
    # [왜] 도구가 하나 늘거나 설명 한 글자가 바뀌어도 모델의 선택이 달라져 평가 조건이 바뀐다
    tools = make_tools(
        None,
        date.today,
        provision=lambda label, as_of: [],
        model=GenericFakeChatModel(messages=iter([])),
    )
    seen = "".join(f"{t.name}\n{t.description}\n" for t in sorted(tools, key=lambda t: t.name))
    assert _sha(seen) == TOOLS_SHA


def test_cargo_line_shows_only_token_stage_port_and_date():
    # [왜] 배 이름·양륙항 코드·입항일 같은 새 칸이 화물 사실에 생겨도 모델이 보는 화물 줄은 그대로다
    facts = {
        "stage": "반입신고",
        "stage_at": "2026-10-27T09:00:00+09:00",
        "port": "부산",
        "vessel_name": "TEST VESSEL ONE",
        "port_code": "KRPUS",
        "entry_date": "2026-10-26",
        "loading_port": "QINGDAO",
        "vessel_flag": "PA",
        "voyage": "0012W",
        "shed": "TEST터미널 CY",
    }
    assert cargo_lines([{"token": "[BL1]", "facts": facts, "error": None}]) == [
        "[BL1]: 반입신고 (부산) 2026-10-27"
    ]


def test_nothing_in_the_graph_server_or_eval_runner_imports_the_vessel_base():
    files = [p for d in WIRED_DIRS for p in (ROOT / d).rglob("*.py")] + [ROOT / f for f in WIRED_FILES]
    files = [p for p in files if str(p.relative_to(ROOT)) not in ALLOWED]
    assert len(files) > 40
    for path in files:
        text = path.read_text(encoding="utf-8")
        for name in NEW_MODULES:
            assert f"marvia.tools.{name}" not in text and f"tools import {name}" not in text, (
                path.name,
                name,
            )
