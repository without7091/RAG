import logging
import re

import httpx
from tenacity import (
    RetryCallState,
    retry,
    retry_base,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

from app.exceptions import EmbeddingError, QueryRewriteError, RerankerError

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {429, 502, 503, 504}
_STATUS_CODE_PATTERN = re.compile(r"\b([1-5]\d{2})\b")
_UPSTREAM_ERRORS = (EmbeddingError, RerankerError, QueryRewriteError)
_NETWORK_RETRYABLE_ERRORS = (
    TimeoutError,
    ConnectionError,
    OSError,
    httpx.TimeoutException,
    httpx.NetworkError,
)


def is_retryable_status_code(status_code: int | None) -> bool:
    return status_code in RETRYABLE_STATUS_CODES


def get_api_error_status_code(exc: BaseException) -> int | None:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code

    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code

    match = _STATUS_CODE_PATTERN.search(str(exc))
    if match is None:
        return None
    return int(match.group(1))


def get_api_error_upstream(exc: BaseException) -> str:
    upstream = getattr(exc, "upstream", None)
    if isinstance(upstream, str) and upstream:
        return upstream

    if isinstance(exc, EmbeddingError):
        return "embedding"
    if isinstance(exc, RerankerError):
        return "reranker"
    if isinstance(exc, QueryRewriteError):
        return "query_rewrite"
    return "upstream"


def is_timeout_api_exception(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return True
    return "timeout" in str(exc).lower()


def is_retryable_api_exception(exc: BaseException) -> bool:
    if isinstance(exc, _NETWORK_RETRYABLE_ERRORS):
        return True

    if isinstance(exc, httpx.HTTPStatusError):
        return is_retryable_status_code(exc.response.status_code)

    if isinstance(exc, _UPSTREAM_ERRORS):
        retryable = getattr(exc, "retryable", None)
        if retryable is not None:
            return retryable
        return is_retryable_status_code(get_api_error_status_code(exc))

    return False


class RetryIfApiError(retry_base):
    """Retry transient upstream API failures."""

    def __call__(self, retry_state: RetryCallState) -> bool:
        if retry_state.outcome is None or not retry_state.outcome.failed:
            return False
        exc = retry_state.outcome.exception()
        return exc is not None and is_retryable_api_exception(exc)


def _log_retry_before_sleep(retry_state: RetryCallState, max_attempts: int) -> None:
    exc = retry_state.outcome.exception() if retry_state.outcome is not None else None
    if exc is None:
        return
    logger.warning(
        "Retrying upstream API call (attempt=%d/%d, upstream=%s, status_code=%s, retryable=%s): %s",
        retry_state.attempt_number,
        max_attempts,
        get_api_error_upstream(exc),
        get_api_error_status_code(exc),
        is_retryable_api_exception(exc),
        exc,
    )


def retry_on_api_error(
    max_attempts: int = 3,
    min_wait: float = 1,
    max_wait: float = 10,
    jitter_max: float = 1,
):
    """Retry decorator for transient upstream API failures."""
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait) + wait_random(0, jitter_max),
        retry=RetryIfApiError(),
        before_sleep=lambda retry_state: _log_retry_before_sleep(retry_state, max_attempts),
        reraise=True,
    )


def retry_on_rate_limit(max_attempts: int = 5, min_wait: float = 2, max_wait: float = 30):
    """Retry decorator specifically for retryable upstream rate limit errors."""
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=2, min=min_wait, max=max_wait) + wait_random(0, 1),
        retry=RetryIfApiError(),
        before_sleep=lambda retry_state: _log_retry_before_sleep(retry_state, max_attempts),
        reraise=True,
    )
