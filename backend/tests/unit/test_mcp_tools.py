"""Tests for MCP Tool implementations."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.mcp.tools import (
    get_knowledge_base_detail,
    get_platform_stats,
    list_knowledge_bases,
    search_knowledge_base,
)


def _make_kb(kb_id, name, description="", folder=None):
    """Create a mock KnowledgeBase object."""
    kb = MagicMock()
    kb.knowledge_base_id = kb_id
    kb.knowledge_base_name = name
    kb.description = description
    kb.folder = folder
    return kb


def _make_folder(name, parent=None):
    """Create a mock KBFolder object."""
    folder = MagicMock()
    folder.folder_name = name
    folder.parent = parent
    return folder


def _make_doc(file_name, status_name, chunk_count):
    """Create a mock Document object."""
    doc = MagicMock()
    doc.file_name = file_name
    doc.status = MagicMock()
    doc.status.name = status_name
    doc.chunk_count = chunk_count
    return doc


class TestListKnowledgeBases:
    @pytest.fixture
    def mock_session(self):
        return AsyncMock()

    async def test_returns_formatted_list(self, mock_session):
        parent_folder = _make_folder("技术文档")
        leaf_folder = _make_folder("产品线A", parent=parent_folder)
        kbs = [
            _make_kb("kb_1", "产品文档库", "包含产品手册", folder=leaf_folder),
            _make_kb("kb_2", "HR库", "", folder=None),
        ]

        with (
            patch("app.mcp.tools.KBService") as MockKBService,
        ):
            instance = MockKBService.return_value
            instance.list_all = AsyncMock(return_value=kbs)
            instance.get_document_count = AsyncMock(side_effect=[42, 15])

            result = await list_knowledge_bases(mock_session)

        assert "共 2 个知识库" in result
        assert "产品文档库" in result
        assert "kb_1" in result
        assert "文档数: 42" in result
        assert "技术文档 > 产品线A" in result

    async def test_empty_list(self, mock_session):
        with patch("app.mcp.tools.KBService") as MockKBService:
            instance = MockKBService.return_value
            instance.list_all = AsyncMock(return_value=[])

            result = await list_knowledge_bases(mock_session)

        assert "当前没有知识库" in result


class TestGetKnowledgeBaseDetail:
    @pytest.fixture
    def mock_session(self):
        return AsyncMock()

    async def test_returns_formatted_detail(self, mock_session):
        folder = _make_folder("分组A")
        kb = _make_kb("kb_1", "测试库", "描述", folder=folder)
        docs = [
            _make_doc("文件1.pdf", "COMPLETED", 100),
            _make_doc("文件2.md", "PENDING", 0),
        ]

        with (
            patch("app.mcp.tools.KBService") as MockKBService,
            patch("app.mcp.tools.DocumentService") as MockDocService,
        ):
            MockKBService.return_value.get_by_id = AsyncMock(return_value=kb)
            MockDocService.return_value.list_by_kb = AsyncMock(return_value=docs)

            result = await get_knowledge_base_detail(mock_session, "kb_1")

        assert "测试库" in result
        assert "kb_1" in result
        assert "文件1.pdf — 已完成 — 100 个片段" in result
        assert "文件2.md — 待处理 — 0 个片段" in result


class TestSearchKnowledgeBase:
    async def test_calls_retrieval_service(self):
        mock_retrieval = AsyncMock()
        mock_retrieval.retrieve = AsyncMock(
            return_value={
                "source_nodes": [
                    {
                        "text": "test content",
                        "score": 0.9,
                        "file_name": "test.pdf",
                        "header_path": "Chapter 1",
                        "metadata": {},
                    }
                ],
                "total_candidates": 10,
            }
        )

        result = await search_knowledge_base(
            retrieval_service=mock_retrieval,
            knowledge_base_id="kb_1",
            query="test query",
            top_n=3,
            enable_reranker=True,
        )

        mock_retrieval.retrieve.assert_called_once_with(
            knowledge_base_id="kb_1",
            query="test query",
            top_k=12,  # top_n * 4
            top_n=3,
            enable_reranker=True,
            enable_context_synthesis=True,
        )
        assert "共找到 1 条相关结果" in result
        assert "test.pdf" in result

    async def test_uses_config_defaults(self):
        mock_retrieval = AsyncMock()
        mock_retrieval.retrieve = AsyncMock(
            return_value={"source_nodes": []}
        )

        with patch("app.mcp.tools.get_settings") as mock_settings:
            mock_settings.return_value.mcp_default_top_n = 5
            mock_settings.return_value.mcp_default_enable_reranker = True

            result = await search_knowledge_base(
                retrieval_service=mock_retrieval,
                knowledge_base_id="kb_1",
                query="test",
            )

        mock_retrieval.retrieve.assert_called_once()
        call_kwargs = mock_retrieval.retrieve.call_args.kwargs
        assert call_kwargs["top_n"] == 5
        assert call_kwargs["top_k"] == 20  # 5 * 4
        assert call_kwargs["enable_reranker"] is True
        assert "未找到相关结果" in result


class TestGetPlatformStats:
    async def test_returns_formatted_stats(self, db_session):
        """Test with actual database session."""
        from app.models.knowledge_base import KnowledgeBase

        kb = KnowledgeBase(
            knowledge_base_id="kb_test",
            knowledge_base_name="TestKB",
            description="test",
        )
        db_session.add(kb)
        await db_session.commit()

        result = await get_platform_stats(db_session)
        assert "知识库总数: 1" in result
        assert "文档总数: 0" in result
        assert "TestKB" in result

    async def test_empty_platform(self, db_session):
        result = await get_platform_stats(db_session)
        assert "知识库总数: 0" in result
        assert "文档总数: 0" in result
