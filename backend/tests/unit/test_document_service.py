import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import DocumentNotFoundError
from app.models.document import DocumentStatus
from app.services.document_service import DocumentService
from app.services.kb_service import KBService


@pytest.fixture
async def kb_id(db_session: AsyncSession) -> str:
    svc = KBService(db_session)
    kb = await svc.create("Test KB for Docs")
    return kb.knowledge_base_id


class TestDocumentService:
    async def test_create_document(self, db_session: AsyncSession, kb_id: str):
        svc = DocumentService(db_session)
        doc = await svc.create("doc_abc", "test.pdf", kb_id)
        assert doc.doc_id == "doc_abc"
        assert doc.file_name == "test.pdf"
        assert doc.status == DocumentStatus.PENDING

    async def test_create_duplicate_resets(self, db_session: AsyncSession, kb_id: str):
        svc = DocumentService(db_session)
        await svc.create("doc_dup", "v1.pdf", kb_id)

        # Update to completed
        await svc.update_status("doc_dup", kb_id, DocumentStatus.COMPLETED, chunk_count=5)

        # Re-create with same doc_id resets
        doc2 = await svc.create("doc_dup", "v2.pdf", kb_id)
        assert doc2.status == DocumentStatus.PENDING
        assert doc2.file_name == "v2.pdf"
        assert doc2.chunk_count == 0

    async def test_get_by_doc_id_and_kb(self, db_session: AsyncSession, kb_id: str):
        svc = DocumentService(db_session)
        await svc.create("doc_find", "file.md", kb_id)
        found = await svc.get_by_doc_id_and_kb("doc_find", kb_id)
        assert found is not None
        assert found.doc_id == "doc_find"

    async def test_get_by_doc_id_and_kb_not_found(self, db_session: AsyncSession, kb_id: str):
        svc = DocumentService(db_session)
        found = await svc.get_by_doc_id_and_kb("nonexistent", kb_id)
        assert found is None

    async def test_list_by_kb(self, db_session: AsyncSession, kb_id: str):
        svc = DocumentService(db_session)
        await svc.create("doc_a", "a.pdf", kb_id)
        await svc.create("doc_b", "b.pdf", kb_id)
        docs = await svc.list_by_kb(kb_id)
        assert len(docs) == 2

    async def test_update_status(self, db_session: AsyncSession, kb_id: str):
        svc = DocumentService(db_session)
        await svc.create("doc_status", "s.pdf", kb_id)
        doc = await svc.update_status("doc_status", kb_id, DocumentStatus.PARSING)
        assert doc.status == DocumentStatus.PARSING

    async def test_update_status_with_chunk_count(self, db_session: AsyncSession, kb_id: str):
        svc = DocumentService(db_session)
        await svc.create("doc_chunks", "c.pdf", kb_id)
        doc = await svc.update_status(
            "doc_chunks", kb_id, DocumentStatus.COMPLETED, chunk_count=10
        )
        assert doc.chunk_count == 10

    async def test_update_status_not_found(self, db_session: AsyncSession, kb_id: str):
        svc = DocumentService(db_session)
        with pytest.raises(DocumentNotFoundError):
            await svc.update_status("missing", kb_id, DocumentStatus.FAILED)

    async def test_delete_document(self, db_session: AsyncSession, kb_id: str):
        svc = DocumentService(db_session)
        await svc.create("doc_del", "d.pdf", kb_id)
        await svc.delete("doc_del", kb_id)
        found = await svc.get_by_doc_id_and_kb("doc_del", kb_id)
        assert found is None

    async def test_status_flow(self, db_session: AsyncSession, kb_id: str):
        """Test full status transition: PENDING -> PARSING -> CHUNKING -> ... -> COMPLETED."""
        svc = DocumentService(db_session)
        await svc.create("doc_flow", "flow.pdf", kb_id)

        for status in [
            DocumentStatus.PARSING,
            DocumentStatus.CHUNKING,
            DocumentStatus.EMBEDDING,
            DocumentStatus.UPSERTING,
            DocumentStatus.COMPLETED,
        ]:
            doc = await svc.update_status("doc_flow", kb_id, status)
            assert doc.status == status
