"""Integration tests for MCP server — verifies tool discovery, tool calls, and resources."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.document import Document, DocumentStatus
from app.models.knowledge_base import KnowledgeBase
from app.utils.id_gen import generate_kb_id


@pytest.fixture
async def mcp_app():
    """Create a FastAPI app with MCP mounted and in-memory DB."""
    from app.db import session as session_mod
    from app.main import create_app

    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    original_engine = session_mod._engine
    original_factory = session_mod._session_factory
    session_mod._engine = engine
    session_mod._session_factory = factory

    app = create_app()

    yield app, factory

    session_mod._engine = original_engine
    session_mod._session_factory = original_factory
    await engine.dispose()


@pytest.fixture
async def seeded_mcp_app(mcp_app):
    """MCP app with test data seeded into the database."""
    app, factory = mcp_app

    async with factory() as session:
        kb = KnowledgeBase(
            knowledge_base_id=generate_kb_id(),
            knowledge_base_name="测试知识库",
            description="用于 MCP 集成测试",
        )
        session.add(kb)
        await session.commit()

        doc = Document(
            doc_id="doc_test_001",
            file_name="测试文档.pdf",
            knowledge_base_id=kb.knowledge_base_id,
            status=DocumentStatus.COMPLETED,
            chunk_count=42,
        )
        session.add(doc)
        await session.commit()

        kb_id = kb.knowledge_base_id

    yield app, kb_id


class TestMCPEndpointExists:
    """Verify the /mcp endpoint is reachable via HTTP."""

    async def test_mcp_endpoint_reachable(self, mcp_app):
        """The /mcp endpoint should respond (even if not a valid MCP request)."""
        from httpx import ASGITransport, AsyncClient

        app, _ = mcp_app
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # A GET to /mcp should return something (MCP uses POST for RPC,
            # but GET should at least not 404)
            response = await client.get("/mcp")
            # Streamable HTTP MCP endpoint should return 405 for GET
            # (it only accepts POST), but not 404
            assert response.status_code != 404

    async def test_mcp_mount_does_not_duplicate_subpath(self, mcp_app):
        """The mounted sub-app should expose MCP at /mcp, not /mcp/mcp."""
        app, _ = mcp_app

        mcp_mount = next(route for route in app.routes if getattr(route, "path", None) == "/mcp")
        child_paths = {getattr(route, "path", None) for route in mcp_mount.app.routes}

        assert "/mcp" not in child_paths

    def test_mcp_http_requests_do_not_fail_with_uninitialized_task_group(self):
        """A malformed MCP request should return protocol/user error, not framework startup failure."""
        from starlette.testclient import TestClient

        from app.mcp.server import create_mcp_server

        mcp_server = create_mcp_server()
        mcp_asgi = mcp_server.streamable_http_app()

        with TestClient(mcp_asgi, raise_server_exceptions=False) as client:
            response = client.get("/")

        assert response.status_code != 500
        assert "Task group is not initialized" not in response.text


class TestMCPServerRegistration:
    """Test that the MCP server has the expected tools, resources, and prompts registered."""

    async def test_server_has_tools(self):
        """Verify all 4 tools are registered."""
        from app.mcp.server import create_mcp_server

        mcp = create_mcp_server()
        # FastMCP exposes tools via _tool_manager
        tool_names = set()
        for tool in mcp._tool_manager.list_tools():
            tool_names.add(tool.name)

        assert "list_knowledge_bases" in tool_names
        assert "search_knowledge_base" in tool_names
        assert "get_knowledge_base_detail" in tool_names
        assert "get_platform_stats" in tool_names

    async def test_server_has_resources(self):
        """Verify all 3 resources are registered."""
        from app.mcp.server import create_mcp_server

        mcp = create_mcp_server()
        resource_uris = set()
        for resource in mcp._resource_manager.list_resources():
            resource_uris.add(str(resource.uri))

        assert "rag://knowledge-bases" in resource_uris
        assert "rag://stats" in resource_uris

    async def test_server_has_prompts(self):
        """Verify all 2 prompts are registered."""
        from app.mcp.server import create_mcp_server

        mcp = create_mcp_server()
        prompt_names = set()
        for prompt in mcp._prompt_manager.list_prompts():
            prompt_names.add(prompt.name)

        assert "search_and_answer" in prompt_names
        assert "cross_kb_search" in prompt_names

    async def test_tool_descriptions_contain_guidance(self):
        """Verify tool descriptions guide the agent on usage order."""
        from app.mcp.server import create_mcp_server

        mcp = create_mcp_server()
        tools_by_name = {t.name: t for t in mcp._tool_manager.list_tools()}

        # list_knowledge_bases should mention it's the first step
        assert "第一步" in tools_by_name["list_knowledge_bases"].description

        # search_knowledge_base should reference list_knowledge_bases
        assert "list_knowledge_bases" in tools_by_name["search_knowledge_base"].description

    async def test_search_tool_schema_validates_query_and_top_n(self):
        """The MCP tool schema should expose the same basic constraints as the REST API."""
        from app.mcp.server import create_mcp_server

        mcp = create_mcp_server()
        tools_by_name = {t.name: t for t in mcp._tool_manager.list_tools()}
        schema = tools_by_name["search_knowledge_base"].parameters
        properties = schema["properties"]

        assert properties["query"].get("minLength") == 1
        assert properties["top_n"].get("minimum") == 1

    async def test_search_tool_schema_defaults_follow_settings(self, monkeypatch):
        """The advertised MCP defaults should follow runtime configuration."""
        from app.config import reload_settings
        from app.mcp.server import create_mcp_server

        with monkeypatch.context() as m:
            m.setenv("MCP_DEFAULT_TOP_N", "9")
            m.setenv("MCP_DEFAULT_ENABLE_RERANKER", "false")
            reload_settings()
            mcp = create_mcp_server()

        reload_settings()

        tools_by_name = {t.name: t for t in mcp._tool_manager.list_tools()}
        properties = tools_by_name["search_knowledge_base"].parameters["properties"]

        assert properties["top_n"]["default"] == 9
        assert properties["enable_reranker"]["default"] is False


class TestMCPToolExecution:
    """Test tool execution via the MCP server with real DB."""

    async def test_list_knowledge_bases_tool(self, seeded_mcp_app):
        """Call list_knowledge_bases tool and verify output."""
        from app.mcp.tools import list_knowledge_bases
        from app.db.session import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            result = await list_knowledge_bases(session)

        assert "测试知识库" in result
        assert "文档数: 1" in result

    async def test_get_knowledge_base_detail_tool(self, seeded_mcp_app):
        """Call get_knowledge_base_detail tool and verify output."""
        from app.mcp.tools import get_knowledge_base_detail
        from app.db.session import get_session_factory

        _, kb_id = seeded_mcp_app
        factory = get_session_factory()
        async with factory() as session:
            result = await get_knowledge_base_detail(session, kb_id)

        assert "测试知识库" in result
        assert "测试文档.pdf" in result
        assert "42 个片段" in result

    async def test_get_platform_stats_tool(self, seeded_mcp_app):
        """Call get_platform_stats tool and verify output."""
        from app.mcp.tools import get_platform_stats
        from app.db.session import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            result = await get_platform_stats(session)

        assert "知识库总数: 1" in result
        assert "文档总数: 1" in result


class TestMCPResourceExecution:
    """Test resource reads with real DB."""

    async def test_knowledge_bases_resource(self, seeded_mcp_app):
        from app.mcp.resources import read_knowledge_bases
        from app.db.session import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            result = await read_knowledge_bases(session)

        assert "测试知识库" in result

    async def test_stats_resource(self, seeded_mcp_app):
        from app.mcp.resources import read_stats
        from app.db.session import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            result = await read_stats(session)

        assert "知识库总数: 1" in result


class TestExistingAPIUnaffected:
    """Verify that enabling MCP doesn't break existing REST API."""

    async def test_rest_api_still_works(self, mcp_app):
        from httpx import ASGITransport, AsyncClient

        app, _ = mcp_app
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/v1/stats")
            assert response.status_code == 200
            data = response.json()
            assert "total_knowledge_bases" in data
