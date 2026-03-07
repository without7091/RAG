from pathlib import Path

from app.config import Settings


class TestSettings:
    def test_default_values(self):
        s = Settings(siliconflow_api_key="test-key", _env_file=None)
        assert s.embedding_url == "https://api.siliconflow.cn/v1/embeddings"
        assert s.embedding_model == "Qwen/Qwen3-Embedding-4B"
        assert s.reranker_url == "https://api.siliconflow.cn/v1/rerank"
        assert s.reranker_model == "Qwen/Qwen3-Reranker-4B"
        assert s.embedding_dimension == 2560
        assert s.sparse_embedding_mode == "local"
        assert s.default_top_k == 20
        assert s.default_top_n == 3
        assert s.chunk_size == 1024
        assert s.chunk_overlap == 128
        assert s.min_chunk_size == 50
        assert s.header_prefix_template == "[{path}]\n\n"
        assert s.header_separator == " > "
        assert s.max_upload_size_mb == 100

    def test_embedding_url_property(self):
        s = Settings(siliconflow_api_key="test-key", _env_file=None)
        assert s.embedding_url == "https://api.siliconflow.cn/v1/embeddings"

    def test_reranker_url_property(self):
        s = Settings(siliconflow_api_key="test-key", _env_file=None)
        assert s.reranker_url == "https://api.siliconflow.cn/v1/rerank"

    def test_upload_path_property(self):
        from pathlib import Path

        s = Settings(siliconflow_api_key="test-key", upload_dir="/tmp/uploads", _env_file=None)
        assert s.upload_path == Path("/tmp/uploads")

    def test_pipeline_worker_defaults(self):
        s = Settings(siliconflow_api_key="test-key", _env_file=None)
        assert s.pipeline_max_concurrency == 2
        assert s.pipeline_poll_interval == 2.0

    def test_pipeline_worker_from_env(self, monkeypatch):
        monkeypatch.setenv("SILICONFLOW_API_KEY", "test-key")
        monkeypatch.setenv("PIPELINE_MAX_CONCURRENCY", "4")
        monkeypatch.setenv("PIPELINE_POLL_INTERVAL", "5.0")
        s = Settings()
        assert s.pipeline_max_concurrency == 4
        assert s.pipeline_poll_interval == 5.0

    def test_bm25_defaults(self):
        s = Settings(siliconflow_api_key="test-key", _env_file=None)
        assert s.bm25_vocab_size == 1_048_576
        assert s.bm25_stopwords_path is None

    def test_sparse_model_default(self):
        s = Settings(siliconflow_api_key="test-key", _env_file=None)
        assert s.fastembed_model_name == "Qdrant/bm25"
        assert s.sparse_embedding_model == "Qdrant/bm25"

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("SILICONFLOW_API_KEY", "sk-test-env")
        monkeypatch.setenv("DEFAULT_TOP_K", "20")
        s = Settings()
        assert s.siliconflow_api_key == "sk-test-env"
        assert s.default_top_k == 20

    def test_env_file_path_is_absolute_and_points_to_backend(self):
        env_file = Path(Settings.model_config["env_file"])
        assert env_file.is_absolute()
        assert env_file.name == ".env"
        assert env_file.parent.name == "backend"
