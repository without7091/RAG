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
    """

    def __init__(self, client: httpx.AsyncClient | None = None):
        settings = get_settings()
        self.mode = settings.sparse_embedding_mode
        self._client = client

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

    @retry_on_api_error(max_attempts=3)
    async def _api_embed_texts(self, texts: list[str]) -> list[dict]:
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

        data = response.json()
        results = []
        for item in data["data"]:
            emb = item["embedding"]
            # API may return dense-style vector or sparse {indices, values} dict
            if isinstance(emb, dict):
                results.append({
                    "indices": emb.get("indices", []),
                    "values": emb.get("values", []),
                })
            elif isinstance(emb, list):
                # Dense-format returned — convert to sparse by taking non-zero entries
                indices = [i for i, v in enumerate(emb) if v != 0.0]
                values = [emb[i] for i in indices]
                results.append({"indices": indices, "values": values})
            else:
                results.append({"indices": [], "values": []})
        return results

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
        """Generate sparse vectors (async, for API mode)."""
        if not texts:
            return []
        if self.mode == "api":
            return await self._api_embed_texts(texts)
        return self._local_embed_texts(texts)

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
