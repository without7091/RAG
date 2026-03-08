from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_BASE_DIR = Path(__file__).resolve().parents[1]
_ENV_FILE = _BASE_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # API keys
    siliconflow_api_key: str = "sk-placeholder"

    # Dense embedding
    embedding_url: str = "https://api.siliconflow.cn/v1/embeddings"
    embedding_model: str = "Qwen/Qwen3-Embedding-4B"
    embedding_dimension: int = 2560

    # Reranker and query rewrite
    reranker_url: str = "https://api.siliconflow.cn/v1/rerank"
    reranker_model: str = "Qwen/Qwen3-Reranker-4B"
    reranker_concurrency: int = 5
    reranker_min_score: float = 0.1
    default_enable_reranker: bool = True
    query_rewrite_mode: str = "dynamic"
    query_rewrite_url: str = "https://api.siliconflow.cn/v1/chat/completions"
    query_rewrite_model: str = "Pro/zai-org/GLM-4.7"
    query_rewrite_timeout_ms: int = 15_000
    query_rewrite_connect_timeout_s: float = 5.0
    query_rewrite_read_timeout_s: float | None = None
    query_rewrite_write_timeout_s: float | None = None
    query_rewrite_pool_timeout_s: float = 10.0
    query_rewrite_concurrency: int = 10
    query_rewrite_max_queries: int = 3
    query_rewrite_cache_ttl: int = 300
    query_rewrite_rerank_pool_size: int = 40

    # Sparse embedding
    sparse_embedding_mode: str = "local"
    sparse_embedding_url: str = "https://api.siliconflow.cn/v1/embeddings"
    sparse_embedding_model: str = "Qdrant/bm25"
    fastembed_cache_path: str = "./data/fastembed_cache"
    fastembed_model_name: str = "Qdrant/bm25"

    # BM25
    bm25_vocab_size: int = 1_048_576
    bm25_stopwords_path: str | None = None

    # Qdrant
    qdrant_storage_path: str = "./data/qdrant_storage"

    # SQLite metadata
    sqlite_database_url: str = "sqlite+aiosqlite:///./data/metadata.db"

    # Uploads
    upload_dir: str = "./data/uploads"
    max_upload_size_mb: int = 100

    # Shared HTTP client resilience
    http_connect_timeout_s: float = 10.0
    http_read_timeout_s: float = 180.0
    http_write_timeout_s: float = 180.0
    http_pool_timeout_s: float = 30.0

    # Embedding batching
    embedding_batch_size: int = 64
    embedding_concurrency: int = 5

    # Pipeline worker
    pipeline_max_concurrency: int = 2
    pipeline_poll_interval: float = 2.0
    pipeline_retry_attempts: int = 2
    pipeline_retry_backoff_s: float = 5.0

    # Retrieval defaults
    default_top_k: int = 20
    default_top_n: int = 3
    chunk_size: int = 1024
    chunk_overlap: int = 128
    min_chunk_size: int = 50
    header_prefix_template: str = "[{path}]\n\n"
    header_separator: str = " > "

    @property
    def upload_path(self) -> Path:
        return Path(self.upload_dir)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    """Clear cached settings and reload from current environment."""
    get_settings.cache_clear()
    return get_settings()
