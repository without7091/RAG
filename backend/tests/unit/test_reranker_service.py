import asyncio

import httpx
import pytest
import respx

from app.config import Settings
from app.exceptions import RerankerError
from app.services.reranker_service import RerankerService


class TrackingRerankerClient:
    def __init__(self):
        self.current_in_flight = 0
        self.max_in_flight = 0

    async def post(self, url: str, *, json: dict, headers: dict):
        self.current_in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.current_in_flight)
        await asyncio.sleep(0.05)
        self.current_in_flight -= 1
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "results": [
                    {"index": index, "relevance_score": 1.0 - (index * 0.1)}
                    for index, _ in enumerate(json["documents"])
                ]
            },
        )


@pytest.fixture
def mock_client():
    return httpx.AsyncClient()


@pytest.fixture
def reranker_service(mock_client):
    return RerankerService(client=mock_client)


class TestRerankerService:
    @respx.mock
    async def test_rerank_success(self, reranker_service):
        respx.post("https://api.siliconflow.cn/v1/rerank").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {"index": 2, "relevance_score": 0.95},
                        {"index": 0, "relevance_score": 0.80},
                        {"index": 1, "relevance_score": 0.30},
                    ]
                },
            )
        )

        results = await reranker_service.rerank(
            "test query", ["text A", "text B", "text C"], top_n=2
        )
        assert len(results) == 2
        assert results[0]["score"] == 0.95
        assert results[0]["index"] == 2
        assert results[1]["score"] == 0.80

    @respx.mock
    async def test_rerank_sorted_descending(self, reranker_service):
        respx.post("https://api.siliconflow.cn/v1/rerank").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {"index": 0, "relevance_score": 0.3},
                        {"index": 1, "relevance_score": 0.9},
                    ]
                },
            )
        )

        results = await reranker_service.rerank("q", ["a", "b"], top_n=2)
        assert results[0]["score"] >= results[1]["score"]

    async def test_rerank_empty_list(self, reranker_service):
        results = await reranker_service.rerank("query", [], top_n=3)
        assert results == []

    @respx.mock
    async def test_rerank_api_error_raises(self, reranker_service):
        respx.post("https://api.siliconflow.cn/v1/rerank").mock(
            return_value=httpx.Response(500, json={"error": "fail"})
        )

        with pytest.raises(RerankerError):
            await reranker_service.rerank("q", ["text"], top_n=1)

    @respx.mock
    async def test_rerank_correct_model(self, reranker_service):
        route = respx.post("https://api.siliconflow.cn/v1/rerank").mock(
            return_value=httpx.Response(
                200,
                json={"results": [{"index": 0, "relevance_score": 0.5}]},
            )
        )

        await reranker_service.rerank("q", ["text"], top_n=1)
        import json

        body = json.loads(route.calls[0].request.content)
        assert body["model"] == "Qwen/Qwen3-Reranker-4B"
        assert body["query"] == "q"
        assert body["documents"] == ["text"]

    @respx.mock
    async def test_rerank_top_n_truncation(self, reranker_service):
        respx.post("https://api.siliconflow.cn/v1/rerank").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {"index": 0, "relevance_score": 0.9},
                        {"index": 1, "relevance_score": 0.8},
                        {"index": 2, "relevance_score": 0.7},
                    ]
                },
            )
        )

        results = await reranker_service.rerank("q", ["a", "b", "c"], top_n=1)
        assert len(results) == 1

    @respx.mock
    async def test_rerank_list_response_format(self, reranker_service):
        """Test handling when API returns a list directly instead of dict."""
        respx.post("https://api.siliconflow.cn/v1/rerank").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"index": 0, "score": 0.9},
                    {"index": 1, "score": 0.1},
                ],
            )
        )

        results = await reranker_service.rerank("q", ["a", "b"], top_n=2)
        assert len(results) == 2

    @respx.mock
    async def test_rerank_retries_retryable_503(self, mock_client):
        route = respx.post("https://api.siliconflow.cn/v1/rerank").mock(
            side_effect=[
                httpx.Response(
                    503,
                    json={"error": "busy"},
                    request=httpx.Request("POST", "https://api.siliconflow.cn/v1/rerank"),
                ),
                httpx.Response(
                    200,
                    json={"results": [{"index": 0, "relevance_score": 0.8}]},
                ),
            ]
        )
        service = RerankerService(client=mock_client)

        results = await service.rerank("q", ["text"], top_n=1)

        assert len(results) == 1
        assert len(route.calls) == 2

    async def test_rerank_requests_share_concurrency_gate(self):
        settings = Settings(
            siliconflow_api_key="test-key",
            reranker_concurrency=1,
            _env_file=None,
        )
        client = TrackingRerankerClient()
        service = RerankerService(client=client, settings=settings)

        await asyncio.gather(
            service.rerank("query-1", ["a", "b"], top_n=1),
            service.rerank("query-2", ["c", "d"], top_n=1),
        )

        assert client.max_in_flight == 1
