from qdrant_client import AsyncQdrantClient

from app.config import get_settings

_client: AsyncQdrantClient | None = None


async def get_qdrant_client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncQdrantClient(path=settings.qdrant_storage_path)
    return _client


async def get_qdrant_memory_client() -> AsyncQdrantClient:
    """Create an in-memory Qdrant client for testing."""
    return AsyncQdrantClient(location=":memory:")


async def close_qdrant_client() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
