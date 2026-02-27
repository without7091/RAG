from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import KnowledgeBaseAlreadyExistsError, KnowledgeBaseNotFoundError
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.utils.id_gen import generate_kb_id


class KBService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, name: str, description: str = "") -> KnowledgeBase:
        # Check for duplicate name
        existing = await self.session.execute(
            select(KnowledgeBase).where(KnowledgeBase.knowledge_base_name == name)
        )
        if existing.scalar_one_or_none() is not None:
            raise KnowledgeBaseAlreadyExistsError(name)

        kb_id = generate_kb_id(name)
        kb = KnowledgeBase(
            knowledge_base_id=kb_id,
            knowledge_base_name=name,
            description=description,
        )
        self.session.add(kb)
        await self.session.commit()
        await self.session.refresh(kb)
        return kb

    async def get_by_id(self, kb_id: str) -> KnowledgeBase:
        result = await self.session.execute(
            select(KnowledgeBase).where(KnowledgeBase.knowledge_base_id == kb_id)
        )
        kb = result.scalar_one_or_none()
        if kb is None:
            raise KnowledgeBaseNotFoundError(kb_id)
        return kb

    async def list_all(self) -> list[KnowledgeBase]:
        result = await self.session.execute(
            select(KnowledgeBase).order_by(KnowledgeBase.created_at.desc())
        )
        return list(result.scalars().all())

    async def delete(self, kb_id: str) -> None:
        kb = await self.get_by_id(kb_id)
        await self.session.delete(kb)
        await self.session.commit()

    async def get_document_count(self, kb_id: str) -> int:
        result = await self.session.execute(
            select(func.count(Document.id)).where(Document.knowledge_base_id == kb_id)
        )
        return result.scalar() or 0
