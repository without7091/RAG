import json
from collections.abc import Mapping

import httpx

from app.config import Settings, get_settings
from app.core.httpx_client import get_httpx_client
from app.exceptions import QueryRewriteError
from app.utils.retry import retry_on_api_error


class ChatCompletionService:
    """Minimal OpenAI-compatible chat completion wrapper for query rewriting."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        settings: Settings | None = None,
    ):
        self._client = client
        self._settings = settings or get_settings()
        self.api_url = self._settings.query_rewrite_url
        self.api_key = self._settings.siliconflow_api_key
        self.model = self._settings.query_rewrite_model

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        return await get_httpx_client()

    @retry_on_api_error(max_attempts=2)
    async def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> dict:
        """Call the configured chat endpoint and parse a JSON object response."""
        client = await self._get_client()
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 256,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = await client.post(
                self.api_url,
                json=payload,
                headers=headers,
                timeout=self._settings.query_rewrite_timeout_ms / 1000,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise QueryRewriteError(
                f"Query rewrite API returned {exc.response.status_code}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise QueryRewriteError(f"Query rewrite API timeout: {exc}") from exc
        except httpx.HTTPError as exc:
            raise QueryRewriteError(f"Query rewrite API error: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise QueryRewriteError("Query rewrite API returned non-JSON payload") from exc

        content = self._extract_content(data)
        return self._parse_json_object(content)

    def _extract_content(self, data: object) -> str | dict:
        if not isinstance(data, Mapping):
            raise QueryRewriteError("Invalid chat completion response format")

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise QueryRewriteError("Missing chat completion choices")

        message = choices[0].get("message")
        if not isinstance(message, Mapping):
            raise QueryRewriteError("Missing chat completion message")

        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, Mapping) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            if parts:
                return "\n".join(parts)
        if isinstance(content, Mapping):
            return dict(content)

        raise QueryRewriteError("Unsupported chat completion content format")

    def _parse_json_object(self, content: str | dict) -> dict:
        if isinstance(content, dict):
            return content

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            start = content.find("{")
            end = content.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise QueryRewriteError("Chat completion did not return valid JSON") from exc
            try:
                parsed = json.loads(content[start : end + 1])
            except json.JSONDecodeError as nested_exc:
                raise QueryRewriteError("Chat completion did not return valid JSON") from nested_exc

        if not isinstance(parsed, dict):
            raise QueryRewriteError("Chat completion JSON must be an object")
        return parsed
