"""url_pipeline — helper that fetches a URL and feeds bytes into the service.

Implements URL handling agreement §3.7 — the conversion cache is bytes-based,
so the same bytes from two different URLs share one cache entry; each
response is composed with the *current* request's fetch metadata.
"""

from pathlib import Path

import httpx
import pytest

from mdflow.converters.text import TextConverter
from mdflow.core.cache import Cache
from mdflow.core.errors import ErrorCode, MdflowError
from mdflow.core.registry import Registry
from mdflow.core.service import ConversionService
from mdflow.core.url_fetch import UrlPolicy
from mdflow.core.url_pipeline import UrlConvertResponse, convert_from_url


def _policy() -> UrlPolicy:
    # allow_private_urls=True skips real DNS resolution in tests.
    return UrlPolicy(
        allow_private_urls=True,
        max_redirects=3,
        max_bytes=4096,
        connect_timeout_s=1.0,
        read_timeout_s=1.0,
        user_agent="mdflow-test/0.0",
    )


@pytest.fixture
def service(tmp_cache_dir: Path) -> ConversionService:
    reg = Registry()
    reg.register(TextConverter())
    return ConversionService(registry=reg, cache=Cache(tmp_cache_dir))


def test_convert_from_url_returns_response_and_fetch_metadata(service):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            content=b"hello mdflow",
        )

    out = convert_from_url(
        "https://example.com/x.txt",
        policy=_policy(),
        service=service,
        transport=httpx.MockTransport(handler),
    )
    assert isinstance(out, UrlConvertResponse)
    assert out.response.cached is False
    assert out.response.result.markdown == "hello mdflow"
    assert out.response.detected_format == "txt"
    assert out.fetch["input_kind"] == "url"
    assert out.fetch["source_url"] == "https://example.com/x.txt"
    assert out.fetch["effective_url"] == "https://example.com/x.txt"
    assert out.fetch["http_status"] == 200
    assert out.fetch["content_type"] == "text/plain"
    assert out.fetch["content_length"] == len(b"hello mdflow")
    assert out.fetch["filename_hint"] == "x.txt"
    assert out.fetch["redirect_count"] == 0
    assert out.fetch["fetched_at"].endswith("Z")


def test_convert_from_url_filename_hint_drives_format_detect(service):
    """Step 9: Content-Disposition filename hint reaches format detection."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "content-type": "application/octet-stream",
                "content-disposition": 'attachment; filename="notes.md"',
            },
            content=b"# Hello",
        )

    out = convert_from_url(
        "https://example.com/download",
        policy=_policy(),
        service=service,
        transport=httpx.MockTransport(handler),
    )
    assert out.response.detected_format == "md"
    assert out.fetch["filename_hint"] == "notes.md"
    assert out.response.result.markdown == "# Hello"


def test_same_bytes_from_two_urls_share_cache_but_distinct_fetch_metadata(service):
    """Agreement §3.7: bytes-keyed cache + request-level fetch composition."""
    shared = b"same content from two urls"

    def make_handler():
        def h(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=shared, headers={"content-type": "text/plain"})

        return h

    first = convert_from_url(
        "https://a.example.com/x.txt",
        policy=_policy(),
        service=service,
        transport=httpx.MockTransport(make_handler()),
    )
    second = convert_from_url(
        "https://b.example.com/y.txt",
        policy=_policy(),
        service=service,
        transport=httpx.MockTransport(make_handler()),
    )

    assert first.response.cached is False
    assert second.response.cached is True
    assert first.response.sha256 == second.response.sha256
    assert first.response.result.markdown == second.response.result.markdown

    # Each response reflects its own URL, not the URL that seeded the cache.
    assert first.fetch["source_url"] == "https://a.example.com/x.txt"
    assert second.fetch["source_url"] == "https://b.example.com/y.txt"
    assert first.fetch["source_url"] != second.fetch["source_url"]


def test_url_validation_failure_propagates_before_service_is_called(service):
    """validate_url runs inside fetch_url; service must not see the request."""
    with pytest.raises(MdflowError) as exc:
        convert_from_url(
            "file:///etc/passwd",
            policy=_policy(),
            service=service,
        )
    assert exc.value.code is ErrorCode.URL_INVALID


def test_content_type_alone_drives_format_when_no_filename_hint(service):
    """Codex blocker #2 slice 3 (2026-05-22): URL fetch with a path
    that yields no filename, no Content-Disposition, and indeterminate
    magic must still resolve via the agreement §3.2 step 9 hint chain:
    magic > Content-Type > Content-Disposition filename > URL path.
    """

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/plain; charset=utf-8"},
            content=b"plain text body\n",
        )

    out = convert_from_url(
        "https://example.com/",
        policy=_policy(),
        service=service,
        transport=httpx.MockTransport(handler),
    )
    assert out.fetch["filename_hint"] is None
    assert out.fetch["content_type"] == "text/plain; charset=utf-8"
    assert out.response.detected_format == "txt"
    assert out.response.converter_name == "text-passthrough"
    assert out.response.result.markdown == "plain text body\n"


def test_options_flow_into_cache_key(service):
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"hi", headers={"content-type": "text/plain"})

    a = convert_from_url(
        "https://example.com/x.txt",
        policy=_policy(),
        service=service,
        options={"k": 1},
        transport=httpx.MockTransport(handler),
    )
    b = convert_from_url(
        "https://example.com/x.txt",
        policy=_policy(),
        service=service,
        options={"k": 2},
        transport=httpx.MockTransport(handler),
    )
    assert a.response.sha256 != b.response.sha256
    assert a.response.cached is False
    assert b.response.cached is False
