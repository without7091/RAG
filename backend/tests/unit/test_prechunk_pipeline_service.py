import json
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.exceptions import EmbeddingError
from app.models.document import DocumentStatus
from app.services.document_service import DocumentService
from app.services.kb_service import KBService
from app.services.prechunk_pipeline_service import PreChunkPipelineService

EMBEDDING_DIM = get_settings().embedding_dimension


class TestPreChunkPipelineService:
    async def test_run_pipeline_uses_async_file_io(
        self,
        db_session: AsyncSession,
        tmp_path,
        monkeypatch,
    ):
        import app.services.prechunk_pipeline_service as prechunk_module

        kb = await KBService(db_session).create("PreChunk IO KB")
        doc_id = "doc_prechunk_io"
        await DocumentService(db_session).create(
            doc_id=doc_id,
            file_name="chunks.json",
            knowledge_base_id=kb.knowledge_base_id,
            is_pre_chunked=True,
        )

        chunks_json_path = tmp_path / "chunks.json"
        chunks_json_path.write_text(
            json.dumps([{"text": "chunk-a"}, {"text": "chunk-b"}]),
            encoding="utf-8",
        )

        # Guardrail: sync open in async path should never be used.
        def _sync_open_forbidden(*args, **kwargs):
            raise AssertionError("sync open() should not be used in prechunk pipeline")

        monkeypatch.setattr(prechunk_module, "open", _sync_open_forbidden, raising=False)

        embedding = AsyncMock()
        embedding.embed_texts = AsyncMock(
            return_value=[[0.1] * EMBEDDING_DIM, [0.2] * EMBEDDING_DIM]
        )
        sparse_embedding = AsyncMock()
        sparse_embedding.embed_texts_async = AsyncMock(
            return_value=[
                {"indices": [1], "values": [0.1]},
                {"indices": [2], "values": [0.2]},
            ]
        )
        vector_store = AsyncMock()
        vector_store.delete_by_doc_id = AsyncMock()
        vector_store.upsert_points = AsyncMock()

        pipeline = PreChunkPipelineService(
            session=db_session,
            embedding_service=embedding,
            sparse_embedding_service=sparse_embedding,
            vector_store_service=vector_store,
            bm25_service=None,
        )

        await pipeline.run_pipeline(
            chunks_json_path=str(chunks_json_path),
            doc_id=doc_id,
            file_name="chunks.json",
            knowledge_base_id=kb.knowledge_base_id,
        )

        doc = await DocumentService(db_session).get_by_doc_id_and_kb(doc_id, kb.knowledge_base_id)
        assert doc is not None
        assert doc.status == DocumentStatus.COMPLETED
        embedding.embed_texts.assert_awaited_once_with(["chunk-a", "chunk-b"])
        sparse_embedding.embed_texts_async.assert_awaited_once_with(["chunk-a", "chunk-b"])
        vector_store.upsert_points.assert_awaited_once()

    async def test_run_pipeline_reraises_retryable_upstream_error(
        self,
        db_session: AsyncSession,
        tmp_path,
    ):
        kb = await KBService(db_session).create("PreChunk Retry KB")
        doc_id = "doc_prechunk_retry"
        await DocumentService(db_session).create(
            doc_id=doc_id,
            file_name="chunks.json",
            knowledge_base_id=kb.knowledge_base_id,
            is_pre_chunked=True,
        )

        chunks_json_path = tmp_path / "chunks.json"
        chunks_json_path.write_text(json.dumps([{"text": "chunk-a"}]), encoding="utf-8")

        embedding = AsyncMock()
        embedding.embed_texts = AsyncMock(
            side_effect=EmbeddingError(
                "Embedding API returned 503",
                status_code=503,
                retryable=True,
                upstream="embedding",
            )
        )
        sparse_embedding = AsyncMock()
        vector_store = AsyncMock()

        pipeline = PreChunkPipelineService(
            session=db_session,
            embedding_service=embedding,
            sparse_embedding_service=sparse_embedding,
            vector_store_service=vector_store,
            bm25_service=None,
        )

        with pytest.raises(EmbeddingError):
            await pipeline.run_pipeline(
                chunks_json_path=str(chunks_json_path),
                doc_id=doc_id,
                file_name="chunks.json",
                knowledge_base_id=kb.knowledge_base_id,
            )

        doc = await DocumentService(db_session).get_by_doc_id_and_kb(doc_id, kb.knowledge_base_id)
        assert doc is not None
        assert doc.status == DocumentStatus.FAILED
