"""FastMCP server — registers Tools, Resources, and Prompts."""

import logging

from mcp.server.fastmcp import FastMCP

from app.config import get_settings
from app.db.session import get_session_factory
from app.dependencies import get_retrieval_service
from app.mcp import prompts as prompt_module
from app.mcp import resources as resource_module
from app.mcp import tools as tool_module

logger = logging.getLogger(__name__)


def create_mcp_server() -> FastMCP:
    """Create and configure the FastMCP server instance."""
    settings = get_settings()

    mcp = FastMCP(
        name=settings.mcp_server_name,
        stateless_http=settings.mcp_stateless,
    )

    _register_tools(mcp)
    _register_resources(mcp)
    _register_prompts(mcp)

    logger.info("MCP server created: %s", settings.mcp_server_name)
    return mcp


def _get_session():
    """Get a new async database session from the shared factory."""
    factory = get_session_factory()
    return factory()


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def _register_tools(mcp: FastMCP) -> None:
    @mcp.tool(
        name="list_knowledge_bases",
        description=(
            "列出所有可用的知识库及其描述和文档数量。"
            "这是使用 RAG 平台的第一步——通过此工具了解有哪些知识库可供检索，"
            "然后使用返回的 knowledge_base_id 调用 search_knowledge_base 进行检索。"
        ),
    )
    async def list_knowledge_bases_tool() -> str:
        async with _get_session() as session:
            return await tool_module.list_knowledge_bases(session)

    @mcp.tool(
        name="search_knowledge_base",
        description=(
            "在指定知识库中检索相关文档内容。使用混合检索（语义向量+稀疏向量+BM25）"
            "并可选精排重排序，返回最相关的文档片段及其来源信息。"
            "当用户需要查找参考资料、验证事实、获取专业知识时调用此工具。"
            "调用前请先使用 list_knowledge_bases 工具确定目标知识库的 ID。"
        ),
    )
    async def search_knowledge_base_tool(
        knowledge_base_id: str,
        query: str,
        top_n: int = 5,
        enable_reranker: bool = True,
    ) -> str:
        retrieval_service = await get_retrieval_service()
        return await tool_module.search_knowledge_base(
            retrieval_service=retrieval_service,
            knowledge_base_id=knowledge_base_id,
            query=query,
            top_n=top_n,
            enable_reranker=enable_reranker,
        )

    @mcp.tool(
        name="get_knowledge_base_detail",
        description=(
            "获取指定知识库的详细信息，包括描述和所有文档列表。"
            "当需要了解某个知识库具体包含哪些文档、文档状态时使用。"
        ),
    )
    async def get_knowledge_base_detail_tool(knowledge_base_id: str) -> str:
        async with _get_session() as session:
            return await tool_module.get_knowledge_base_detail(session, knowledge_base_id)

    @mcp.tool(
        name="get_platform_stats",
        description=(
            "获取 RAG 平台的整体统计信息，包括知识库总数、文档总数、切片总数。"
            "当用户询问平台规模或运行状态时使用。"
        ),
    )
    async def get_platform_stats_tool() -> str:
        async with _get_session() as session:
            return await tool_module.get_platform_stats(session)


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


def _register_resources(mcp: FastMCP) -> None:
    @mcp.resource(
        uri="rag://knowledge-bases",
        name="知识库列表",
        description="所有可用知识库的列表（包含 ID、名称、描述、文档数）",
    )
    async def knowledge_bases_resource() -> str:
        async with _get_session() as session:
            return await resource_module.read_knowledge_bases(session)

    @mcp.resource(
        uri="rag://knowledge-bases/{kb_id}/info",
        name="知识库详情",
        description="指定知识库的详细信息和文档列表",
    )
    async def knowledge_base_info_resource(kb_id: str) -> str:
        async with _get_session() as session:
            return await resource_module.read_knowledge_base_info(session, kb_id)

    @mcp.resource(
        uri="rag://stats",
        name="平台统计",
        description="平台整体统计数据",
    )
    async def stats_resource() -> str:
        async with _get_session() as session:
            return await resource_module.read_stats(session)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


def _register_prompts(mcp: FastMCP) -> None:
    @mcp.prompt(
        name="search_and_answer",
        description="在知识库中搜索信息并基于检索结果回答问题",
    )
    async def search_and_answer(
        query: str,
        knowledge_base_name: str | None = None,
    ) -> str:
        return prompt_module.search_and_answer_prompt(query, knowledge_base_name)

    @mcp.prompt(
        name="cross_kb_search",
        description="跨多个知识库搜索信息并综合回答",
    )
    async def cross_kb_search(query: str) -> str:
        return prompt_module.cross_kb_search_prompt(query)
