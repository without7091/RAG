from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.exceptions import QueryRewriteError
from app.services.query_rewrite_service import QueryRewriteService


@pytest.fixture
def rewrite_settings() -> Settings:
    return Settings(
        siliconflow_api_key="test-key",
        query_rewrite_max_queries=3,
        query_rewrite_cache_ttl=300,
        query_rewrite_model="Qwen/Qwen3.5-4B",
        _env_file=None,
    )


class TestQueryRewriteService:
    async def test_build_plan_bypasses_precise_identifier_queries(self, rewrite_settings: Settings):
        chat_service = AsyncMock()
        service = QueryRewriteService(chat_service=chat_service, settings=rewrite_settings)

        plan = await service.build_plan("ERR-104 网关连接失败")

        assert plan.strategy == "bypass"
        assert plan.final_queries == ["ERR-104 网关连接失败"]
        chat_service.complete_json.assert_not_called()

    async def test_build_plan_uses_chat_output_for_expand(self, rewrite_settings: Settings):
        chat_service = AsyncMock()
        chat_service.complete_json = AsyncMock(return_value={
            "strategy": "expand",
            "canonical_query": "网关连接失败 故障排查",
            "queries": ["网关连不上 如何排查", "gateway 连接失败 处理"],
        })
        service = QueryRewriteService(chat_service=chat_service, settings=rewrite_settings)

        plan = await service.build_plan("怎么处理网关连接失败")

        assert plan.strategy == "expand"
        assert plan.canonical_query == "网关连接失败 故障排查"
        assert plan.final_queries == [
            "怎么处理网关连接失败",
            "网关连接失败 故障排查",
            "网关连不上 如何排查",
        ]

    async def test_build_plan_falls_back_to_heuristic_decompose(
        self,
        rewrite_settings: Settings,
    ):
        chat_service = AsyncMock()
        chat_service.complete_json = AsyncMock(side_effect=QueryRewriteError("bad response"))
        service = QueryRewriteService(chat_service=chat_service, settings=rewrite_settings)

        plan = await service.build_plan("网关连接失败和认证异常怎么处理")

        assert plan.strategy == "decompose"
        assert plan.fallback_used is True
        assert plan.final_queries == [
            "网关连接失败和认证异常怎么处理",
            "网关连接失败怎么处理",
            "认证异常怎么处理",
        ]
