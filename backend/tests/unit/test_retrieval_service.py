"""Unit tests for RetrievalService BM25 integration."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import get_settings
from app.services.query_rewrite_service import RewritePlan
from app.services.retrieval_service import RetrievalService

EMBEDDING_DIM = get_settings().embedding_dimension


@pytest.fixture
def mock_deps():
    embedding = AsyncMock()
    embedding.embed_query = AsyncMock(return_value=[0.1] * EMBEDDING_DIM)

    sparse_embedding = AsyncMock()
    sparse_embedding.embed_query_async = AsyncMock(return_value={"indices": [1], "values": [1.0]})

    vector_store = AsyncMock()
    vector_store.hybrid_search = AsyncMock(return_value=[
        {
            "id": "pt1",
            "score": 0.9,
            "payload": {
                "text": "result text",
                "doc_id": "doc1",
                "file_name": "test.md",
                "knowledge_base_id": "kb1",
                "chunk_index": 0,
            },
        }
    ])
    vector_store.get_chunks_by_doc_id = AsyncMock(return_value=[
        {"chunk_index": 0, "text": "result text", "header_path": "", "header_level": 0, "content_type": "text"},
    ])

    reranker = AsyncMock()
    reranker.rerank = AsyncMock(return_value=[
        {"index": 0, "score": 0.95, "text": "result text"},
    ])

    bm25_service = MagicMock()
    bm25_service.text_to_sparse_vector = MagicMock(
        return_value={"indices": [10, 20], "values": [2.0, 1.0]}
    )

    return {
        "embedding": embedding,
        "sparse_embedding": sparse_embedding,
        "vector_store": vector_store,
        "reranker": reranker,
        "bm25_service": bm25_service,
    }


class TestRetrievalServiceBM25:
    async def test_generates_bm25_query_vector(self, mock_deps):
        """Should call bm25_service.text_to_sparse_vector with the query."""
        svc = RetrievalService(
            embedding_service=mock_deps["embedding"],
            sparse_embedding_service=mock_deps["sparse_embedding"],
            vector_store_service=mock_deps["vector_store"],
            reranker_service=mock_deps["reranker"],
            bm25_service=mock_deps["bm25_service"],
        )

        await svc.retrieve("kb1", "test query", top_k=10, top_n=3)

        mock_deps["bm25_service"].text_to_sparse_vector.assert_called_once_with("test query")

    async def test_passes_bm25_to_hybrid_search(self, mock_deps):
        """Should pass bm25_vector to hybrid_search."""
        svc = RetrievalService(
            embedding_service=mock_deps["embedding"],
            sparse_embedding_service=mock_deps["sparse_embedding"],
            vector_store_service=mock_deps["vector_store"],
            reranker_service=mock_deps["reranker"],
            bm25_service=mock_deps["bm25_service"],
        )

        await svc.retrieve("kb1", "test query", top_k=10, top_n=3)

        call_kwargs = mock_deps["vector_store"].hybrid_search.call_args
        assert call_kwargs.kwargs.get("bm25_vector") == {"indices": [10, 20], "values": [2.0, 1.0]}

    async def test_works_without_bm25_service(self, mock_deps):
        """Should work normally when bm25_service is None."""
        svc = RetrievalService(
            embedding_service=mock_deps["embedding"],
            sparse_embedding_service=mock_deps["sparse_embedding"],
            vector_store_service=mock_deps["vector_store"],
            reranker_service=mock_deps["reranker"],
            bm25_service=None,
        )

        result = await svc.retrieve("kb1", "test query", top_k=10, top_n=3)

        assert len(result["source_nodes"]) > 0
        # hybrid_search should be called without bm25_vector
        call_kwargs = mock_deps["vector_store"].hybrid_search.call_args
        assert call_kwargs.kwargs.get("bm25_vector") is None

    async def test_skips_context_synthesis_when_disabled(self, mock_deps):
        """Should avoid adjacent chunk lookup when context synthesis is disabled."""
        svc = RetrievalService(
            embedding_service=mock_deps["embedding"],
            sparse_embedding_service=mock_deps["sparse_embedding"],
            vector_store_service=mock_deps["vector_store"],
            reranker_service=mock_deps["reranker"],
            bm25_service=mock_deps["bm25_service"],
        )

        result = await svc.retrieve(
            "kb1",
            "test query",
            top_k=10,
            top_n=3,
            enable_context_synthesis=False,
        )

        mock_deps["vector_store"].get_chunks_by_doc_id.assert_not_awaited()
        assert result["enable_context_synthesis_used"] is False
        assert result["source_nodes"][0]["context_text"] == result["source_nodes"][0]["text"]

    async def test_reranker_uses_raw_query_after_query_rewrite(self, mock_deps):
        query_rewriter = AsyncMock()
        query_rewriter.build_plan = AsyncMock(return_value=RewritePlan(
            strategy="expand",
            canonical_query="网关连接失败 故障排查",
            generated_queries=["网关连不上 怎么排查"],
            final_queries=["怎么处理网关连接失败", "网关连接失败 故障排查", "网关连不上 怎么排查"],
            reasons=["llm_expand"],
            fallback_used=False,
            model="Qwen/Qwen3.5-4B",
        ))
        mock_deps["vector_store"].hybrid_search = AsyncMock(side_effect=[
            [
                {
                    "id": "pt1",
                    "score": 0.11,
                    "payload": {
                        "text": "result text",
                        "doc_id": "doc1",
                        "file_name": "test.md",
                        "knowledge_base_id": "kb1",
                        "chunk_index": 0,
                    },
                }
            ],
            [
                {
                    "id": "pt1b",
                    "score": 0.12,
                    "payload": {
                        "text": "result text",
                        "doc_id": "doc1",
                        "file_name": "test.md",
                        "knowledge_base_id": "kb1",
                        "chunk_index": 0,
                    },
                },
                {
                    "id": "pt2",
                    "score": 0.09,
                    "payload": {
                        "text": "second result",
                        "doc_id": "doc2",
                        "file_name": "test2.md",
                        "knowledge_base_id": "kb1",
                        "chunk_index": 1,
                    },
                },
            ],
            [],
        ])
        mock_deps["vector_store"].get_chunks_by_doc_id = AsyncMock(side_effect=[
            [{"chunk_index": 0, "text": "result text", "header_path": "", "header_level": 0, "content_type": "text"}],
            [{"chunk_index": 1, "text": "second result", "header_path": "", "header_level": 0, "content_type": "text"}],
        ])
        mock_deps["reranker"].rerank = AsyncMock(return_value=[
            {"index": 1, "score": 0.97, "text": "second result"},
            {"index": 0, "score": 0.96, "text": "result text"},
        ])

        svc = RetrievalService(
            embedding_service=mock_deps["embedding"],
            sparse_embedding_service=mock_deps["sparse_embedding"],
            vector_store_service=mock_deps["vector_store"],
            reranker_service=mock_deps["reranker"],
            bm25_service=mock_deps["bm25_service"],
            query_rewrite_service=query_rewriter,
        )

        result = await svc.retrieve(
            "kb1",
            "怎么处理网关连接失败",
            top_k=10,
            top_n=2,
            enable_query_rewrite=True,
            query_rewrite_debug=True,
        )

        mock_deps["reranker"].rerank.assert_awaited_once()
        assert mock_deps["reranker"].rerank.await_args.args[0] == "怎么处理网关连接失败"
        assert result["total_candidates"] == 2
        assert result["debug"]["candidate_stats"]["raw_candidate_count"] == 3
        assert result["debug"]["candidate_stats"]["merged_candidate_count"] == 2
        assert result["debug"]["query_plan"]["final_queries"] == [
            "怎么处理网关连接失败",
            "网关连接失败 故障排查",
            "网关连不上 怎么排查",
        ]

    async def test_query_rewrite_is_request_driven(self, mock_deps):
        query_rewriter = AsyncMock()
        svc = RetrievalService(
            embedding_service=mock_deps["embedding"],
            sparse_embedding_service=mock_deps["sparse_embedding"],
            vector_store_service=mock_deps["vector_store"],
            reranker_service=mock_deps["reranker"],
            bm25_service=mock_deps["bm25_service"],
            query_rewrite_service=query_rewriter,
        )

        result = await svc.retrieve(
            "kb1",
            "test query",
            top_k=10,
            top_n=3,
            enable_query_rewrite=False,
            query_rewrite_debug=True,
        )

        query_rewriter.build_plan.assert_not_called()
        assert result["debug"]["query_plan"]["enabled"] is False
        assert result["debug"]["query_plan"]["final_queries"] == ["test query"]

    async def test_returns_empty_source_nodes_when_min_score_filters_all(self, mock_deps):
        mock_deps["reranker"].rerank = AsyncMock(return_value=[
            {"index": 0, "score": 0.05, "text": "result text"},
        ])
        svc = RetrievalService(
            embedding_service=mock_deps["embedding"],
            sparse_embedding_service=mock_deps["sparse_embedding"],
            vector_store_service=mock_deps["vector_store"],
            reranker_service=mock_deps["reranker"],
            bm25_service=mock_deps["bm25_service"],
        )

        result = await svc.retrieve(
            "kb1",
            "test query",
            top_k=10,
            top_n=3,
            min_score=0.1,
            enable_reranker=True,
        )

        assert result["total_candidates"] == 1
        assert result["source_nodes"] == []
