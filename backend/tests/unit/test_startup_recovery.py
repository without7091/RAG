"""Tests for startup recovery — stuck docs should be reset to PENDING."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentStatus
from app.services.document_service import DocumentService
from app.services.kb_service import KBService

# SQLAlchemy Enum stores names (uppercase), not values
RECOVERY_SQL = (
    "UPDATE documents SET status = 'PENDING', needs_vector_cleanup = 1 "
    "WHERE status IN ('PARSING', 'CHUNKING', 'EMBEDDING', 'UPSERTING')"
)


@pytest.fixture
async def kb_id(db_session: AsyncSession) -> str:
    svc = KBService(db_session)
    kb = await svc.create("Recovery Test KB")
    return kb.knowledge_base_id


async def _run_recovery_and_query(db_session, doc_id):
    """Run recovery SQL, expire cache, and re-query the document."""
    await db_session.execute(text(RECOVERY_SQL))
    await db_session.commit()
    db_session.expire_all()
    result = await db_session.execute(
        select(Document).where(Document.doc_id == doc_id)
    )
    return result.scalar_one()


class TestStartupRecovery:
    async def test_stuck_parsing_docs_reset_to_pending(self, db_session: AsyncSession, kb_id: str):
        """Docs stuck in PARSING state should be reset to PENDING on startup."""
        svc = DocumentService(db_session)
        await svc.create("doc_stuck_parse", "stuck.md", kb_id)
        await svc.update_status("doc_stuck_parse", kb_id, DocumentStatus.PARSING)

        doc = await _run_recovery_and_query(db_session, "doc_stuck_parse")
        assert doc.status == DocumentStatus.PENDING
        assert doc.needs_vector_cleanup is True

    async def test_stuck_embedding_docs_reset_to_pending(self, db_session: AsyncSession, kb_id: str):
        svc = DocumentService(db_session)
        await svc.create("doc_stuck_embed", "embed.md", kb_id)
        await svc.update_status("doc_stuck_embed", kb_id, DocumentStatus.EMBEDDING)

        doc = await _run_recovery_and_query(db_session, "doc_stuck_embed")
        assert doc.status == DocumentStatus.PENDING
        assert doc.needs_vector_cleanup is True

    async def test_completed_docs_not_affected(self, db_session: AsyncSession, kb_id: str):
        """COMPLETED docs should NOT be reset by startup recovery."""
        svc = DocumentService(db_session)
        await svc.create("doc_completed", "done.md", kb_id)
        await svc.update_status("doc_completed", kb_id, DocumentStatus.COMPLETED, chunk_count=5)

        doc = await _run_recovery_and_query(db_session, "doc_completed")
        assert doc.status == DocumentStatus.COMPLETED
        assert doc.needs_vector_cleanup is False

    async def test_pending_docs_not_affected(self, db_session: AsyncSession, kb_id: str):
        """Already-PENDING docs should not be modified."""
        svc = DocumentService(db_session)
        await svc.create("doc_pending", "pending.md", kb_id)
        await svc.update_status("doc_pending", kb_id, DocumentStatus.PENDING)

        doc = await _run_recovery_and_query(db_session, "doc_pending")
        assert doc.status == DocumentStatus.PENDING
        # should stay False since it wasn't in the WHERE clause
        assert doc.needs_vector_cleanup is False

    async def test_all_processing_states_reset(self, db_session: AsyncSession, kb_id: str):
        """All intermediate processing states should be reset."""
        svc = DocumentService(db_session)
        states = [
            ("doc_parsing", DocumentStatus.PARSING),
            ("doc_chunking", DocumentStatus.CHUNKING),
            ("doc_embedding", DocumentStatus.EMBEDDING),
            ("doc_upserting", DocumentStatus.UPSERTING),
        ]
        for doc_id, status in states:
            await svc.create(doc_id, f"{doc_id}.md", kb_id)
            await svc.update_status(doc_id, kb_id, status)

        await db_session.execute(text(RECOVERY_SQL))
        await db_session.commit()
        db_session.expire_all()

        for doc_id, _ in states:
            result = await db_session.execute(
                select(Document).where(Document.doc_id == doc_id)
            )
            doc = result.scalar_one()
            assert doc.status == DocumentStatus.PENDING, f"{doc_id} should be PENDING"
            assert doc.needs_vector_cleanup is True, f"{doc_id} should have cleanup flag"
