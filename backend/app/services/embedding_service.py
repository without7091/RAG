import asyncio
import logging

import httpx

from app.config import get_settings
from app.core.httpx_client import get_httpx_client
from app.exceptions import EmbeddingError
from app.utils.retry import retry_on_api_error

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Dense embedding via HTTP API (OpenAI-compatible format).

    Supports automatic batching and fallback to one-by-one on 400 errors.
    """

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client
        settings = get_settings()
        self.api_url = settings.embedding_url
        self.api_key = settings.siliconflow_api_key
        self.model = settings.embedding_model
        self.dimension = settings.embedding_dimension
        self.batch_size = settings.embedding_batch_size
        self._concurrency_sem = asyncio.Semaphore(settings.embedding_concurrency)
        self._fallback_to_single = False

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        return await get_httpx_client()

    @retry_on_api_error(max_attempts=3)
    async def _call_api(self, texts: list[str]) -> list[list[float]]:
        """Call embedding API for a list of texts."""
        client = await self._get_client()
        payload = {
            "model": self.model,
            "input": texts,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = await client.post(self.api_url, json=payload, headers=headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise EmbeddingError(f"Embedding API returned {e.response.status_code}") from e
        except httpx.TimeoutException as e:
            raise TimeoutError(f"Embedding API timeout: {e}") from e

        data = response.json()
        embeddings = [item["embedding"] for item in data["data"]]
        return embeddings

    async def _embed_single(self, text: str) -> list[float]:
        """Embed a single text with concurrency control."""
        async with self._concurrency_sem:
            results = await self._call_api([text])
            return results[0]

    async def _embed_one_by_one(self, texts: list[str]) -> list[list[float]]:
        """Embed texts one at a time with concurrency semaphore."""
        tasks = [self._embed_single(t) for t in texts]
        return list(await asyncio.gather(*tasks))

    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        """Embed a batch, falling back to one-by-one on 400 errors."""
        if self._fallback_to_single:
            return await self._embed_one_by_one(batch)

        try:
            return await self._call_api(batch)
        except EmbeddingError as e:
            if "400" in str(e) and len(batch) > 1:
                logger.warning(
                    "Embedding API rejected batch of %d texts (400). "
                    "Falling back to one-by-one mode for remaining requests.",
                    len(batch),
                )
                self._fallback_to_single = True
                return await self._embed_one_by_one(batch)
            raise

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts into dense vectors.

        Automatically splits into batches of `batch_size` and falls back
        to one-by-one mode if the API rejects batch requests (HTTP 400).
        """
        if not texts:
            return []

        all_embeddings: list[list[float]] = []
        total = len(texts)

        for i in range(0, total, self.batch_size):
            batch = texts[i : i + self.batch_size]
            batch_num = i // self.batch_size + 1
            total_batches = (total + self.batch_size - 1) // self.batch_size
            logger.debug(
                "Embedding batch %d/%d (%d texts)", batch_num, total_batches, len(batch)
            )
            result = await self._embed_batch(batch)
            all_embeddings.extend(result)

        return all_embeddings

    async def embed_query(self, query: str) -> list[float]:
        """Embed a single query string."""
        results = await self.embed_texts([query])
        return results[0]
