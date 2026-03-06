import httpx
import pytest
import respx

from app.config import get_settings
from app.exceptions import EmbeddingError
from app.services.embedding_service import EmbeddingService

EMBEDDING_DIM = get_settings().embedding_dimension


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
                        {"embedding": [0.1] * EMBEDDING_DIM, "index": 0},
                        {"embedding": [0.2] * EMBEDDING_DIM, "index": 1},
                    ]
                },
            )
        )

        results = await embedding_service.embed_texts(["text1", "text2"])
        assert len(results) == 2
        assert len(results[0]) == EMBEDDING_DIM

    @respx.mock
    async def test_embed_query_success(self, embedding_service):
        respx.post("https://api.siliconflow.cn/v1/embeddings").mock(
            return_value=httpx.Response(
                200,
                json={"data": [{"embedding": [0.5] * EMBEDDING_DIM, "index": 0}]},
            )
        )

        result = await embedding_service.embed_query("test query")
        assert len(result) == EMBEDDING_DIM

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
                json={"data": [{"embedding": [0.1] * EMBEDDING_DIM, "index": 0}]},
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
                json={"data": [{"embedding": [0.1] * EMBEDDING_DIM, "index": 0}]},
            )
        )

        await embedding_service.embed_texts(["text"])
        import json

        body = json.loads(route.calls[0].request.content)
        assert body["model"] == "Qwen/Qwen3-Embedding-4B"

    @respx.mock
    async def test_embed_raises_on_invalid_response_structure(self, embedding_service):
        respx.post("https://api.siliconflow.cn/v1/embeddings").mock(
            return_value=httpx.Response(200, json={"unexpected": []})
        )

        with pytest.raises(EmbeddingError, match="Invalid embedding response"):
            await embedding_service.embed_texts(["text"])

    @respx.mock
    async def test_embed_raises_on_dimension_mismatch(self, embedding_service):
        respx.post("https://api.siliconflow.cn/v1/embeddings").mock(
            return_value=httpx.Response(
                200,
                json={"data": [{"embedding": [0.1] * (EMBEDDING_DIM - 1), "index": 0}]},
            )
        )

        with pytest.raises(EmbeddingError, match="dimension"):
            await embedding_service.embed_texts(["text"])

    @respx.mock
    async def test_embed_raises_on_count_mismatch(self, embedding_service):
        respx.post("https://api.siliconflow.cn/v1/embeddings").mock(
            return_value=httpx.Response(
                200,
                json={"data": [{"embedding": [0.1] * EMBEDDING_DIM, "index": 0}]},
            )
        )

        with pytest.raises(EmbeddingError, match="count mismatch"):
            await embedding_service.embed_texts(["text1", "text2"])
