from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import DocumentNotFoundError
from app.models.document import Document, DocumentStatus


class DocumentService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self, doc_id: str, file_name: str, knowledge_base_id: str
    ) -> Document:
        # Check for existing document with same (kb_id, doc_id) — if found, reset it
        existing = await self.get_by_doc_id_and_kb(doc_id, knowledge_base_id)
        if existing is not None:
            existing.status = DocumentStatus.PENDING
            existing.file_name = file_name
            existing.chunk_count = 0
            existing.error_message = None
            await self.session.commit()
            await self.session.refresh(existing)
            return existing

        doc = Document(
            doc_id=doc_id,
            file_name=file_name,
            knowledge_base_id=knowledge_base_id,
            status=DocumentStatus.PENDING,
        )
        self.session.add(doc)
        await self.session.commit()
        await self.session.refresh(doc)
        return doc

    async def get_by_doc_id_and_kb(
        self, doc_id: str, knowledge_base_id: str
    ) -> Document | None:
        result = await self.session.execute(
            select(Document).where(
                Document.doc_id == doc_id,
                Document.knowledge_base_id == knowledge_base_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, doc_id: str) -> Document:
        result = await self.session.execute(
            select(Document).where(Document.doc_id == doc_id)
        )
        doc = result.scalar_one_or_none()
        if doc is None:
            raise DocumentNotFoundError(doc_id)
        return doc

    async def list_by_kb(self, knowledge_base_id: str) -> list[Document]:
        result = await self.session.execute(
            select(Document)
            .where(Document.knowledge_base_id == knowledge_base_id)
            .order_by(Document.upload_timestamp.desc())
        )
        return list(result.scalars().all())

    async def update_status(
        self,
        doc_id: str,
        knowledge_base_id: str,
        status: DocumentStatus,
        chunk_count: int | None = None,
        error_message: str | None = None,
    ) -> Document:
        doc = await self.get_by_doc_id_and_kb(doc_id, knowledge_base_id)
        if doc is None:
            raise DocumentNotFoundError(doc_id)
        doc.status = status
        if chunk_count is not None:
            doc.chunk_count = chunk_count
        if error_message is not None:
            doc.error_message = error_message
        await self.session.commit()
        await self.session.refresh(doc)
        return doc

    async def delete(self, doc_id: str, knowledge_base_id: str) -> None:
        doc = await self.get_by_doc_id_and_kb(doc_id, knowledge_base_id)
        if doc is None:
            raise DocumentNotFoundError(doc_id)
        await self.session.delete(doc)
        await self.session.commit()
