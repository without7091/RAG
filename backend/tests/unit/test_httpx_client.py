import httpx

from app.config import Settings
from app.core.httpx_client import build_httpx_timeout, build_query_rewrite_timeout


def _assert_timeout(
    timeout: httpx.Timeout,
    *,
    connect: float,
    read: float,
    write: float,
    pool: float,
) -> None:
    assert timeout.connect == connect
    assert timeout.read == read
    assert timeout.write == write
    assert timeout.pool == pool


def test_build_httpx_timeout_from_settings():
    settings = Settings(
        http_connect_timeout_s=11,
        http_read_timeout_s=181,
        http_write_timeout_s=182,
        http_pool_timeout_s=31,
        _env_file=None,
    )

    timeout = build_httpx_timeout(settings)

    _assert_timeout(timeout, connect=11, read=181, write=182, pool=31)


def test_build_query_rewrite_timeout_uses_split_settings():
    settings = Settings(
        query_rewrite_timeout_ms=15_000,
        query_rewrite_connect_timeout_s=4,
        query_rewrite_read_timeout_s=20,
        query_rewrite_write_timeout_s=21,
        query_rewrite_pool_timeout_s=9,
        _env_file=None,
    )

    timeout = build_query_rewrite_timeout(settings)

    _assert_timeout(timeout, connect=4, read=20, write=21, pool=9)


def test_build_query_rewrite_timeout_falls_back_to_legacy_ms():
    settings = Settings(
        query_rewrite_timeout_ms=18_000,
        query_rewrite_connect_timeout_s=5,
        query_rewrite_read_timeout_s=None,
        query_rewrite_write_timeout_s=None,
        query_rewrite_pool_timeout_s=10,
        _env_file=None,
    )

    timeout = build_query_rewrite_timeout(settings)

    _assert_timeout(timeout, connect=5, read=18, write=18, pool=10)
