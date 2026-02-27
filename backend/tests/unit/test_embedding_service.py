import httpx
import pytest
import respx

from app.exceptions import EmbeddingError
from app.services.embedding_service import EmbeddingService


@pytest.fixture
def mock_client():
    return httpx.AsyncClient()


@pytest.fixture
def embedding_service(mock_client):
    return EmbeddingService(client=mock_client)


class TestEmbeddingService:
    @respx.mock
    async def test_embed_texts_success(self, embedding_service):
        respx.post("https://api.siliconflow.cn/v1/embeddings").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {"embedding": [0.1] * 1024, "index": 0},
                        {"embedding": [0.2] * 1024, "index": 1},
                    ]
                },
            )
        )

        results = await embedding_service.embed_texts(["text1", "text2"])
        assert len(results) == 2
        assert len(results[0]) == 1024

    @respx.mock
    async def test_embed_query_success(self, embedding_service):
        respx.post("https://api.siliconflow.cn/v1/embeddings").mock(
            return_value=httpx.Response(
                200,
                json={"data": [{"embedding": [0.5] * 1024, "index": 0}]},
            )
        )

        result = await embedding_service.embed_query("test query")
        assert len(result) == 1024

    async def test_embed_empty_list(self, embedding_service):
        results = await embedding_service.embed_texts([])
        assert results == []

    @respx.mock
    async def test_embed_api_error_raises(self, embedding_service):
        respx.post("https://api.siliconflow.cn/v1/embeddings").mock(
            return_value=httpx.Response(500, json={"error": "server error"})
        )

        with pytest.raises(EmbeddingError):
            await embedding_service.embed_texts(["text"])

    @respx.mock
    async def test_correct_headers_sent(self, embedding_service):
        route = respx.post("https://api.siliconflow.cn/v1/embeddings").mock(
            return_value=httpx.Response(
                200,
                json={"data": [{"embedding": [0.1] * 1024, "index": 0}]},
            )
        )

        await embedding_service.embed_texts(["text"])
        assert route.called
        request = route.calls[0].request
        assert "Bearer" in request.headers.get("authorization", "")

    @respx.mock
    async def test_correct_model_in_payload(self, embedding_service):
        route = respx.post("https://api.siliconflow.cn/v1/embeddings").mock(
            return_value=httpx.Response(
                200,
                json={"data": [{"embedding": [0.1] * 1024, "index": 0}]},
            )
        )

        await embedding_service.embed_texts(["text"])
        import json

        body = json.loads(route.calls[0].request.content)
        assert body["model"] == "Qwen/Qwen3-Embedding-4B"
