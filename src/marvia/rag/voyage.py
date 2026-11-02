"""Voyage AI API로 임베딩과 리랭커를 부른다 (설계 13절, 2절 결정 14).

하지 않는 일: 재시도. 실패하면 httpx 오류를 그대로 올린다(색인 스크립트는 다시 돌리면 덮어쓴다).
[주의] Anthropic API에는 임베딩·리랭커 모델이 없어 Voyage를 따로 부른다. 키는 MARVIA_VOYAGE_API_KEY.
"""

from __future__ import annotations

from typing import Literal

import httpx

from marvia.config import Settings


def _client(settings: Settings, transport: httpx.BaseTransport | None) -> httpx.Client:
    """키를 머리글에 붙인 HTTP 클라이언트. transport는 테스트가 가짜 응답을 끼울 때만 쓴다."""
    key = settings.voyage_api_key.get_secret_value()
    if not key:
        raise RuntimeError("MARVIA_VOYAGE_API_KEY가 비어 있습니다. .env를 확인하세요")
    return httpx.Client(
        base_url=settings.voyage_url,
        headers={"Authorization": f"Bearer {key}"},
        timeout=60,
        transport=transport,
    )


def embed(
    texts: list[str],
    settings: Settings,
    input_type: Literal["query", "document"],
    transport: httpx.BaseTransport | None = None,
) -> list[list[float]]:
    """글 목록을 벡터 목록으로 바꾼다. 순서는 넣은 순서와 같다."""
    body = {
        "model": settings.embed_model,
        "input": texts,
        # [왜] 검색어는 "query", 색인할 조문은 "document".
        # Voyage가 용도에 맞는 머리말을 붙여 검색이 더 잘 맞는다
        "input_type": input_type,
        "output_dimension": settings.embed_dim,  # [주의] DB 표의 vector(1024)와 같은 값
    }
    with _client(settings, transport) as client:
        response = client.post("/embeddings", json=body)
        response.raise_for_status()
    # [왜] 각 항목에 index가 있다. 순서가 바뀌어 와도 넣은 순서로 다시 맞춘다
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
    for result in response.json()["data"]:  # 결과는 점수 순서로 오고, index가 원래 자리다
        scores[result["index"]] = result["relevance_score"]
    return scores
