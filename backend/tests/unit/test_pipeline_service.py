"""Unit tests for PipelineService with optional task_manager."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.document import DocumentStatus
from app.services.pipeline_service import PipelineService

EMBEDDING_DIM = get_settings().embedding_dimension


class FakeNode:
    def __init__(self, text, metadata=None):
        self.text = text
        self.metadata = metadata or {}


@pytest.fixture
def mock_services():
    parsing = AsyncMock()
    parsing.parse_file = AsyncMock(return_value="# Title\n\nSome content")

    chunking = MagicMock()
    chunking.chunk_markdown = MagicMock(return_value=[
        FakeNode("chunk1", {"chunk_index": 0, "header_path": "", "header_level": 0, "content_type": "text"}),
    ])

    embedding = AsyncMock()
    embedding.embed_texts = AsyncMock(return_value=[[0.1] * EMBEDDING_DIM])

    sparse_embedding = AsyncMock()
    sparse_embedding.embed_texts_async = AsyncMock(return_value=[{"indices": [1], "values": [1.0]}])

    vector_store = AsyncMock()
    vector_store.delete_by_doc_id = AsyncMock()
    vector_store.upsert_points = AsyncMock()

    bm25_service = MagicMock()
    bm25_service.batch_to_sparse_vectors = MagicMock(
        return_value=[{"indices": [10, 20], "values": [2.0, 1.0]}]
    )

    return {
        "parsing": parsing,
        "chunking": chunking,
        "embedding": embedding,
        "sparse_embedding": sparse_embedding,
        "vector_store": vector_store,
        "bm25_service": bm25_service,
    }


class TestPipelineServiceWithoutTaskManager:
    """Verify PipelineService works when task_manager is None."""

    async def test_run_pipeline_without_task_manager(self, db_session: AsyncSession, mock_services):
        """Pipeline should complete successfully without a task_manager."""
        from app.services.kb_service import KBService
        from app.services.document_service import DocumentService

        kb_svc = KBService(db_session)
        kb = await kb_svc.create("Pipeline Test KB")
        doc_svc = DocumentService(db_session)
        await doc_svc.create("doc_test", "test.md", kb.knowledge_base_id)

        pipeline = PipelineService(
            session=db_session,
            parsing_service=mock_services["parsing"],
            chunking_service=mock_services["chunking"],
            embedding_service=mock_services["embedding"],
            sparse_embedding_service=mock_services["sparse_embedding"],
            vector_store_service=mock_services["vector_store"],
            bm25_service=mock_services["bm25_service"],
            task_manager=None,
        )

        await pipeline.run_pipeline(
            task_id="unused",
            file_path="/tmp/test.md",
            doc_id="doc_test",
            file_name="test.md",
            knowledge_base_id=kb.knowledge_base_id,
        )

        doc = await doc_svc.get_by_doc_id_and_kb("doc_test", kb.knowledge_base_id)
        assert doc.status == DocumentStatus.COMPLETED
        assert doc.chunk_count == 1

    async def test_run_pipeline_failure_without_task_manager(self, db_session: AsyncSession, mock_services):
        """Pipeline failure should update doc status even without task_manager."""
        from app.services.kb_service import KBService
        from app.services.document_service import DocumentService

        kb_svc = KBService(db_session)
        kb = await kb_svc.create("Pipeline Fail KB")
        doc_svc = DocumentService(db_session)
        await doc_svc.create("doc_fail", "fail.md", kb.knowledge_base_id)

        mock_services["parsing"].parse_file = AsyncMock(side_effect=RuntimeError("Parse error"))

        pipeline = PipelineService(
            session=db_session,
            parsing_service=mock_services["parsing"],
            chunking_service=mock_services["chunking"],
            embedding_service=mock_services["embedding"],
            sparse_embedding_service=mock_services["sparse_embedding"],
            vector_store_service=mock_services["vector_store"],
            bm25_service=mock_services["bm25_service"],
            task_manager=None,
        )

        await pipeline.run_pipeline(
            task_id="unused",
            file_path="/tmp/fail.md",
            doc_id="doc_fail",
            file_name="fail.md",
            knowledge_base_id=kb.knowledge_base_id,
        )

        doc = await doc_svc.get_by_doc_id_and_kb("doc_fail", kb.knowledge_base_id)
        assert doc.status == DocumentStatus.FAILED
        assert "Parse error" in doc.error_message


class TestPipelineServiceBM25:
    """Tests for BM25 integration in PipelineService."""

    async def test_pipeline_calls_bm25_service(self, db_session: AsyncSession, mock_services):
        """Pipeline should call bm25_service.batch_to_sparse_vectors with chunk texts."""
        from app.services.kb_service import KBService
        from app.services.document_service import DocumentService

        kb_svc = KBService(db_session)
        kb = await kb_svc.create("BM25 Pipeline KB")
        doc_svc = DocumentService(db_session)
        await doc_svc.create("doc_bm25", "bm25.md", kb.knowledge_base_id)

        pipeline = PipelineService(
            session=db_session,
            parsing_service=mock_services["parsing"],
            chunking_service=mock_services["chunking"],
            embedding_service=mock_services["embedding"],
            sparse_embedding_service=mock_services["sparse_embedding"],
            vector_store_service=mock_services["vector_store"],
            bm25_service=mock_services["bm25_service"],
            task_manager=None,
        )

        await pipeline.run_pipeline(
            task_id="unused",
            file_path="/tmp/bm25.md",
            doc_id="doc_bm25",
            file_name="bm25.md",
            knowledge_base_id=kb.knowledge_base_id,
        )

        mock_services["bm25_service"].batch_to_sparse_vectors.assert_called_once_with(["chunk1"])

    async def test_pipeline_passes_bm25_to_upsert(self, db_session: AsyncSession, mock_services):
        """Pipeline should pass bm25_vectors to upsert_points."""
        from app.services.kb_service import KBService
        from app.services.document_service import DocumentService

        kb_svc = KBService(db_session)
        kb = await kb_svc.create("BM25 Upsert KB")
        doc_svc = DocumentService(db_session)
        await doc_svc.create("doc_bm25u", "bm25u.md", kb.knowledge_base_id)

        pipeline = PipelineService(
            session=db_session,
            parsing_service=mock_services["parsing"],
            chunking_service=mock_services["chunking"],
            embedding_service=mock_services["embedding"],
            sparse_embedding_service=mock_services["sparse_embedding"],
            vector_store_service=mock_services["vector_store"],
            bm25_service=mock_services["bm25_service"],
            task_manager=None,
        )

        await pipeline.run_pipeline(
            task_id="unused",
            file_path="/tmp/bm25u.md",
            doc_id="doc_bm25u",
            file_name="bm25u.md",
            knowledge_base_id=kb.knowledge_base_id,
        )

        # Check that upsert_points was called with bm25_vectors keyword argument
        call_kwargs = mock_services["vector_store"].upsert_points.call_args
        assert "bm25_vectors" in call_kwargs.kwargs
        assert call_kwargs.kwargs["bm25_vectors"] == [{"indices": [10, 20], "values": [2.0, 1.0]}]

    async def test_pipeline_works_without_bm25(self, db_session: AsyncSession, mock_services):
        """Pipeline should work fine when bm25_service is None."""
        from app.services.kb_service import KBService
        from app.services.document_service import DocumentService

        kb_svc = KBService(db_session)
        kb = await kb_svc.create("No BM25 KB")
        doc_svc = DocumentService(db_session)
        await doc_svc.create("doc_nobm25", "nobm25.md", kb.knowledge_base_id)

        pipeline = PipelineService(
            session=db_session,
            parsing_service=mock_services["parsing"],
            chunking_service=mock_services["chunking"],
            embedding_service=mock_services["embedding"],
            sparse_embedding_service=mock_services["sparse_embedding"],
            vector_store_service=mock_services["vector_store"],
            bm25_service=None,
            task_manager=None,
        )

        await pipeline.run_pipeline(
            task_id="unused",
            file_path="/tmp/nobm25.md",
            doc_id="doc_nobm25",
            file_name="nobm25.md",
            knowledge_base_id=kb.knowledge_base_id,
        )

        doc = await doc_svc.get_by_doc_id_and_kb("doc_nobm25", kb.knowledge_base_id)
        assert doc.status == DocumentStatus.COMPLETED
