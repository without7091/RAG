from app.exceptions import EmbeddingError, QueryRewriteError, RerankerError
from app.utils.retry import is_retryable_api_exception, is_retryable_status_code


def test_retryable_status_codes_are_classified():
    assert is_retryable_status_code(429) is True
    assert is_retryable_status_code(502) is True
    assert is_retryable_status_code(503) is True
    assert is_retryable_status_code(504) is True
    assert is_retryable_status_code(400) is False
    assert is_retryable_status_code(422) is False


def test_retryable_business_errors_are_detected():
    assert is_retryable_api_exception(
        EmbeddingError(
            "Embedding API returned 503",
            status_code=503,
            retryable=True,
            upstream="embedding",
        )
    )
    assert is_retryable_api_exception(
        RerankerError(
            "Reranker API returned 429",
            status_code=429,
            retryable=True,
            upstream="reranker",
        )
    )
    assert is_retryable_api_exception(
        QueryRewriteError(
            "Query rewrite API timeout",
            retryable=True,
            upstream="query_rewrite",
        )
    )


def test_non_retryable_business_errors_are_ignored():
    assert not is_retryable_api_exception(
        EmbeddingError(
            "Embedding API returned 400",
            status_code=400,
            retryable=False,
            upstream="embedding",
        )
    )
    assert not is_retryable_api_exception(
        QueryRewriteError(
            "Chat completion did not return valid JSON",
            retryable=False,
            upstream="query_rewrite",
        )
    )


def test_timeout_error_is_retryable():
    assert is_retryable_api_exception(TimeoutError("upstream timeout"))
