"""Tests for MCP Prompt templates."""

from app.mcp.prompts import cross_kb_search_prompt, search_and_answer_prompt


class TestSearchAndAnswerPrompt:
    def test_with_kb_name(self):
        result = search_and_answer_prompt("退款政策是什么", "产品文档库")
        assert "退款政策是什么" in result
        assert "产品文档库" in result
        assert "请在「产品文档库」知识库中搜索" in result

    def test_without_kb_name(self):
        result = search_and_answer_prompt("如何部署")
        assert "如何部署" in result
        assert "list_knowledge_bases" in result

    def test_contains_instructions(self):
        result = search_and_answer_prompt("query")
        assert "先调用检索工具获取相关文档片段" in result
        assert "基于检索结果回答" in result
        assert "检索结果不足以回答" in result


class TestCrossKBSearchPrompt:
    def test_contains_query(self):
        result = cross_kb_search_prompt("跨部门协作流程")
        assert "跨部门协作流程" in result

    def test_contains_steps(self):
        result = cross_kb_search_prompt("query")
        assert "list_knowledge_bases" in result
        assert "判断可能涉及哪些知识库" in result
        assert "综合所有检索结果" in result
