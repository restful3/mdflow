"""URL fetch helper — implements agreement §3.2 (10 steps).

Mapping (test name -> agreement step):
- validate_url_*                        : step 1
- fragment_dropped_*                    : step 2
- _is_blocked_ip / pre_connect / *_redirect_to_private : step 3
- fixed_user_agent                      : step 4
- redirect_followed / redirect_limit    : step 5
- timeout                               : step 6
- size_cap                              : step 7
- non_2xx                               : step 8
- content_disposition_filename / filename_from_path : step 9 (hints)
- fetch_result_fields                   : step 10 (metadata surface)
"""

import ipaddress
from unittest.mock import patch

import httpx
import pytest

from mdflow.core.errors import ErrorCode, MdflowError
from mdflow.core.url_fetch import (
    FetchResult,
    UrlPolicy,
    _is_blocked_ip,
    fetch_url,
    validate_url,
)


def _policy(
    *,
    allow_private: bool = False,
    max_redirects: int = 3,
    max_bytes: int = 1024,
    connect_timeout_s: float = 1.0,
    read_timeout_s: float = 1.0,
    user_agent: str = "mdflow-test/0.0",
) -> UrlPolicy:
    return UrlPolicy(
        allow_private_urls=allow_private,
        max_redirects=max_redirects,
        max_bytes=max_bytes,
        connect_timeout_s=connect_timeout_s,
        read_timeout_s=read_timeout_s,
        user_agent=user_agent,
    )


# -------- step 1: validate_url --------


def test_validate_url_accepts_http_and_https():
    validate_url("http://example.com/x")
    validate_url("https://example.com/x")


@pytest.mark.parametrize(
    "bad",
    [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "gopher://x/",
        "javascript:alert(1)",
        "data:text/plain,foo",
    ],
)
def test_validate_url_rejects_unsupported_scheme(bad):
    with pytest.raises(MdflowError) as exc:
        validate_url(bad)
    assert exc.value.code is ErrorCode.URL_INVALID


def test_validate_url_rejects_missing_host():
    with pytest.raises(MdflowError) as exc:
        validate_url("https:///path")
    assert exc.value.code is ErrorCode.URL_INVALID


def test_validate_url_rejects_userinfo():
    with pytest.raises(MdflowError) as exc:
        validate_url("https://user:pw@example.com/")
    assert exc.value.code is ErrorCode.URL_INVALID


@pytest.mark.parametrize(
    "bad",
    [
        "https://example.com:bad/path",  # non-integer port
        "https://example.com:-1/path",  # negative port
        "https://example.com:99999/path",  # port out of valid range
    ],
)
def test_validate_url_rejects_malformed_port(bad):
    """Codex blocker #3 (2026-05-21): urlparse accepts these but
    `parsed.port` raises ValueError. If we don't surface it here, httpx
    later raises `httpx.InvalidURL` (NOT a subclass of RequestError) and
    leaks past fetch_url's catch as a raw exception.
    """
    with pytest.raises(MdflowError) as exc:
        validate_url(bad)
    assert exc.value.code is ErrorCode.URL_INVALID


# -------- step 2: fragment dropped --------


def test_fragment_dropped_from_source_url():
    def handler(request: httpx.Request) -> httpx.Response:
        # Fragment never leaves the client per HTTP spec; verify regardless.
        assert "#" not in str(request.url)
        return httpx.Response(200, content=b"ok")

    transport = httpx.MockTransport(handler)
    res = fetch_url("https://example.com/x#section", _policy(), transport=transport)
    assert "#" not in res.source_url
    assert res.source_url.endswith("/x")


# -------- step 3: SSRF policy --------


@pytest.mark.parametrize(
    "addr",
    [
        "127.0.0.1",  # loopback v4
        "10.0.0.5",  # private v4
        "192.168.1.1",  # private v4
        "172.16.0.1",  # private v4
        "169.254.169.254",  # link-local / cloud metadata
        "224.0.0.1",  # multicast v4
        "0.0.0.0",  # unspecified v4
        "::1",  # loopback v6
        "fd00::1",  # private v6 (ULA)
        "fe80::1",  # link-local v6
        "ff00::1",  # multicast v6
    ],
)
def test_is_blocked_ip_for_unsafe_addresses(addr):
    assert _is_blocked_ip(ipaddress.ip_address(addr)) is True


@pytest.mark.parametrize("addr", ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"])
def test_is_blocked_ip_allows_public(addr):
    assert _is_blocked_ip(ipaddress.ip_address(addr)) is False


def test_fetch_blocks_private_host_before_connect():
    """If DNS resolves to a private IP, fetch must refuse before any HTTP send."""
    with patch("mdflow.core.url_fetch._resolve_host") as resolve:
        resolve.return_value = [ipaddress.ip_address("10.0.0.5")]
        with pytest.raises(MdflowError) as exc:
            fetch_url("https://internal.example.com/", _policy())
    assert exc.value.code is ErrorCode.URL_BLOCKED


def test_allow_private_urls_bypasses_ssrf():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"ok")

    with patch("mdflow.core.url_fetch._resolve_host") as resolve:
        resolve.return_value = [ipaddress.ip_address("10.0.0.5")]
        res = fetch_url(
            "https://internal.example.com/",
            _policy(allow_private=True),
            transport=httpx.MockTransport(handler),
        )
    assert res.data == b"ok"


