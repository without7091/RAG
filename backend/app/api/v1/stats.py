from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase


class KBStats(BaseModel):
    knowledge_base_id: str
    knowledge_base_name: str
    document_count: int


class StatsResponse(BaseModel):
    total_knowledge_bases: int
    total_documents: int
    total_chunks: int
    knowledge_bases: list[KBStats]


router = APIRouter(prefix="/stats", tags=["Stats"])


@router.get("", response_model=StatsResponse)
async def get_stats(
    session: AsyncSession = Depends(get_session),
):
    """Return global statistics."""
    # All KBs
    kb_result = await session.execute(
        select(KnowledgeBase).order_by(KnowledgeBase.created_at.desc())
    )
    kbs = list(kb_result.scalars().all())

    # Doc counts per KB
    kb_stats = []
    total_docs = 0
    total_chunks = 0
    for kb in kbs:
        row = await session.execute(
            select(
                func.count(Document.id),
                func.coalesce(func.sum(Document.chunk_count), 0),
            ).where(Document.knowledge_base_id == kb.knowledge_base_id)
        )
        doc_count, chunk_count = row.one()
        total_docs += doc_count
        total_chunks += chunk_count
        kb_stats.append(
            KBStats(
                knowledge_base_id=kb.knowledge_base_id,
                knowledge_base_name=kb.knowledge_base_name,
                document_count=doc_count,
            )
        )

    return StatsResponse(
        total_knowledge_bases=len(kbs),
        total_documents=total_docs,
        total_chunks=total_chunks,
        knowledge_bases=kb_stats,
    )
