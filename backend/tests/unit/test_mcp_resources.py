"""Tests for MCP Resource implementations."""

from app.mcp.resources import read_knowledge_bases, read_knowledge_base_info, read_stats
from app.models.document import Document, DocumentStatus
from app.models.kb_folder import KBFolder
from app.models.knowledge_base import KnowledgeBase
from app.utils.id_gen import generate_kb_id


async def _create_kb(session, name, description="", folder_id=None):
    kb = KnowledgeBase(
        knowledge_base_id=generate_kb_id(),
        knowledge_base_name=name,
        description=description,
        folder_id=folder_id,
    )
    session.add(kb)
    await session.commit()
    return kb


async def _create_folder(session, name, parent_id=None, depth=1):
    from app.utils.id_gen import generate_kb_id

    folder = KBFolder(
        folder_id=generate_kb_id(),
        folder_name=name,
        parent_folder_id=parent_id,
        depth=depth,
    )
    session.add(folder)
    await session.commit()
    return folder


async def _create_document(session, kb_id, file_name, status=DocumentStatus.COMPLETED, chunks=10):
    doc = Document(
        doc_id=f"doc_{file_name}",
        file_name=file_name,
        knowledge_base_id=kb_id,
        status=status,
        chunk_count=chunks,
    )
    session.add(doc)
    await session.commit()
    return doc


class TestReadKnowledgeBases:
    async def test_empty(self, db_session):
        result = await read_knowledge_bases(db_session)
        assert "当前没有知识库" in result

    async def test_with_kbs(self, db_session):
        kb1 = await _create_kb(db_session, "KB One", "First KB")
        kb2 = await _create_kb(db_session, "KB Two", "Second KB")
        await _create_document(db_session, kb1.knowledge_base_id, "file1.pdf")

        result = await read_knowledge_bases(db_session)
        assert "共 2 个知识库" in result
        assert "KB One" in result
        assert "KB Two" in result
        assert "文档数: 1" in result


class TestReadKnowledgeBaseInfo:
    async def test_with_documents(self, db_session):
        kb = await _create_kb(db_session, "Detail KB", "Detailed description")
        await _create_document(db_session, kb.knowledge_base_id, "doc1.pdf", chunks=50)
        await _create_document(
            db_session, kb.knowledge_base_id, "doc2.md",
            status=DocumentStatus.PENDING, chunks=0,
        )

        result = await read_knowledge_base_info(db_session, kb.knowledge_base_id)
        assert "Detail KB" in result
        assert "Detailed description" in result
        assert "文档总数: 2" in result
        assert "doc1.pdf — 已完成 — 50 个片段" in result
        assert "doc2.md — 待处理 — 0 个片段" in result

    async def test_empty_kb(self, db_session):
        kb = await _create_kb(db_session, "Empty KB")
        result = await read_knowledge_base_info(db_session, kb.knowledge_base_id)
        assert "Empty KB" in result
        assert "暂无文档" in result


class TestReadStats:
    async def test_empty_platform(self, db_session):
        result = await read_stats(db_session)
        assert "知识库总数: 0" in result
        assert "文档总数: 0" in result

    async def test_with_data(self, db_session):
        kb = await _create_kb(db_session, "Stats KB")
        await _create_document(db_session, kb.knowledge_base_id, "a.pdf", chunks=100)
        await _create_document(db_session, kb.knowledge_base_id, "b.pdf", chunks=50)

        result = await read_stats(db_session)
        assert "知识库总数: 1" in result
        assert "文档总数: 2" in result
        assert "Stats KB: 2 文档" in result
