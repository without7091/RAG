from unittest.mock import AsyncMock

import pytest

from app.api.v1.retrieve import _stream_retrieval, retrieve
from app.schemas.retrieve import RetrieveRequest, RetrieveResponse


@pytest.mark.asyncio
async def test_retrieve_route_passes_context_synthesis_flag():
    request = RetrieveRequest(
        user_id="user1",
        knowledge_base_id="kb1",
        query="what is rag",
        stream=False,
        enable_context_synthesis=False,
        enable_query_rewrite=True,
        query_rewrite_debug=True,
    )
    retrieval_service = AsyncMock()
    retrieval_service.retrieve = AsyncMock(return_value={
        "source_nodes": [],
        "total_candidates": 0,
        "top_k_used": 20,
        "top_n_used": 3,
        "min_score_used": 0.1,
        "enable_reranker_used": True,
        "enable_context_synthesis_used": False,
        "debug": {
            "query_plan": {
                "enabled": True,
                "strategy": "expand",
                "canonical_query": "what is rag",
                "generated_queries": [],
                "final_queries": ["what is rag"],
                "reasons": [],
                "fallback_used": False,
                "model": "Qwen/Qwen3.5-4B",
            },
            "candidate_stats": {
                "query_count": 1,
                "raw_candidate_count": 0,
                "merged_candidate_count": 0,
                "rerank_pool_size": 0,
            },
        },
    })

    response = await retrieve(request, retrieval_service)

    assert isinstance(response, RetrieveResponse)
    assert response.enable_context_synthesis_used is False
    assert response.debug is not None
    assert response.debug.query_plan is not None
    retrieval_service.retrieve.assert_awaited_once_with(
        knowledge_base_id="kb1",
        query="what is rag",
        top_k=20,
        top_n=3,
        min_score=None,
        enable_reranker=True,
        enable_context_synthesis=False,
        enable_query_rewrite=True,
        query_rewrite_debug=True,
    )


@pytest.mark.asyncio
async def test_stream_retrieval_emits_embedding_query_step():
    request = RetrieveRequest(
        user_id="user1",
        knowledge_base_id="kb1",
        query="what is rag",
        stream=True,
        enable_query_rewrite=False,
    )
    retrieval_service = AsyncMock()
    retrieval_service.retrieve = AsyncMock(return_value={
        "source_nodes": [],
        "total_candidates": 0,
        "top_k_used": 20,
        "top_n_used": 3,
        "min_score_used": 0.1,
        "enable_reranker_used": True,
        "enable_context_synthesis_used": True,
    })

    events = []
    async for item in _stream_retrieval(request, retrieval_service):
        events.append(item)

    status_payloads = [item["data"] for item in events if item["event"] == "status"]
    assert any('"step": "embedding_query"' in payload for payload in status_payloads)
