import logging

import httpx

from app.config import get_settings
from app.core.httpx_client import get_httpx_client
from app.exceptions import RerankerError
from app.utils.retry import retry_on_api_error

logger = logging.getLogger(__name__)


class RerankerService:
    """Reranker via SiliconFlow API (Qwen3-Reranker-4B)."""

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client
        settings = get_settings()
        self.api_url = settings.reranker_url
        self.api_key = settings.siliconflow_api_key
        self.model = settings.reranker_model

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
        """Rerank texts against a query, return top_n results.

        Returns list of dicts: [{"index": int, "score": float, "text": str}, ...]
        sorted by score descending.
        """
        if not texts:
            return []

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

        try:
            response = await client.post(self.api_url, json=payload, headers=headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RerankerError(f"Reranker API returned {e.response.status_code}") from e
        except httpx.TimeoutException as e:
            raise TimeoutError(f"Reranker API timeout: {e}") from e

        data = response.json()
        # API may return results as list or dict with "results" key
        results = data if isinstance(data, list) else data.get("results", [])

        scored = []
        for item in results:
            idx = item.get("index", 0)
            score = item.get("relevance_score", item.get("score", 0.0))
            scored.append({
                "index": idx,
                "score": score,
                "text": texts[idx] if idx < len(texts) else "",
            })

        # Sort by score descending, truncate to top_n
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_n]
