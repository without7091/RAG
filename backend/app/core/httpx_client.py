import httpx

from app.config import Settings, get_settings

_client: httpx.AsyncClient | None = None


def _build_timeout(*, connect: float, read: float, write: float, pool: float) -> httpx.Timeout:
    return httpx.Timeout(connect=connect, read=read, write=write, pool=pool)


def build_httpx_timeout(settings: Settings | None = None) -> httpx.Timeout:
    settings = settings or get_settings()
    return _build_timeout(
        connect=settings.http_connect_timeout_s,
        read=settings.http_read_timeout_s,
        write=settings.http_write_timeout_s,
        pool=settings.http_pool_timeout_s,
    )


def build_query_rewrite_timeout(settings: Settings | None = None) -> httpx.Timeout:
    settings = settings or get_settings()
    legacy_timeout_s = settings.query_rewrite_timeout_ms / 1000
    return _build_timeout(
        connect=settings.query_rewrite_connect_timeout_s,
        read=(
            settings.query_rewrite_read_timeout_s
            if settings.query_rewrite_read_timeout_s is not None
            else legacy_timeout_s
        ),
        write=(
            settings.query_rewrite_write_timeout_s
            if settings.query_rewrite_write_timeout_s is not None
            else legacy_timeout_s
        ),
        pool=settings.query_rewrite_pool_timeout_s,
    )


async def get_httpx_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=build_httpx_timeout(),
            proxy=None,
            trust_env=False,
        )
    return _client


async def close_httpx_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None
