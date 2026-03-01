import logging

from tenacity import (
    RetryCallState,
    retry,
    retry_base,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.exceptions import EmbeddingError, RerankerError

logger = logging.getLogger(__name__)


class retry_if_rate_limit(retry_base):
    """Retry if the exception is an EmbeddingError or RerankerError containing '429'."""

    def __call__(self, retry_state: RetryCallState) -> bool:
        if retry_state.outcome is None or not retry_state.outcome.failed:
            return False
        exc = retry_state.outcome.exception()
        return isinstance(exc, (EmbeddingError, RerankerError)) and "429" in str(exc)


def retry_on_api_error(max_attempts: int = 3, min_wait: float = 1, max_wait: float = 10):
    """Retry decorator for external API calls with exponential backoff.

    Retries on network-level errors (timeout, connection) and HTTP 429 rate limit.
    """
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
        retry=retry_if_exception_type((TimeoutError, ConnectionError, OSError)) | retry_if_rate_limit(),
        before_sleep=lambda retry_state: logger.warning(
            f"Retry attempt {retry_state.attempt_number} after error: "
            f"{retry_state.outcome.exception()}"
        ),
    )


def retry_on_rate_limit(max_attempts: int = 5, min_wait: float = 2, max_wait: float = 30):
    """Retry decorator specifically for HTTP 429 rate limit errors with longer backoff."""
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=2, min=min_wait, max=max_wait),
        retry=retry_if_rate_limit(),
        before_sleep=lambda retry_state: logger.warning(
            f"Rate limit retry {retry_state.attempt_number} after: "
            f"{retry_state.outcome.exception()}"
        ),
    )
