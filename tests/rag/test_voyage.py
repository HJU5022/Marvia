import json

import httpx
import pytest

from marvia.config import Settings
from marvia.rag.voyage import embed, rerank

# [왜] 진짜처럼 보이지 않는 가짜 키. embed_dim=3으로 짧은 벡터를 쓴다
SETTINGS = Settings(_env_file=None, voyage_api_key="pa-test-not-real", embed_dim=3)


def test_embed_sends_model_and_orders_by_index():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        # 일부러 순서를 뒤집어 돌려준다
        data = [{"index": 1, "embedding": [0.0, 1.0, 0.0]}, {"index": 0, "embedding": [1.0, 0.0, 0.0]}]
        return httpx.Response(200, json={"data": data})

    # [왜] MockTransport는 인터넷에 나가지 않고 handler가 만든 응답을 돌려준다
    vectors = embed(["가", "나"], SETTINGS, "document", transport=httpx.MockTransport(handler))
    assert vectors == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    assert seen["url"] == "https://api.voyageai.com/v1/embeddings"
    assert seen["auth"] == "Bearer pa-test-not-real"
    assert seen["body"] == {
        "model": "voyage-4",
        "input": ["가", "나"],
        "input_type": "document",
        "output_dimension": 3,
    }


def test_embed_rejects_wrong_dimension():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]})

    with pytest.raises(ValueError, match="차원"):
        embed(["가"], SETTINGS, "query", transport=httpx.MockTransport(handler))


def test_rerank_returns_scores_in_document_order():
    def handler(request: httpx.Request) -> httpx.Response:
        results = [{"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.2}]
        return httpx.Response(200, json={"data": results})

    assert rerank("질문", ["a", "b"], SETTINGS, transport=httpx.MockTransport(handler)) == [0.2, 0.9]
