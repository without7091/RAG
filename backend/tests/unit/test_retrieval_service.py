"""Unit tests for RetrievalService BM25 integration."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import get_settings
from app.services.context_synthesis_service import synthesize_context
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

    async def test_merges_overlapping_context_windows_per_document(self, mock_deps):
        mock_deps["vector_store"].hybrid_search = AsyncMock(return_value=[
            {
                "id": "pt4",
                "score": 0.91,
                "payload": {
                    "text": "chunk-4",
                    "doc_id": "doc1",
                    "file_name": "test.md",
                    "knowledge_base_id": "kb1",
                    "chunk_index": 4,
                },
            },
            {
                "id": "pt5",
                "score": 0.9,
                "payload": {
                    "text": "chunk-5",
                    "doc_id": "doc1",
                    "file_name": "test.md",
                    "knowledge_base_id": "kb1",
                    "chunk_index": 5,
                },
            },
            {
                "id": "pt6",
                "score": 0.89,
                "payload": {
                    "text": "chunk-6",
                    "doc_id": "doc1",
                    "file_name": "test.md",
                    "knowledge_base_id": "kb1",
                    "chunk_index": 6,
                },
            },
        ])
        mock_deps["vector_store"].get_chunks_by_doc_id = AsyncMock(return_value=[
            {"chunk_index": 3, "text": "chunk-3", "header_path": "", "header_level": 0, "content_type": "text"},
            {"chunk_index": 4, "text": "chunk-4", "header_path": "", "header_level": 0, "content_type": "text"},
            {"chunk_index": 5, "text": "chunk-5", "header_path": "", "header_level": 0, "content_type": "text"},
            {"chunk_index": 6, "text": "chunk-6", "header_path": "", "header_level": 0, "content_type": "text"},
            {"chunk_index": 7, "text": "chunk-7", "header_path": "", "header_level": 0, "content_type": "text"},
        ])
        mock_deps["reranker"].rerank = AsyncMock(return_value=[
            {"index": 0, "score": 0.98, "text": "chunk-4"},
            {"index": 1, "score": 0.97, "text": "chunk-5"},
            {"index": 2, "score": 0.96, "text": "chunk-6"},
        ])
        svc = RetrievalService(
            embedding_service=mock_deps["embedding"],
            sparse_embedding_service=mock_deps["sparse_embedding"],
            vector_store_service=mock_deps["vector_store"],
            reranker_service=mock_deps["reranker"],
            bm25_service=mock_deps["bm25_service"],
        )

        result = await svc.retrieve("kb1", "test query", top_k=10, top_n=3)

        expected_context = "chunk-3\n\nchunk-4\n\nchunk-5\n\nchunk-6\n\nchunk-7"
        assert [node["text"] for node in result["source_nodes"]] == ["chunk-4", "chunk-5", "chunk-6"]
        assert [node["context_text"] for node in result["source_nodes"]] == [
            expected_context,
            expected_context,
            expected_context,
        ]

    async def test_keeps_disjoint_context_windows_separate(self):
        vector_store = AsyncMock()
        vector_store.get_chunks_by_doc_id = AsyncMock(return_value=[
            {"chunk_index": 3, "text": "chunk-3"},
            {"chunk_index": 4, "text": "chunk-4"},
            {"chunk_index": 5, "text": "chunk-5"},
            {"chunk_index": 7, "text": "chunk-7"},
            {"chunk_index": 8, "text": "chunk-8"},
            {"chunk_index": 9, "text": "chunk-9"},
        ])
        nodes = [
            {"text": "chunk-4", "doc_id": "doc1", "chunk_index": 4},
            {"text": "chunk-8", "doc_id": "doc1", "chunk_index": 8},
        ]

        result = await synthesize_context(nodes, "kb1", vector_store)

        assert result[0]["context_text"] == "chunk-3\n\nchunk-4\n\nchunk-5"
        assert result[1]["context_text"] == "chunk-7\n\nchunk-8\n\nchunk-9"

    async def test_does_not_merge_context_across_documents(self):
        vector_store = AsyncMock()
        vector_store.get_chunks_by_doc_id = AsyncMock(side_effect=[
            [
                {"chunk_index": 3, "text": "doc1-3"},
                {"chunk_index": 4, "text": "doc1-4"},
                {"chunk_index": 5, "text": "doc1-5"},
            ],
            [
                {"chunk_index": 3, "text": "doc2-3"},
                {"chunk_index": 4, "text": "doc2-4"},
                {"chunk_index": 5, "text": "doc2-5"},
            ],
        ])
        nodes = [
            {"text": "doc1-4", "doc_id": "doc1", "chunk_index": 4},
            {"text": "doc2-4", "doc_id": "doc2", "chunk_index": 4},
        ]

        result = await synthesize_context(nodes, "kb1", vector_store)

        assert result[0]["context_text"] == "doc1-3\n\ndoc1-4\n\ndoc1-5"
        assert result[1]["context_text"] == "doc2-3\n\ndoc2-4\n\ndoc2-5"

    async def test_falls_back_to_text_when_chunk_lookup_fails(self):
        vector_store = AsyncMock()
        vector_store.get_chunks_by_doc_id = AsyncMock(side_effect=RuntimeError("boom"))
        nodes = [{"text": "chunk-4", "doc_id": "doc1", "chunk_index": 4}]

        result = await synthesize_context(nodes, "kb1", vector_store)

        assert result[0]["context_text"] == "chunk-4"

    async def test_clamps_context_to_available_edge_chunks(self):
        vector_store = AsyncMock()
        vector_store.get_chunks_by_doc_id = AsyncMock(return_value=[
            {"chunk_index": 0, "text": "chunk-0"},
            {"chunk_index": 1, "text": "chunk-1"},
        ])
        nodes = [{"text": "chunk-0", "doc_id": "doc1", "chunk_index": 0}]

        result = await synthesize_context(nodes, "kb1", vector_store)

        assert result[0]["context_text"] == "chunk-0\n\nchunk-1"

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
