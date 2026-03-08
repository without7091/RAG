import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[3] / "manual_retrieve_test.py"
SPEC = importlib.util.spec_from_file_location("manual_retrieve_test", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None

manual_retrieve_test = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manual_retrieve_test)


def test_default_base_url_points_to_backend_directly():
    assert manual_retrieve_test.DEFAULT_BASE_URL == "http://localhost:8000/api/v1/retrieve"


def test_resolve_retrieve_url_accepts_backend_root():
    assert (
        manual_retrieve_test.resolve_retrieve_url("http://localhost:8000")
        == "http://localhost:8000/api/v1/retrieve"
    )


def test_resolve_retrieve_url_accepts_api_prefix():
    assert (
        manual_retrieve_test.resolve_retrieve_url("http://localhost:8000/api/v1")
        == "http://localhost:8000/api/v1/retrieve"
    )


def test_build_connection_hint_for_frontend_proxy():
    hint = manual_retrieve_test.build_connection_hint("http://localhost:3000/api/v1/retrieve")
    assert hint is not None
    assert "前端 3000" in hint


def test_should_bypass_proxy_for_local_backend():
    assert manual_retrieve_test.should_bypass_proxy("http://localhost:8000/api/v1/retrieve")
    assert manual_retrieve_test.should_bypass_proxy("http://127.0.0.1:8000/api/v1/retrieve")


def test_should_not_bypass_proxy_for_remote_host():
    assert not manual_retrieve_test.should_bypass_proxy("https://example.com/api/v1/retrieve")
