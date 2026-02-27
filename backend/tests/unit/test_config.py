

from app.config import Settings


class TestSettings:
    def test_default_values(self):
        s = Settings(siliconflow_api_key="test-key")
        assert s.embedding_url == "https://api.siliconflow.cn/v1/embeddings"
        assert s.embedding_model == "Qwen/Qwen3-Embedding-4B"
        assert s.reranker_url == "https://api.siliconflow.cn/v1/rerank"
        assert s.reranker_model == "Qwen/Qwen3-Reranker-4B"
        assert s.embedding_dimension == 1024
        assert s.sparse_embedding_mode == "api"
        assert s.default_top_k == 10
        assert s.default_top_n == 3
        assert s.chunk_size == 512
        assert s.chunk_overlap == 64
        assert s.max_upload_size_mb == 100

    def test_embedding_url_property(self):
        s = Settings(siliconflow_api_key="test-key")
        assert s.embedding_url == "https://api.siliconflow.cn/v1/embeddings"

    def test_reranker_url_property(self):
        s = Settings(siliconflow_api_key="test-key")
        assert s.reranker_url == "https://api.siliconflow.cn/v1/rerank"

    def test_upload_path_property(self):
        from pathlib import Path

        s = Settings(siliconflow_api_key="test-key", upload_dir="/tmp/uploads")
        assert s.upload_path == Path("/tmp/uploads")

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("SILICONFLOW_API_KEY", "sk-test-env")
        monkeypatch.setenv("DEFAULT_TOP_K", "20")
        s = Settings()
        assert s.siliconflow_api_key == "sk-test-env"
        assert s.default_top_k == 20
