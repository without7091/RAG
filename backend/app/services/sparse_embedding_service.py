import asyncio
import logging

import httpx

from app.config import get_settings
from app.core.httpx_client import get_httpx_client
from app.exceptions import EmbeddingError
from app.utils.retry import retry_on_api_error

logger = logging.getLogger(__name__)


class SparseEmbeddingService:
    """Sparse embedding service with two modes:

    - "api": Call a remote HTTP endpoint (default, for intranet deployment)
    - "local": Use local FastEmbed SPLADE model (requires fastembed + model files)

    API mode supports automatic batching and fallback to one-by-one on 400 errors.
    """

    def __init__(self, client: httpx.AsyncClient | None = None):
        settings = get_settings()
        self.mode = settings.sparse_embedding_mode
        self._client = client
        self.batch_size = settings.embedding_batch_size
        self._concurrency_sem = asyncio.Semaphore(settings.embedding_concurrency)
        self._fallback_to_single = False

        if self.mode == "api":
            self.api_url = settings.sparse_embedding_url
            self.api_key = settings.siliconflow_api_key
            self.model = settings.sparse_embedding_model
        elif self.mode == "local":
            self._local_model = None
            self._cache_path = settings.fastembed_cache_path
            self._model_name = settings.fastembed_model_name
        else:
            raise ValueError(f"Unknown sparse_embedding_mode: {self.mode!r} (expected 'api' or 'local')")

    # ── API mode ──

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        return await get_httpx_client()

    @staticmethod
    def _parse_sparse_results(data: dict) -> list[dict]:
        """Parse API response into list of sparse vectors."""
        if "data" not in data:
            raise EmbeddingError(
                f"Sparse embedding API response missing 'data' field. "
                f"Response keys: {list(data.keys())}"
            )
        results = []
        for i, item in enumerate(data["data"]):
            if "embedding" not in item:
                raise EmbeddingError(
                    f"Sparse embedding API response item[{i}] missing 'embedding' field. "
                    f"Item keys: {list(item.keys())}"
                )
            emb = item["embedding"]
            if isinstance(emb, dict):
                results.append({
                    "indices": emb.get("indices", []),
                    "values": emb.get("values", []),
                })
            elif isinstance(emb, list):
                indices = [i for i, v in enumerate(emb) if v != 0.0]
                values = [emb[i] for i in indices]
                results.append({"indices": indices, "values": values})
            else:
                results.append({"indices": [], "values": []})
        return results

    @retry_on_api_error(max_attempts=3)
    async def _call_api(self, texts: list[str]) -> list[dict]:
        """Call sparse embedding API for a list of texts."""
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
            raise EmbeddingError(
                f"Sparse embedding API returned {e.response.status_code}"
            ) from e
        except httpx.TimeoutException as e:
            raise TimeoutError(f"Sparse embedding API timeout: {e}") from e

        return self._parse_sparse_results(response.json())

    async def _embed_single_api(self, text: str) -> dict:
        """Embed a single text via API with concurrency control."""
        async with self._concurrency_sem:
            results = await self._call_api([text])
            return results[0]

    async def _embed_one_by_one_api(self, texts: list[str]) -> list[dict]:
        """Embed texts one at a time via API with concurrency semaphore."""
        tasks = [self._embed_single_api(t) for t in texts]
        return list(await asyncio.gather(*tasks))

    async def _embed_batch_api(self, batch: list[str]) -> list[dict]:
        """Embed a batch via API, falling back to one-by-one on 400 errors."""
        if self._fallback_to_single:
            return await self._embed_one_by_one_api(batch)

        try:
            return await self._call_api(batch)
        except EmbeddingError as e:
            if "400" in str(e) and len(batch) > 1:
                logger.warning(
                    "Sparse embedding API rejected batch of %d texts (400). "
                    "Falling back to one-by-one mode for remaining requests.",
                    len(batch),
                )
                self._fallback_to_single = True
                return await self._embed_one_by_one_api(batch)
            raise

    async def _api_embed_texts(self, texts: list[str]) -> list[dict]:
        """Embed texts via API with automatic batching."""
        all_results: list[dict] = []
        total = len(texts)

        for i in range(0, total, self.batch_size):
            batch = texts[i : i + self.batch_size]
            batch_num = i // self.batch_size + 1
            total_batches = (total + self.batch_size - 1) // self.batch_size
            logger.debug(
                "Sparse embedding batch %d/%d (%d texts)", batch_num, total_batches, len(batch)
            )
            result = await self._embed_batch_api(batch)
            all_results.extend(result)

        return all_results

    # ── Local mode ──

    def _get_local_model(self):
        if self._local_model is None:
            import os

            os.environ.setdefault("FASTEMBED_CACHE_PATH", self._cache_path)
            from fastembed import SparseTextEmbedding

            self._local_model = SparseTextEmbedding(model_name=self._model_name)
            logger.info(f"Loaded local sparse model: {self._model_name}")
        return self._local_model

    def _local_embed_texts(self, texts: list[str]) -> list[dict]:
        model = self._get_local_model()
        embeddings = list(model.embed(texts))
        return [
            {"indices": emb.indices.tolist(), "values": emb.values.tolist()}
            for emb in embeddings
        ]

    # ── Public interface ──

    async def embed_texts_async(self, texts: list[str]) -> list[dict]:
        """Generate sparse vectors (async).

        In local mode, FastEmbed inference is CPU-bound; it is offloaded to a
        thread via run_in_executor so the event loop is not blocked.
        """
        if not texts:
            return []
        if self.mode == "api":
            return await self._api_embed_texts(texts)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._local_embed_texts, texts)

    def embed_texts(self, texts: list[str]) -> list[dict]:
        """Generate sparse vectors (sync, for local mode or when called from sync context).

        For API mode, raises RuntimeError — use embed_texts_async instead.
        """
        if not texts:
            return []
        if self.mode == "local":
            return self._local_embed_texts(texts)
        raise RuntimeError(
            "SparseEmbeddingService in 'api' mode requires async context. "
            "Use embed_texts_async() instead."
        )

    async def embed_query_async(self, query: str) -> dict:
        """Generate sparse vector for a single query (async)."""
        results = await self.embed_texts_async([query])
        return results[0]

    def embed_query(self, query: str) -> dict:
        """Generate sparse vector for a single query (sync, local mode only)."""
        results = self.embed_texts([query])
        return results[0]
