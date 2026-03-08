import asyncio
import logging
import time

import httpx

from app.config import Settings, get_settings
from app.core.httpx_client import get_httpx_client
from app.exceptions import RerankerError
from app.utils.retry import is_retryable_status_code, retry_on_api_error

logger = logging.getLogger(__name__)


class RerankerService:
    """Reranker via SiliconFlow-compatible HTTP API."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        settings: Settings | None = None,
    ):
        self._client = client
        self._settings = settings or get_settings()
        self.api_url = self._settings.reranker_url
        self.api_key = self._settings.siliconflow_api_key
        self.model = self._settings.reranker_model
        self._concurrency_sem = asyncio.Semaphore(self._settings.reranker_concurrency)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        return await get_httpx_client()

    @retry_on_api_error(max_attempts=3)
    async def rerank(
        self,
        query: str,
        texts: list[str],
        top_n: int = 3,
    ) -> list[dict]:
        """Rerank texts against a query and return top_n results."""
        if not texts:
            return []

        async with self._concurrency_sem:
            client = await self._get_client()
            payload = {
                "model": self.model,
                "query": query,
                "documents": texts,
                "top_n": top_n,
            }
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            started_at = time.perf_counter()

            try:
                response = await client.post(self.api_url, json=payload, headers=headers)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                retryable = is_retryable_status_code(status_code)
                logger.warning(
                    "Reranker upstream request failed (upstream=reranker, status_code=%s, retryable=%s, elapsed_ms=%.1f): %s",
                    status_code,
                    retryable,
                    (time.perf_counter() - started_at) * 1000,
                    exc,
                )
                raise RerankerError(
                    f"Reranker API returned {status_code}",
                    status_code=status_code,
                    retryable=retryable,
                    upstream="reranker",
                ) from exc
            except httpx.TimeoutException as exc:
                logger.warning(
                    "Reranker upstream request failed (upstream=reranker, status_code=None, retryable=True, elapsed_ms=%.1f): %s",
                    (time.perf_counter() - started_at) * 1000,
                    exc,
                )
                raise RerankerError(
                    f"Reranker API timeout: {exc}",
                    retryable=True,
                    upstream="reranker",
                ) from exc
            except httpx.HTTPError as exc:
                logger.warning(
                    "Reranker upstream request failed (upstream=reranker, status_code=None, retryable=True, elapsed_ms=%.1f): %s",
                    (time.perf_counter() - started_at) * 1000,
                    exc,
                )
                raise RerankerError(
                    f"Reranker API error: {exc}",
                    retryable=True,
                    upstream="reranker",
                ) from exc

            logger.debug(
                "Reranker upstream request succeeded (upstream=reranker, elapsed_ms=%.1f, documents=%d)",
                (time.perf_counter() - started_at) * 1000,
                len(texts),
            )

            try:
                data = response.json()
            except ValueError as exc:
                raise RerankerError(
                    "Invalid reranker response: non-JSON payload",
                    retryable=False,
                    upstream="reranker",
                ) from exc

            if isinstance(data, list):
                results = data
            elif isinstance(data, dict):
                results = data.get("results", [])
            else:
                raise RerankerError(
                    "Invalid reranker response format",
                    retryable=False,
                    upstream="reranker",
                )

            if not isinstance(results, list):
                raise RerankerError(
                    "Invalid reranker response: missing list field 'results'",
                    retryable=False,
                    upstream="reranker",
                )

            scored = []
            for item in results:
                if not isinstance(item, dict):
                    raise RerankerError(
                        "Invalid reranker response item",
                        retryable=False,
                        upstream="reranker",
                    )
                idx = item.get("index", 0)
                score = item.get("relevance_score", item.get("score", 0.0))
                scored.append({
                    "index": idx,
                    "score": score,
                    "text": texts[idx] if idx < len(texts) else "",
                })

            scored.sort(key=lambda candidate: candidate["score"], reverse=True)
            return scored[:top_n]