def test_redirect_to_private_is_blocked_per_hop():
    """Step 3 + 5: per-hop SSRF check rejects mid-chain private redirect."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "example.com":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})
        return httpx.Response(200, content=b"leaked")  # must not be reached

    with pytest.raises(MdflowError) as exc:
        fetch_url(
            "https://example.com/r",
            _policy(),
            transport=httpx.MockTransport(handler),
        )
    assert exc.value.code is ErrorCode.URL_BLOCKED


# -------- step 4: fixed UA + Accept, no user headers --------


def test_fixed_user_agent_and_accept_header_sent():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["ua"] = request.headers.get("user-agent", "")
        seen["accept"] = request.headers.get("accept", "")
        return httpx.Response(200, content=b"x")

    fetch_url(
        "https://example.com/",
        _policy(user_agent="mdflow/0.0"),
        transport=httpx.MockTransport(handler),
    )
    assert seen["ua"] == "mdflow/0.0"
    assert seen["accept"] == "*/*"


# -------- step 5: redirect with hop count --------


def test_redirect_followed_and_counted():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/from":
            return httpx.Response(302, headers={"location": "https://example.com/to"})
        return httpx.Response(200, content=b"ok")

    res = fetch_url(
        "https://example.com/from",
        _policy(max_redirects=3),
        transport=httpx.MockTransport(handler),
    )
    assert res.data == b"ok"
    assert res.effective_url.endswith("/to")
    assert res.redirect_count == 1


def test_redirect_limit_exceeded_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        return httpx.Response(302, headers={"location": f"https://example.com{path}-x"})

    with pytest.raises(MdflowError) as exc:
        fetch_url(
            "https://example.com/loop",
            _policy(max_redirects=2),
            transport=httpx.MockTransport(handler),
        )
    assert exc.value.code is ErrorCode.URL_REDIRECT_LIMIT


# -------- step 6: timeout --------


def test_timeout_raises_url_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated", request=request)

    with pytest.raises(MdflowError) as exc:
        fetch_url(
            "https://example.com/slow",
            _policy(),
            transport=httpx.MockTransport(handler),
        )
    assert exc.value.code is ErrorCode.URL_TIMEOUT


# -------- step 7: size cap --------


def test_size_cap_aborts_when_response_exceeds_limit():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 4096)

    with pytest.raises(MdflowError) as exc:
        fetch_url(
            "https://example.com/big",
            _policy(max_bytes=1024),
            transport=httpx.MockTransport(handler),
        )
    assert exc.value.code is ErrorCode.URL_TOO_LARGE


# -------- step 8: non-2xx --------


@pytest.mark.parametrize("status", [301, 400, 403, 404, 500, 503])
def test_non_2xx_status_raises_when_not_a_redirect(status):
    if status in {301, 302, 303, 307, 308}:
        pytest.skip("redirect status — handled by step 5")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=b"")

    with pytest.raises(MdflowError) as exc:
        fetch_url(
            "https://example.com/",
            _policy(),
            transport=httpx.MockTransport(handler),
        )
    assert exc.value.code is ErrorCode.URL_NON_2XX


# -------- step 9: filename hints --------


def test_filename_hint_from_content_disposition():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "content-type": "application/pdf",
                "content-disposition": 'attachment; filename="report.pdf"',
            },
            content=b"%PDF-1.4",
        )

    res = fetch_url(
        "https://example.com/download",
        _policy(),
        transport=httpx.MockTransport(handler),
    )
    assert res.filename_hint == "report.pdf"
    assert res.content_disposition.startswith("attachment")


def test_filename_hint_from_url_path_when_no_disposition():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x")

    res = fetch_url(
        "https://example.com/some/path/report.docx",
        _policy(),
        transport=httpx.MockTransport(handler),
    )
    assert res.filename_hint == "report.docx"


def test_filename_hint_none_when_path_ends_in_slash():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x")

    res = fetch_url(
        "https://example.com/dir/",
        _policy(),
        transport=httpx.MockTransport(handler),
    )
    assert res.filename_hint is None


# -------- step 10: FetchResult surface --------


def test_fetch_result_carries_all_metadata_fields():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            content=b"hello",
        )

    res = fetch_url(
        "https://example.com/x",
        _policy(),
        transport=httpx.MockTransport(handler),
    )
    assert isinstance(res, FetchResult)
    assert res.data == b"hello"
    assert res.source_url == "https://example.com/x"
    assert res.effective_url == "https://example.com/x"
    assert res.http_status == 200
    assert res.content_type == "text/plain"
    assert res.content_length == len(b"hello")
    assert res.content_disposition is None
    assert res.filename_hint == "x"
    assert res.fetched_at.endswith("Z")
    assert res.redirect_count == 0
    assert res.fetch_warnings == []
