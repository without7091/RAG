from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from app.config import Settings
from app.exceptions import QueryRewriteError
from app.services.chat_completion_service import ChatCompletionService


@pytest.fixture
def chat_settings() -> Settings:
    return Settings(
        siliconflow_api_key="test-key",
        query_rewrite_url="https://api.siliconflow.cn/v1/chat/completions",
        query_rewrite_model="Qwen/Qwen3.5-4B",
        _env_file=None,
    )


@pytest.fixture
def chat_service(chat_settings: Settings) -> ChatCompletionService:
    return ChatCompletionService(
        client=AsyncMock(spec=httpx.AsyncClient),
        settings=chat_settings,
    )


class TestChatCompletionService:
    @respx.mock
    async def test_complete_json_posts_expected_payload(self, chat_settings: Settings):
        client = httpx.AsyncClient()
        service = ChatCompletionService(client=client, settings=chat_settings)
        route = respx.post("https://api.siliconflow.cn/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": '{"strategy":"expand","canonical_query":"标准写法","queries":["别名写法"]}'
                            }
                        }
                    ]
                },
            )
        )

        result = await service.complete_json(
            system_prompt="Rewrite queries",
            user_prompt="处理网关连接失败",
        )

        assert result["strategy"] == "expand"
        request_body = route.calls[0].request.read().decode("utf-8")
        assert '"model":"Qwen/Qwen3.5-4B"' in request_body
        assert '"messages"' in request_body
        await client.aclose()

    @respx.mock
    async def test_complete_json_raises_on_invalid_response(self, chat_settings: Settings):
        client = httpx.AsyncClient()
        service = ChatCompletionService(client=client, settings=chat_settings)
        respx.post("https://api.siliconflow.cn/v1/chat/completions").mock(
            return_value=httpx.Response(200, json={"choices": []})
        )

        with pytest.raises(QueryRewriteError):
            await service.complete_json("Rewrite queries", "处理网关连接失败")

        await client.aclose()
