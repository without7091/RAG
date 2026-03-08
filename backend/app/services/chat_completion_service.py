import asyncio
import json
import logging
import time
from collections.abc import Mapping

import httpx

from app.config import Settings, get_settings
from app.core.httpx_client import build_query_rewrite_timeout, get_httpx_client
from app.exceptions import QueryRewriteError
from app.utils.retry import is_retryable_status_code, retry_on_api_error

logger = logging.getLogger(__name__)


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
        self._concurrency_sem = asyncio.Semaphore(self._settings.query_rewrite_concurrency)

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
        async with self._concurrency_sem:
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
            timeout = build_query_rewrite_timeout(self._settings)
            started_at = time.perf_counter()

            try:
                response = await client.post(
                    self.api_url,
                    json=payload,
                    headers=headers,
                    timeout=timeout,
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                retryable = is_retryable_status_code(status_code)
                logger.warning(
                    "Query rewrite upstream request failed (upstream=query_rewrite, status_code=%s, retryable=%s, elapsed_ms=%.1f): %s",
                    status_code,
                    retryable,
                    (time.perf_counter() - started_at) * 1000,
                    exc,
                )
                raise QueryRewriteError(
                    f"Query rewrite API returned {status_code}",
                    status_code=status_code,
                    retryable=retryable,
                    upstream="query_rewrite",
                ) from exc
            except httpx.TimeoutException as exc:
                logger.warning(
                    "Query rewrite upstream request failed (upstream=query_rewrite, status_code=None, retryable=True, elapsed_ms=%.1f): %s",
                    (time.perf_counter() - started_at) * 1000,
                    exc,
                )
                raise QueryRewriteError(
                    f"Query rewrite API timeout: {exc}",
                    retryable=True,
                    upstream="query_rewrite",
                ) from exc
            except httpx.HTTPError as exc:
                logger.warning(
                    "Query rewrite upstream request failed (upstream=query_rewrite, status_code=None, retryable=True, elapsed_ms=%.1f): %s",
                    (time.perf_counter() - started_at) * 1000,
                    exc,
                )
                raise QueryRewriteError(
                    f"Query rewrite API error: {exc}",
                    retryable=True,
                    upstream="query_rewrite",
                ) from exc

            logger.debug(
                "Query rewrite upstream request succeeded (upstream=query_rewrite, elapsed_ms=%.1f)",
                (time.perf_counter() - started_at) * 1000,
            )

            try:
                data = response.json()
            except ValueError as exc:
                raise QueryRewriteError(
                    "Query rewrite API returned non-JSON payload",
                    retryable=False,
                    upstream="query_rewrite",
                ) from exc

            content = self._extract_content(data)
            return self._parse_json_object(content)

    def _extract_content(self, data: object) -> str | dict:
        if not isinstance(data, Mapping):
            raise QueryRewriteError(
                "Invalid chat completion response format",
                retryable=False,
                upstream="query_rewrite",
            )

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise QueryRewriteError(
                "Missing chat completion choices",
                retryable=False,
                upstream="query_rewrite",
            )

        message = choices[0].get("message")
        if not isinstance(message, Mapping):
            raise QueryRewriteError(
                "Missing chat completion message",
                retryable=False,
                upstream="query_rewrite",
            )

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

        raise QueryRewriteError(
            "Unsupported chat completion content format",
            retryable=False,
            upstream="query_rewrite",
        )

    def _parse_json_object(self, content: str | dict) -> dict:
        if isinstance(content, dict):
            return content

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            start = content.find("{")
            end = content.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise QueryRewriteError(
                    "Chat completion did not return valid JSON",
                    retryable=False,
                    upstream="query_rewrite",
                ) from exc
            try:
                parsed = json.loads(content[start : end + 1])
            except json.JSONDecodeError as nested_exc:
                raise QueryRewriteError(
                    "Chat completion did not return valid JSON",
                    retryable=False,
                    upstream="query_rewrite",
                ) from nested_exc

        if not isinstance(parsed, dict):
            raise QueryRewriteError(
                "Chat completion JSON must be an object",
                retryable=False,
                upstream="query_rewrite",
            )
        return parsed
