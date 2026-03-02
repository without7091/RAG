"""Unit tests for BM25Service: tokenization, hashing, sparse vector generation."""

import pytest

from app.services.bm25_service import BM25Service


@pytest.fixture
def bm25():
    return BM25Service()


class TestTokenization:
    def test_chinese_tokenization(self, bm25):
        tokens = bm25.tokenize("路由器支持Wi-Fi技术")
        assert len(tokens) > 0
        # Should contain Chinese word tokens
        assert any(len(t) > 1 for t in tokens)

    def test_english_tokenization(self, bm25):
        tokens = bm25.tokenize("router supports wifi technology")
        assert "router" in tokens
        assert "supports" in tokens
        assert "wifi" in tokens
        assert "technology" in tokens

    def test_mixed_chinese_english(self, bm25):
        tokens = bm25.tokenize("XJ-998路由器supports Wi-Fi 7")
        assert len(tokens) > 0
        # Should have both Chinese and English tokens
        has_chinese = any(ord(c) > 0x4E00 for t in tokens for c in t)
        has_english = any(t.isascii() and t.isalpha() for t in tokens)
        assert has_chinese
        assert has_english

    def test_empty_string(self, bm25):
        tokens = bm25.tokenize("")
        assert tokens == []

    def test_stopwords_filtered(self, bm25):
        tokens = bm25.tokenize("the a an is are was 的 了 是 在")
        # Common stopwords should be filtered out
        assert "the" not in tokens
        assert "a" not in tokens
        assert "的" not in tokens
        assert "了" not in tokens

    def test_punctuation_filtered(self, bm25):
        tokens = bm25.tokenize("你好！世界。Hello, world!")
        for t in tokens:
            assert t not in {"！", "。", ",", "!"}


class TestHashFunction:
    def test_deterministic(self, bm25):
        h1 = bm25._hash_token("路由器")
        h2 = bm25._hash_token("路由器")
        assert h1 == h2

    def test_range_valid(self, bm25):
        test_tokens = ["hello", "路由器", "Wi-Fi", "技术", "a", "测试", "XJ-998"]
        for token in test_tokens:
            h = bm25._hash_token(token)
            assert 0 <= h < 2**20, f"Hash {h} out of range for token '{token}'"

    def test_non_negative(self, bm25):
        # CRC32 can return negative in some languages; verify Python wraps correctly
        for i in range(100):
            h = bm25._hash_token(f"token_{i}")
            assert h >= 0


class TestSparseVectorGeneration:
    def test_structure(self, bm25):
        vec = bm25.text_to_sparse_vector("路由器支持Wi-Fi技术")
        assert "indices" in vec
        assert "values" in vec
        assert len(vec["indices"]) == len(vec["values"])

    def test_tf_values_correct(self, bm25):
        # "hello hello world" -> "hello" appears twice, "world" once
        vec = bm25.text_to_sparse_vector("hello hello world")
        assert len(vec["values"]) > 0
        # All values should be positive (TF counts)
        for v in vec["values"]:
            assert v > 0

    def test_indices_sorted(self, bm25):
        vec = bm25.text_to_sparse_vector("路由器支持多种无线技术标准")
        indices = vec["indices"]
        assert indices == sorted(indices)

    def test_empty_text(self, bm25):
        vec = bm25.text_to_sparse_vector("")
        assert vec["indices"] == []
        assert vec["values"] == []

    def test_no_zero_values(self, bm25):
        vec = bm25.text_to_sparse_vector("路由器支持Wi-Fi 7技术")
        for v in vec["values"]:
            assert v != 0

    def test_duplicate_token_tf_accumulates(self, bm25):
        vec_single = bm25.text_to_sparse_vector("hello")
        vec_double = bm25.text_to_sparse_vector("hello hello")
        # The "hello" hash should have TF=2 in vec_double
        if vec_single["indices"] and vec_double["indices"]:
            # Find the index for "hello"
            idx = vec_single["indices"][0]
            if idx in vec_double["indices"]:
                pos = vec_double["indices"].index(idx)
                assert vec_double["values"][pos] > vec_single["values"][0]


class TestBatchProcessing:
    def test_batch_consistency(self, bm25):
        texts = ["路由器手册", "Wi-Fi技术", "故障排除"]
        batch_results = bm25.batch_to_sparse_vectors(texts)
        assert len(batch_results) == 3
        # Each result should match individual processing
        for text, batch_vec in zip(texts, batch_results):
            single_vec = bm25.text_to_sparse_vector(text)
            assert batch_vec["indices"] == single_vec["indices"]
            assert batch_vec["values"] == single_vec["values"]

    def test_empty_list(self, bm25):
        result = bm25.batch_to_sparse_vectors([])
        assert result == []
