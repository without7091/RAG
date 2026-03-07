"""Unit tests for RetrievalService BM25 integration."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.config import get_settings
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
