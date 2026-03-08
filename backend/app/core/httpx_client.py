import httpx

_client: httpx.AsyncClient | None = None


async def get_httpx_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0),
            proxy=None,  # Bypass system proxy to avoid auth header issues
            trust_env=False,
        )
    return _client


async def close_httpx_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None
