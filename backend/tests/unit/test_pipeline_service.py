"""Unit tests for PipelineService with optional task_manager."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import DocumentStatus
from app.services.pipeline_service import PipelineService


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
    embedding.embed_texts = AsyncMock(return_value=[[0.1] * 1024])

    sparse_embedding = AsyncMock()
    sparse_embedding.embed_texts_async = AsyncMock(return_value=[{"indices": [1], "values": [1.0]}])

    vector_store = AsyncMock()
    vector_store.delete_by_doc_id = AsyncMock()
    vector_store.upsert_points = AsyncMock()

    return {
        "parsing": parsing,
        "chunking": chunking,
        "embedding": embedding,
        "sparse_embedding": sparse_embedding,
        "vector_store": vector_store,
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
