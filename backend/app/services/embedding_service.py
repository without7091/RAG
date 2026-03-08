import asyncio
import logging
import time

import httpx

from app.config import Settings, get_settings
from app.core.httpx_client import get_httpx_client
from app.exceptions import EmbeddingError
from app.utils.retry import is_retryable_status_code, retry_on_api_error

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Dense embedding via HTTP API."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        settings: Settings | None = None,
    ):
        self._client = client
        self._settings = settings or get_settings()
        self.api_url = self._settings.embedding_url
        self.api_key = self._settings.siliconflow_api_key
        self.model = self._settings.embedding_model
        self.dimension = self._settings.embedding_dimension
        self.batch_size = self._settings.embedding_batch_size
        self._concurrency_sem = asyncio.Semaphore(self._settings.embedding_concurrency)
        self._fallback_to_single = False

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        return await get_httpx_client()

    def _validate_embeddings_response(
        self,
        response_data: object,
        expected_count: int,
    ) -> list[list[float]]:
        if not isinstance(response_data, dict):
            raise EmbeddingError(
                "Invalid embedding response: expected JSON object",
                retryable=False,
                upstream="embedding",
            )

        items = response_data.get("data")
        if not isinstance(items, list):
            raise EmbeddingError(
                "Invalid embedding response: missing list field 'data'",
                retryable=False,
                upstream="embedding",
            )
        if len(items) != expected_count:
            raise EmbeddingError(
                "Embedding response count mismatch: "
                f"expected {expected_count}, got {len(items)}",
                retryable=False,
                upstream="embedding",
            )

        embeddings: list[list[float]] = []
        for i, item in enumerate(items):
            if not isinstance(item, dict) or "embedding" not in item:
                raise EmbeddingError(
                    f"Invalid embedding response item at index {i}",
                    retryable=False,
                    upstream="embedding",
                )
            vector = item["embedding"]
            if not isinstance(vector, list):
                raise EmbeddingError(
                    f"Invalid embedding vector type at index {i}",
                    retryable=False,
                    upstream="embedding",
                )
            if len(vector) != self.dimension:
                raise EmbeddingError(
                    "Embedding vector dimension mismatch at index "
                    f"{i}: expected {self.dimension}, got {len(vector)}",
                    retryable=False,
                    upstream="embedding",
                )
            embeddings.append(vector)

        return embeddings

    @retry_on_api_error(max_attempts=3)
    async def _call_api(self, texts: list[str]) -> list[list[float]]:
        """Call the embedding API for a list of texts."""
        async with self._concurrency_sem:
            client = await self._get_client()
            payload = {
                "model": self.model,
                "input": texts,
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
                    "Embedding upstream request failed (upstream=embedding, status_code=%s, retryable=%s, elapsed_ms=%.1f): %s",
                    status_code,
                    retryable,
                    (time.perf_counter() - started_at) * 1000,
                    exc,
                )
                raise EmbeddingError(
                    f"Embedding API returned {status_code}",
                    status_code=status_code,
                    retryable=retryable,
                    upstream="embedding",
                ) from exc
            except httpx.TimeoutException as exc:
                logger.warning(
                    "Embedding upstream request failed (upstream=embedding, status_code=None, retryable=True, elapsed_ms=%.1f): %s",
                    (time.perf_counter() - started_at) * 1000,
                    exc,
                )
                raise EmbeddingError(
                    f"Embedding API timeout: {exc}",
                    retryable=True,
                    upstream="embedding",
                ) from exc
            except httpx.HTTPError as exc:
                logger.warning(
                    "Embedding upstream request failed (upstream=embedding, status_code=None, retryable=True, elapsed_ms=%.1f): %s",
                    (time.perf_counter() - started_at) * 1000,
                    exc,
                )
                raise EmbeddingError(
                    f"Embedding API error: {exc}",
                    retryable=True,
                    upstream="embedding",
                ) from exc

            logger.debug(
                "Embedding upstream request succeeded (upstream=embedding, elapsed_ms=%.1f, batch_size=%d)",
                (time.perf_counter() - started_at) * 1000,
                len(texts),
            )

            try:
                data = response.json()
            except ValueError as exc:
                raise EmbeddingError(
                    "Invalid embedding response: non-JSON payload",
                    retryable=False,
                    upstream="embedding",
                ) from exc

            return self._validate_embeddings_response(data, expected_count=len(texts))

    async def _embed_single(self, text: str) -> list[float]:
        results = await self._call_api([text])
        return results[0]

    async def _embed_one_by_one(self, texts: list[str]) -> list[list[float]]:
        tasks = [self._embed_single(text) for text in texts]
        return list(await asyncio.gather(*tasks))

    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        if self._fallback_to_single:
            return await self._embed_one_by_one(batch)

        try:
            return await self._call_api(batch)
        except EmbeddingError as exc:
            if exc.status_code == 400 and len(batch) > 1:
                logger.warning(
                    "Embedding API rejected batch of %d texts (400). Falling back to one-by-one mode.",
                    len(batch),
                )
                self._fallback_to_single = True
                return await self._embed_one_by_one(batch)
            raise

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        all_embeddings: list[list[float]] = []
        total = len(texts)

        for i in range(0, total, self.batch_size):
            batch = texts[i : i + self.batch_size]
            batch_num = i // self.batch_size + 1
            total_batches = (total + self.batch_size - 1) // self.batch_size
            logger.debug(
                "Embedding batch %d/%d (%d texts)",
                batch_num,
                total_batches,
                len(batch),
            )
            result = await self._embed_batch(batch)
            all_embeddings.extend(result)

        return all_embeddings

    async def embed_query(self, query: str) -> list[float]:
        results = await self.embed_texts([query])
        return results[0]
