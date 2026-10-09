"""B9 도구 설명 검사. MCP 클라이언트가 보는 설명이 SDD 5.9 형식을 지키는지 본다.

SDD 5.9: 각 tool description은 "언제 쓰는가" 한 문장 + 입력 설명.
SDD 7절: 도구 설명도 데이터라서 "무조건 믿어라"류 문장을 넣지 않는다. 무엇을 믿을지는 Skill이 정한다.
"""
import pytest

from mcp_server.server import mcp

EXPECTED_TOOLS = {"get_vessel_candidates", "get_live_position", "get_port_schedule", "estimate_distance"}

# 설명에 넣지 않는 판단·지시 표현. 신뢰 순서는 skills/ais-reliability, 등급은 services/judge/verdict.py와 skills/cargo-verdict가 맡는다 (CLAUDE.md 폴더 표)
FORBIDDEN_PHRASES = ("믿는다", "믿어라", "무조건", "판정하지 말고", "되물어야")


@pytest.fixture(scope="module")
def tools():
    import asyncio

    return {t.name: t for t in asyncio.run(mcp.list_tools())}


def test_four_tools_registered(tools):
    assert set(tools) == EXPECTED_TOOLS


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_marked_read_only(tools, name):
    """4종 모두 조회·계산만 해서 읽기 전용 표시(readOnlyHint)가 붙어 있다 (D9 도구 권한 정책)."""
    annotations = tools[name].annotations
    assert annotations is not None, f"{name} 도구 표시(annotations) 없음"
    assert annotations.readOnlyHint is True, f"{name} 읽기 전용 표시 없음"


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_first_line_says_when_to_use(tools, name):
    """첫 줄은 한 문장이고 "~때 쓴다."로 끝난다. mcp_check·mcp_demo가 이 줄을 목록에 보여 준다."""
    first = tools[name].description.strip().splitlines()[0]
    assert first.endswith("때 쓴다."), first
    assert first.count(". ") == 0, f"첫 줄이 한 문장이 아니다: {first}"


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_every_input_has_description(tools, name):
    props = tools[name].inputSchema.get("properties", {})
    assert props
    missing = [arg for arg, schema in props.items() if not schema.get("description")]
    assert not missing, f"{name} 입력 설명 없음: {missing}"


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_no_trust_or_verdict_directive(tools, name):
    text = tools[name].description
    for arg in tools[name].inputSchema.get("properties", {}).values():
        text += arg.get("description", "")
    found = [p for p in FORBIDDEN_PHRASES if p in text]
    assert not found, f"{name} 설명에 판단·지시 표현: {found}"
