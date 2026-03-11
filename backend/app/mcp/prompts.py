"""MCP Prompt templates — guided workflows for common agent tasks."""


def search_and_answer_prompt(query: str, knowledge_base_name: str | None = None) -> str:
    """Build the search_and_answer prompt template."""
    kb_instruction = (
        f"请在「{knowledge_base_name}」知识库中搜索。"
        if knowledge_base_name
        else "请先使用 list_knowledge_bases 工具确定最合适的知识库。"
    )

    return (
        f"请帮我在 RAG 知识库中搜索以下问题的相关信息，然后基于检索结果给出准确回答：\n\n"
        f"问题：{query}\n\n"
        f"{kb_instruction}\n\n"
        f"要求：\n"
        f"1. 先调用检索工具获取相关文档片段\n"
        f"2. 基于检索结果回答，引用来源文件名和章节\n"
        f"3. 如果检索结果不足以回答，明确说明并建议调整查询"
    )


def cross_kb_search_prompt(query: str) -> str:
    """Build the cross_kb_search prompt template."""
    return (
        f"请帮我跨多个知识库搜索以下问题：\n\n"
        f"问题：{query}\n\n"
        f"步骤：\n"
        f"1. 先调用 list_knowledge_bases 查看所有可用知识库\n"
        f"2. 根据问题内容，判断可能涉及哪些知识库\n"
        f"3. 依次在相关知识库中检索\n"
        f"4. 综合所有检索结果给出完整回答，标注每条信息的来源知识库和文档"
    )
