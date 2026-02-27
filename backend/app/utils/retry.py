import logging

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


def retry_on_api_error(max_attempts: int = 3, min_wait: float = 1, max_wait: float = 10):
    """Retry decorator for external API calls with exponential backoff."""
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
        retry=retry_if_exception_type((TimeoutError, ConnectionError, OSError)),
        before_sleep=lambda retry_state: logger.warning(
            f"Retry attempt {retry_state.attempt_number} after error: "
            f"{retry_state.outcome.exception()}"
        ),
    )
