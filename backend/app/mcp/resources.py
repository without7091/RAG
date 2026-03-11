"""MCP Resource implementations — read-only context data for LLM injection."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.formatting import format_kb_detail, format_kb_list, format_platform_stats, get_folder_path
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.services.document_service import DocumentService
from app.services.kb_service import KBService


async def read_knowledge_bases(session: AsyncSession) -> str:
    """Read all knowledge bases — for rag://knowledge-bases resource."""
    kb_service = KBService(session)
    kbs = await kb_service.list_all()

    kb_dicts = []
    for kb in kbs:
        doc_count = await kb_service.get_document_count(kb.knowledge_base_id)
        kb_dicts.append({
            "knowledge_base_id": kb.knowledge_base_id,
            "knowledge_base_name": kb.knowledge_base_name,
            "description": kb.description,
            "document_count": doc_count,
            "folder_path": get_folder_path(kb),
        })

    return format_kb_list(kb_dicts)


async def read_knowledge_base_info(session: AsyncSession, kb_id: str) -> str:
    """Read a specific knowledge base's info — for rag://knowledge-bases/{kb_id}/info."""
    kb_service = KBService(session)
    kb = await kb_service.get_by_id(kb_id)

    kb_info = {
        "knowledge_base_id": kb.knowledge_base_id,
        "knowledge_base_name": kb.knowledge_base_name,
        "description": kb.description,
        "folder_path": get_folder_path(kb),
    }

    doc_service = DocumentService(session)
    docs = await doc_service.list_by_kb(kb_id)

    doc_dicts = [
        {
            "file_name": doc.file_name,
            "status": doc.status.name,
            "chunk_count": doc.chunk_count,
        }
        for doc in docs
    ]

    return format_kb_detail(kb_info, doc_dicts)


async def read_stats(session: AsyncSession) -> str:
    """Read platform statistics — for rag://stats resource."""
    kb_result = await session.execute(
        select(KnowledgeBase).order_by(KnowledgeBase.created_at.desc())
    )
    kbs = list(kb_result.scalars().all())

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
        kb_stats.append({
            "knowledge_base_id": kb.knowledge_base_id,
            "knowledge_base_name": kb.knowledge_base_name,
            "document_count": doc_count,
            "chunk_count": chunk_count,
        })

    stats = {
        "total_knowledge_bases": len(kbs),
        "total_documents": total_docs,
        "total_chunks": total_chunks,
        "knowledge_bases": kb_stats,
    }

    return format_platform_stats(stats)
