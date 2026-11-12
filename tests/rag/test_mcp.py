"""규정 검색 MCP 서버·클라이언트 시험 (done 2.4, 계획 3b Task 8). 키·DB·네트워크 없이 돈다."""

from datetime import date

import anyio
import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from marvia.graph import rag as rag_module
from marvia.graph.rag import top_ranked
from marvia.rag.mcp import build_server, http_app, mcp_ranked
from marvia.rag.models import Evidence, SearchFailed

AS_OF = date(2026, 11, 6)


def _unit(n: int, origin: str = "hybrid") -> Evidence:
    return Evidence(
        unit_id=f"LTEST@20261002#제{n}조",
        law_name="시험법",
        heading=f"시험법 > 제{n}조",
        effective=date(2026, 10, 2),
        source_url="https://example.test",
        text=f"제{n}조 본문",
        score=0.0,
        origin=origin,
    )


def direct(query: str, as_of: date) -> list[Evidence]:
    """직접 길: 가짜 검색과 리랭커로 top_ranked를 부른다."""
    return top_ranked(
        lambda q, d: [_unit(1), _unit(2, "graph"), _unit(3)], lambda q, t: [0.2, 0.9, 0.5], query, as_of
    )


def test_mcp_path_returns_exactly_what_the_direct_path_returns():
    via_mcp = mcp_ranked(build_server(direct))
    got = via_mcp("수입신고 기한", AS_OF)
    assert got == direct("수입신고 기한", AS_OF)  # unit_id 순서, 점수, 시행일, origin까지 같다
    assert [e.unit_id for e in got] == [
        "LTEST@20261002#제2조",
        "LTEST@20261002#제3조",
        "LTEST@20261002#제1조",
    ]


def test_server_errors_become_search_failures_without_their_text():
    def boom(query: str, as_of: date) -> list[Evidence]:
        raise RuntimeError("postgresql://user:pw@host/db 접속 실패")

    with pytest.raises(SearchFailed, match="mcp_tool_error") as caught:
        mcp_ranked(build_server(boom))("q", AS_OF)
    assert "postgresql" not in str(caught.value)


def test_the_server_checks_query_length_and_date():
    with pytest.raises(SearchFailed):
        mcp_ranked(build_server(direct))("x" * 301, AS_OF)  # rules/rag.yaml mcp.max_query

    async def bad_date():
        async with Client(build_server(direct)) as client:
            return await client.call_tool("search_regulations", {"query": "q", "as_of": "어제"})

    assert anyio.run(bad_date).is_error


async def _over_http(token_sent: str | None):
    """토큰 하나로 HTTP 앱에 붙는다. 맞는 토큰이면 도구 결과, 아니면 상태 코드를 돌려준다."""
    server = build_server(direct)
    app = http_app(server, "test-token")
    async with server.session_manager.run():  # [왜] 앱 수명 주기(lifespan) 대신 세션 관리자를 직접 돌린다
        headers = {"Authorization": f"Bearer {token_sent}"} if token_sent else {}
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(
            transport=transport, base_url="http://127.0.0.1:8766", headers=headers
        ) as http:
            if token_sent != "test-token":
                return (await http.post("/mcp", json={})).status_code
            async with Client(
                streamable_http_client("http://127.0.0.1:8766/mcp", http_client=http)
            ) as client:
                return await client.call_tool(
                    "search_regulations", {"query": "q", "as_of": AS_OF.isoformat()}
                )


def test_http_with_the_token_gives_the_same_units_as_memory():
    result = anyio.run(_over_http, "test-token")
    assert [Evidence.model_validate(u) for u in result.structured_content["units"]] == direct("q", AS_OF)


def test_http_without_or_with_a_wrong_token_is_401():
    assert anyio.run(_over_http, None) == 401
    assert anyio.run(_over_http, "wrong") == 401


def test_an_empty_token_refuses_to_build_the_http_app():
    with pytest.raises(ValueError, match="MARVIA_MCP_TOKEN"):
        http_app(build_server(direct), "")


def test_the_reranker_reads_the_law_name_with_the_body_on_both_paths_and_evidence_text_stays(monkeypatch):
    # [왜] 본문만 보면 리랭커가 "특별법 제45조"와 "특별법 시행규칙 제45조"를 가르지 못한다.
    #      임베딩 글에는 머리글이 있는데 리랭커 글에는 법령 이름이 없었다 (11-13 실측)
    read: list[list[str]] = []

    def scores(query: str, texts: list[str]) -> list[float]:
        read.append(texts)
        return [0.2, 0.9, 0.5]

    def find(query: str, as_of: date) -> list[Evidence]:
        return top_ranked(lambda q, d: [_unit(1), _unit(2), _unit(3)], scores, query, as_of)

    got = find("수입신고 기한", AS_OF)
    assert read[-1] == ["시험법\n제1조 본문", "시험법\n제2조 본문", "시험법\n제3조 본문"]
    # [주의] 근거로 남는 글(작성자와 검증이 읽는 글)은 한 글자도 바뀌지 않는다
    assert [e.text for e in got] == ["제2조 본문", "제3조 본문", "제1조 본문"]
    assert mcp_ranked(build_server(find))("수입신고 기한", AS_OF) == got  # MCP 길도 같은 함수를 탄다
    assert read[-1] == read[0]
    real = rag_module.load_rules

    def off(name: str) -> dict:
        cfg = real(name)
        return cfg | {"search": cfg["search"] | {"rerank_law_name": False}} if name == "rag" else cfg

    monkeypatch.setattr(rag_module, "load_rules", off)
    find("수입신고 기한", AS_OF)
    assert read[-1] == ["제1조 본문", "제2조 본문", "제3조 본문"]  # 끄면 본문만 넘긴다
