"""MCP Tool implementations — each tool calls the Service layer directly."""

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.mcp.formatting import (
    format_kb_detail,
    format_kb_list,
    format_platform_stats,
    format_search_results,
    get_folder_path,
)
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.services.document_service import DocumentService
from app.services.kb_service import KBService
from app.services.retrieval_service import RetrievalService

logger = logging.getLogger(__name__)


async def list_knowledge_bases(session: AsyncSession) -> str:
    """List all available knowledge bases with descriptions and document counts."""
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


async def get_knowledge_base_detail(
    session: AsyncSession,
    knowledge_base_id: str,
) -> str:
    """Get detailed information about a specific knowledge base including its documents."""
    kb_service = KBService(session)
    kb = await kb_service.get_by_id(knowledge_base_id)

    kb_info = {
        "knowledge_base_id": kb.knowledge_base_id,
        "knowledge_base_name": kb.knowledge_base_name,
        "description": kb.description,
        "folder_path": get_folder_path(kb),
    }

    doc_service = DocumentService(session)
    docs = await doc_service.list_by_kb(knowledge_base_id)

    doc_dicts = [
        {
            "file_name": doc.file_name,
            "status": doc.status.name,
            "chunk_count": doc.chunk_count,
        }
        for doc in docs
    ]

    return format_kb_detail(kb_info, doc_dicts)


async def search_knowledge_base(
    retrieval_service: RetrievalService,
    knowledge_base_id: str,
    query: str,
    top_n: int | None = None,
    enable_reranker: bool | None = None,
) -> str:
    """Search a knowledge base using hybrid retrieval + optional reranking."""
    settings = get_settings()
    effective_top_n = top_n if top_n is not None else settings.mcp_default_top_n
    effective_reranker = (
        enable_reranker if enable_reranker is not None else settings.mcp_default_enable_reranker
    )
    top_k = effective_top_n * 4

    result = await retrieval_service.retrieve(
        knowledge_base_id=knowledge_base_id,
        query=query,
        top_k=top_k,
        top_n=effective_top_n,
        enable_reranker=effective_reranker,
        enable_context_synthesis=True,
    )

    return format_search_results(result)


async def get_platform_stats(session: AsyncSession) -> str:
    """Get overall platform statistics."""
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
