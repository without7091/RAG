import logging

import httpx

from app.config import get_settings
from app.core.httpx_client import get_httpx_client
from app.exceptions import EmbeddingError
from app.utils.retry import retry_on_api_error

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Dense embedding via HTTP API (OpenAI-compatible format)."""

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client
        settings = get_settings()
        self.api_url = settings.embedding_url
        self.api_key = settings.siliconflow_api_key
        self.model = settings.embedding_model
        self.dimension = settings.embedding_dimension

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        return await get_httpx_client()

    @retry_on_api_error(max_attempts=3)
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts into dense vectors."""
        if not texts:
            return []

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

    async def embed_query(self, query: str) -> list[float]:
        """Embed a single query string."""
        results = await self.embed_texts([query])
        return results[0]
