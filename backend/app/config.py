from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── API Keys ──
    siliconflow_api_key: str = "sk-placeholder"

    # ── Dense Embedding ──
    # Full URL to the embedding endpoint (override for intranet deployment)
    embedding_url: str = "https://api.siliconflow.cn/v1/embeddings"
    embedding_model: str = "Qwen/Qwen3-Embedding-4B"
    embedding_dimension: int = 1024

    # ── Reranker ──
    reranker_url: str = "https://api.siliconflow.cn/v1/rerank"
    reranker_model: str = "Qwen/Qwen3-Reranker-4B"
    reranker_min_score: float = 0.1

    # ── Sparse Embedding ──
    # "api" = call remote HTTP endpoint; "local" = use local FastEmbed model
    sparse_embedding_mode: str = "api"
    # API mode settings
    sparse_embedding_url: str = "https://api.siliconflow.cn/v1/embeddings"
    sparse_embedding_model: str = "Qdrant/bm42-all-minilm-l6-v2-attentions"
    # Local mode settings (only used when sparse_embedding_mode=local)
    fastembed_cache_path: str = "./data/fastembed_cache"
    fastembed_model_name: str = "Qdrant/bm42-all-minilm-l6-v2-attentions"

    # ── Qdrant ──
    qdrant_storage_path: str = "./data/qdrant_storage"

    # ── SQLite metadata ──
    sqlite_database_url: str = "sqlite+aiosqlite:///./data/metadata.db"

    # ── Upload ──
    upload_dir: str = "./data/uploads"
    max_upload_size_mb: int = 100

    # ── Embedding batching ──
    embedding_batch_size: int = 64      # Max texts per single API call
    embedding_concurrency: int = 5      # Max concurrent requests when falling back to one-by-one

    # ── Pipeline Worker ──
    pipeline_max_concurrency: int = 2       # Max documents processed concurrently
    pipeline_poll_interval: float = 2.0     # Seconds between polling for PENDING docs

    # ── Retrieval defaults ──
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
