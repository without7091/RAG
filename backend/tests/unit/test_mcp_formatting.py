"""Tests for MCP formatting utilities."""

from app.mcp.formatting import (
    format_kb_detail,
    format_kb_list,
    format_platform_stats,
    format_search_results,
)


class TestFormatKBList:
    def test_empty_list(self):
        result = format_kb_list([])
        assert result == "当前没有知识库。"

    def test_single_kb(self):
        kbs = [
            {
                "knowledge_base_id": "kb_123",
                "knowledge_base_name": "产品文档库",
                "description": "包含产品手册",
                "document_count": 10,
                "folder_path": "技术文档 > 产品线A",
            }
        ]
        result = format_kb_list(kbs)
        assert "共 1 个知识库" in result
        assert "产品文档库" in result
        assert "kb_123" in result
        assert "包含产品手册" in result
        assert "文档数: 10" in result
        assert "技术文档 > 产品线A" in result

    def test_multiple_kbs(self):
        kbs = [
            {
                "knowledge_base_id": "kb_1",
                "knowledge_base_name": "KB One",
                "description": "",
                "document_count": 5,
                "folder_path": "",
            },
            {
                "knowledge_base_id": "kb_2",
                "knowledge_base_name": "KB Two",
                "description": "Second KB",
                "document_count": 3,
                "folder_path": "Group > Sub",
            },
        ]
        result = format_kb_list(kbs)
        assert "共 2 个知识库" in result
        assert "1. KB One" in result
        assert "2. KB Two" in result

    def test_no_description_omits_line(self):
        kbs = [
            {
                "knowledge_base_id": "kb_1",
                "knowledge_base_name": "Test",
                "description": "",
                "document_count": 0,
                "folder_path": "",
            }
        ]
        result = format_kb_list(kbs)
        assert "描述" not in result

    def test_no_folder_path_omits_line(self):
        kbs = [
            {
                "knowledge_base_id": "kb_1",
                "knowledge_base_name": "Test",
                "description": "Desc",
                "document_count": 0,
                "folder_path": "",
            }
        ]
        result = format_kb_list(kbs)
        assert "所属分组" not in result


class TestFormatKBDetail:
    def test_with_documents(self):
        kb_info = {
            "knowledge_base_id": "kb_abc",
            "knowledge_base_name": "文档库",
            "description": "测试描述",
            "folder_path": "分组A > 子组",
        }
        documents = [
            {"file_name": "手册.pdf", "status": "COMPLETED", "chunk_count": 128},
            {"file_name": "指南.md", "status": "PENDING", "chunk_count": 0},
            {"file_name": "失败.docx", "status": "FAILED", "chunk_count": 0},
        ]
        result = format_kb_detail(kb_info, documents)
        assert "文档库" in result
        assert "kb_abc" in result
        assert "测试描述" in result
        assert "分组A > 子组" in result
        assert "文档总数: 3" in result
        assert "手册.pdf — 已完成 — 128 个片段" in result
        assert "指南.md — 待处理 — 0 个片段" in result
        assert "失败.docx — 失败 — 0 个片段" in result

    def test_empty_documents(self):
        kb_info = {
            "knowledge_base_id": "kb_1",
            "knowledge_base_name": "Empty KB",
            "description": "",
            "folder_path": "",
        }
        result = format_kb_detail(kb_info, [])
        assert "文档总数: 0" in result
        assert "暂无文档" in result


class TestFormatSearchResults:
    def test_empty_results(self):
        result = format_search_results({"source_nodes": []})
        assert result == "未找到相关结果。"

    def test_with_results(self):
        data = {
            "source_nodes": [
                {
                    "text": "退款政策内容...",
                    "score": 0.923,
                    "file_name": "产品手册.pdf",
                    "header_path": "第三章 > 退款政策",
                    "metadata": {},
                },
                {
                    "text": "售后说明...",
                    "score": 0.871,
                    "file_name": "FAQ.md",
                    "header_path": "",
                    "metadata": {},
                },
            ]
        }
        result = format_search_results(data)
        assert "共找到 2 条相关结果" in result
        assert "[结果 1]" in result
        assert "产品手册.pdf > 第三章 > 退款政策" in result
        assert "0.923" in result
        assert "退款政策内容..." in result
        assert "[结果 2]" in result
        assert "FAQ.md" in result

    def test_result_without_header_path(self):
        data = {
            "source_nodes": [
                {
                    "text": "some content",
                    "score": 0.5,
                    "file_name": "doc.pdf",
                    "header_path": None,
                    "metadata": {},
                }
            ]
        }
        result = format_search_results(data)
        assert "来源: doc.pdf" in result

    def test_result_without_file_name(self):
        data = {
            "source_nodes": [
                {
                    "text": "content",
                    "score": 0.5,
                    "file_name": "",
                    "header_path": "",
                    "metadata": {},
                }
            ]
        }
        result = format_search_results(data)
        assert "未知来源" in result


class TestFormatPlatformStats:
    def test_basic_stats(self):
        stats = {
            "total_knowledge_bases": 3,
            "total_documents": 50,
            "total_chunks": 12345,
            "knowledge_bases": [
                {
                    "knowledge_base_name": "KB1",
                    "document_count": 30,
                    "chunk_count": 8000,
                },
                {
                    "knowledge_base_name": "KB2",
                    "document_count": 20,
                    "chunk_count": 4345,
                },
            ],
        }
        result = format_platform_stats(stats)
        assert "知识库总数: 3" in result
        assert "文档总数: 50" in result
        assert "12,345" in result
        assert "KB1: 30 文档, 8,000 切片" in result
        assert "KB2: 20 文档, 4,345 切片" in result

    def test_empty_stats(self):
        stats = {
            "total_knowledge_bases": 0,
            "total_documents": 0,
            "total_chunks": 0,
            "knowledge_bases": [],
        }
        result = format_platform_stats(stats)
        assert "知识库总数: 0" in result
