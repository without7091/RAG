"""Format service layer return values into agent-friendly text."""


def format_kb_list(knowledge_bases: list[dict]) -> str:
    """Format a list of knowledge bases for agent consumption.

    Each dict should contain: knowledge_base_id, knowledge_base_name,
    description, document_count, folder_path.
    """
    if not knowledge_bases:
        return "当前没有知识库。"

    lines = [f"共 {len(knowledge_bases)} 个知识库：\n"]
    for i, kb in enumerate(knowledge_bases, 1):
        lines.append(f"{i}. {kb['knowledge_base_name']}")
        lines.append(f"   ID: {kb['knowledge_base_id']}")
        if kb.get("description"):
            lines.append(f"   描述: {kb['description']}")
        lines.append(f"   文档数: {kb['document_count']}")
        if kb.get("folder_path"):
            lines.append(f"   所属分组: {kb['folder_path']}")
        lines.append("")
    return "\n".join(lines).rstrip()


def format_kb_detail(kb_info: dict, documents: list[dict]) -> str:
    """Format knowledge base detail with document list.

    kb_info: knowledge_base_id, knowledge_base_name, description, folder_path
    documents: list of dicts with file_name, status, chunk_count
    """
    lines = [
        f"知识库: {kb_info['knowledge_base_name']}",
        f"ID: {kb_info['knowledge_base_id']}",
    ]
    if kb_info.get("description"):
        lines.append(f"描述: {kb_info['description']}")
    if kb_info.get("folder_path"):
        lines.append(f"所属分组: {kb_info['folder_path']}")
    lines.append(f"文档总数: {len(documents)}")
    lines.append("")

    if documents:
        lines.append("文档列表:")
        for i, doc in enumerate(documents, 1):
            status_map = {
                "COMPLETED": "已完成",
                "PENDING": "待处理",
                "PARSING": "解析中",
                "CHUNKING": "切片中",
                "EMBEDDING": "向量化中",
                "UPSERTING": "入库中",
                "UPLOADED": "已上传",
                "FAILED": "失败",
            }
            status_text = status_map.get(doc["status"], doc["status"])
            chunk_text = f"{doc['chunk_count']} 个片段" if doc["chunk_count"] else "0 个片段"
            lines.append(f"  {i}. {doc['file_name']} — {status_text} — {chunk_text}")
    else:
        lines.append("暂无文档。")

    return "\n".join(lines)


def format_search_results(result: dict) -> str:
    """Format retrieval results for agent consumption.

    result: dict returned by RetrievalService.retrieve()
    """
    source_nodes = result.get("source_nodes", [])
    if not source_nodes:
        return "未找到相关结果。"

    lines = [f"共找到 {len(source_nodes)} 条相关结果：\n"]
    for i, node in enumerate(source_nodes, 1):
        # Build source path
        source_parts = []
        if node.get("file_name"):
            source_parts.append(node["file_name"])
        if node.get("header_path"):
            source_parts.append(node["header_path"])
        source_str = " > ".join(source_parts) if source_parts else "未知来源"

        lines.append(f"[结果 {i}] 来源: {source_str}")
        lines.append(f"相关度: {node.get('score', 0):.3f}")
        lines.append(f"内容: {node.get('text', '')}")

        # Context from synthesis
        context = node.get("metadata", {}).get("context_before", "")
        context_after = node.get("metadata", {}).get("context_after", "")
        if context or context_after:
            ctx_parts = []
            if context:
                ctx_parts.append(context)
            if context_after:
                ctx_parts.append(context_after)
            lines.append(f"上下文: {' ... '.join(ctx_parts)}")

        lines.append("")
        lines.append("---\n")

    return "\n".join(lines).rstrip()


def format_platform_stats(stats: dict) -> str:
    """Format platform statistics for agent consumption.

    stats: dict with total_knowledge_bases, total_documents, total_chunks,
           knowledge_bases (list of per-KB stats)
    """
    lines = [
        "RAG 平台统计:",
        f"  - 知识库总数: {stats['total_knowledge_bases']}",
        f"  - 文档总数: {stats['total_documents']}",
        f"  - 切片总数: {stats['total_chunks']:,}",
        "",
    ]

    kb_stats = stats.get("knowledge_bases", [])
    if kb_stats:
        lines.append("各知识库概况:")
        for kb in kb_stats:
            lines.append(
                f"  - {kb['knowledge_base_name']}: "
                f"{kb['document_count']} 文档, {kb.get('chunk_count', 0):,} 切片"
            )

    return "\n".join(lines)


def get_folder_path(kb) -> str:
    """Build folder path string from a KnowledgeBase ORM object with eager-loaded folder."""
    if kb.folder is None:
        return ""
    parts = []
    if kb.folder.parent is not None:
        parts.append(kb.folder.parent.folder_name)
    parts.append(kb.folder.folder_name)
    return " > ".join(parts)
