"""OpenRouter로 임베딩과 리랭커를 부른다 (설계 13절, 2절 결정 14).

하지 않는 일: 재시도. 실패하면 httpx 오류를 그대로 올린다(색인 스크립트는 다시 돌리면 덮어쓴다).
[주의] OpenRouter가 Voyage에 dimensions·input_type을 넘기는지 문서에 없어(10-30) 보내지 않는다.
대신 받은 벡터의 차원을 설정 embed_dim과 비교한다.
"""

from __future__ import annotations

import httpx

from marvia.config import Settings


def _client(settings: Settings, transport: httpx.BaseTransport | None) -> httpx.Client:
    """키를 머리글에 붙인 HTTP 클라이언트. transport는 테스트가 가짜 응답을 끼울 때만 쓴다."""
    key = settings.openrouter_api_key.get_secret_value()
    if not key:
        raise RuntimeError("MARVIA_OPENROUTER_API_KEY가 비어 있습니다. .env를 확인하세요")
    return httpx.Client(
        base_url=settings.openrouter_url,
        headers={"Authorization": f"Bearer {key}"},
        timeout=60,
        transport=transport,
    )


def embed(
    texts: list[str], settings: Settings, transport: httpx.BaseTransport | None = None
) -> list[list[float]]:
    """글 목록을 벡터 목록으로 바꾼다. 순서는 넣은 순서와 같다."""
    with _client(settings, transport) as client:
        response = client.post("/embeddings", json={"model": settings.embed_model, "input": texts})
        response.raise_for_status()
    # [왜] 응답의 순서가 넣은 순서라는 말이 문서에 없다. 각 항목의 index로 다시 맞춘다
    data = sorted(response.json()["data"], key=lambda item: item["index"])
    vectors = [item["embedding"] for item in data]
    for vector in vectors:
        if len(vector) != settings.embed_dim:
            raise ValueError(
                f"임베딩 차원이 {len(vector)}이다. 설정 embed_dim({settings.embed_dim})과 DB 표를 맞춘다"
            )
    return vectors


def rerank(
    query: str, documents: list[str], settings: Settings, transport: httpx.BaseTransport | None = None
) -> list[float]:
    """질문과 문서마다 관련 점수를 매긴다. documents와 같은 순서의 점수 목록을 돌려준다."""
    with _client(settings, transport) as client:
        response = client.post(
            "/rerank", json={"model": settings.rerank_model, "query": query, "documents": documents}
        )
        response.raise_for_status()
    scores = [0.0] * len(documents)
    for result in response.json()["results"]:  # 결과는 점수 순서로 오고, index가 원래 자리다
        scores[result["index"]] = result["relevance_score"]
    return scores
