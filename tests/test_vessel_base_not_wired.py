"""측정 커밋(48ca3c5)의 파일 묶음이 그대로임을 고정한다 (계획 8a, 계획 8b에서 다섯 파일을 뺌).

본 측정은 끝났다. 이 고정의 목적은 이제 "배 식별 스위치가 꺼진 길이 그대로"를 지키는 것이다.
계획 8b는 배 식별 단계를 스위치(MARVIA_VESSEL, 기본 off) 뒤에 더하며 다섯 파일을 고친다:
graph/main.py, graph/state.py, server.py, view.py, trace.py. 그 다섯만 묶음에서 빼고
"꺼져 있으면 동작이 같다"를 tests/graph/test_vessel_off.py가 본다. 나머지 묶음과 값은 그대로다.

계획 8c는 모델이 배 판정을 읽는 길을 스위치 뒤에 더하며 graph/agent.py, graph/tools.py, graph/verify.py,
rules/verify.yaml, eval/dataset.py, eval/metrics.py, eval/run.py, scripts/run_eval.py를 고친다. 그 파일들은
묶음에서 이름으로 빼고 tests/graph/test_vessel_off_inputs.py(도구 인자 꼴, 도구 결과 글, 검증자,
트레이스 가림)와 tests/eval/test_run_eval_cli.py(평가 지표 다시 세기)가 지킨다.
새 prompts/vessel_*.md는 묶음에 없다.

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
MEASURED_CARGOS = ("DEMO0001", "DEMO0002", "DEMO0003", "MOCK12345678", "TEST87654321")
# [왜] agent, tools, verify는 계획 8c가 고친다(도구 셋, 지시문 조각을 잇는 자리, 검증자 새 규칙).
#      그 셋은 묶음에서 빼고 tests/graph/test_vessel_off_inputs.py가 "꺼져 있으면 모델 입력이 같다"로 묶는다
GRAPH_FILES = (
    "__init__",
    "answer",
    "identify",
    "live",
    "rag",
    "resume",
    "schemas",
    "supervisor",
)
PROMPT_FILES = (
    "agent agent_turn cli_transcript conversation_summary item_facts item_graph memory official plan "
    "rag_analyze rag_context rag_grade rag_rewrite research research_turn sub_cargo sub_item sub_law "
    "sub_turn summary supervisor todos_system todos_tool write"
).split()
# 묶음 이름 → (파일을 고르는 glob 목록, 측정 커밋의 sha256)
GROUPS: dict[str, tuple[list[str], str]] = {
    # [왜] prompts/*.md가 아니라 이름으로 적는다. 계획 8c의 새 조각(prompts/vessel_*.md)은 묶음에 없다
    "지시문": (
        [f"prompts/{name}.md" for name in PROMPT_FILES],
        "56a43bb60bac04e7796db22cf85a2c10f31152eaccba730f36ccb61d584029d3",
    ),
    "규칙(에이전트·검색·기한·재수입·식별·평가)": (
        [f"rules/{name}.yaml" for name in ("agent", "rag", "deadlines", "reimport", "identify", "eval")],
        "0725b7cd0f475d61a4ec72860ec42546672074bfa664121308bb78fa0725bb12",
    ),
    # [왜] 폴더 전체가 아니라 이름으로 적는다. main.py와 state.py(계획 8b가 고침)와 새 파일 vessel.py,
    #      계획 8c가 고치는 agent.py·tools.py·verify.py와 새 파일 vessel_text.py는 뺀다
    "그래프(main·state·agent·tools·verify 제외)": (
        [f"src/marvia/graph/{name}.py" for name in GRAPH_FILES],
        "c1cf6860407d6e297b4d343b6f8807ce8f363fdbc8fa5483ba724876e8fb0eef",
    ),
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
        # [왜] 측정에 쓴 다섯 화물만 묶는다. 계획 8b가 더한 화물(TESTVSL000x)은 평가 문항이 쓰지 않는다
        [f"fixtures/unipass/{name}.json" for name in MEASURED_CARGOS],
        "6e67943f9416bd31e256b5c04c553fa746c55e5844b962967df08b1005f8385b",
    ),
    # 아래 다섯 묶음은 11-13에 더했다. 값은 측정 커밋과 같음을 git diff로 확인한 뒤 적었다.
    # [주의] config.py, identify/models.py, tools/unipass.py, rules/verdict.yaml은 계획 8a가 칸을 더해
    #        측정 커밋과 다르다. 여기에 넣지 않았고, 모델이 보는 쪽은 아래 화물 줄·도구 설명 시험이 본다
    "평가 실행기": (
        [
            # [왜] dataset.py, metrics.py, run.py, scripts/run_eval.py는 계획 8c가 고친다. 평가 지표 계산은
            #      tests/eval/test_run_eval_cli.py가 저장한 실행 열 개를 다시 세어 지킨다 (R-154)
            "src/marvia/eval/retrieval.py",
        ],
        "0d11f51686d80987810e63464e3dd72c8c7fd6cfc6d9116feeabc3055e5bccc4",
    ),
    # server.py, view.py, trace.py는 계획 8b가 고쳐서 뺐다
    "감시·지시문 읽기·추적 연결·DB·로그인": (
        [
            "src/marvia/watch.py",
            "src/marvia/prompts.py",
            "src/marvia/langfuse_trace.py",
            "src/marvia/db.py",
            "src/marvia/auth.py",
        ],
        "d6f476b730ef576b312e4e4e45c006c7b3ebaad561a156e9337e4548525b5303",
    ),
    "화물 조회 도구": (
        ["src/marvia/tools/unipass_replay.py", "src/marvia/tools/verdict.py", "src/marvia/tools/rules.py"],
        "373729b83e98295c364a460a5ae7a0433448b1d6d29038787b0387cbb9b454b8",
    ),
    # [왜] rules/verify.yaml은 계획 8c가 고친다(검증자 새 규칙 낱말).
    #      그 값은 test_vessel_off_inputs.py의 VERIFY_SHA가 지킨다
    "규칙(그래프·화물 조회·서버·값)": (
        [
            "rules/graph.yaml",
            "rules/unipass.yaml",
            "rules/server.yaml",
            "rules/pricing.yaml",
        ],
        "f3a8e8f368cab8e1c01075c2e1ebef99751357dfac61880992c5cc34d97a27b5",
    ),
    "의존성과 DB 틀": (
        ["pyproject.toml", "uv.lock", "migrations/*.sql"],
        "3f943d9cf97ada312757d5dbf95e73b36b12ee1b2bc284aac4bc3b6a2d614de8",
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
# 배 식별 단계(계획 8b)는 graph/vessel.py 한 파일만 판정·조회 모듈을 부른다
ALLOWED = {"src/marvia/eval/verdict_set.py", "src/marvia/graph/vessel.py"}
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
            # [왜] `from marvia import tools` 뒤 `tools.judge`로 쓰는 꼴도 `tools.이름`에 걸린다
            assert f"tools.{name}" not in text and f"tools import {name}" not in text, (path.name, name)
