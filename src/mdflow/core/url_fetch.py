"""URL fetch with PRD §5.0 / agreement §3.2 policy.

10 steps from the Claude–Codex agreement, in order:
  1. validate_url    — scheme http/https, host required, no userinfo
  2. drop fragment   — never used for fetch or cache key
  3. SSRF policy     — block loopback/private/link-local/multicast/
                       unspecified/reserved, IPv4 + IPv6 + metadata IP
                       (169.254.169.254). MDFLOW_ALLOW_PRIVATE_URLS
                       bypasses this for local-dev / closed-network.
  4. fixed UA + Accept; no user-supplied headers/cookies/auth in v1
  5. mdflow-managed redirects, per-hop validate + SSRF, max_redirects
  6. connect/read timeouts → URL_TIMEOUT (distinct from converter TIMEOUT)
  7. streaming bytes accumulation with max_bytes cap → URL_TOO_LARGE
  8. final status must be 2xx → URL_NON_2XX
  9. emit filename hint (Content-Disposition → URL path) for the
     downstream format detector
 10. return FetchResult with the request-level metadata bundle
"""

from __future__ import annotations

import datetime as _dt
import ipaddress
import socket
from collections.abc import Iterable
from dataclasses import dataclass, field
from urllib.parse import urlparse, urlunparse

import httpx

from mdflow.core.errors import ErrorCode, MdflowError


@dataclass
class UrlPolicy:
    allow_private_urls: bool
    max_redirects: int
    max_bytes: int
    connect_timeout_s: float
    read_timeout_s: float
    user_agent: str


@dataclass
class FetchResult:
    data: bytes
    source_url: str
    effective_url: str
    http_status: int
    content_type: str | None
    content_length: int
    content_disposition: str | None
    filename_hint: str | None
    fetched_at: str
    redirect_count: int
    fetch_warnings: list[str] = field(default_factory=list)


# ---------------- step 1: validate ----------------


def validate_url(url: str) -> None:
    try:
        parsed = urlparse(url)
    except ValueError as e:
        raise MdflowError(ErrorCode.URL_INVALID, f"unparseable URL: {e}") from e

    if parsed.scheme not in {"http", "https"}:
        raise MdflowError(ErrorCode.URL_INVALID, f"unsupported scheme: {parsed.scheme!r}")
    if not parsed.hostname:
        raise MdflowError(ErrorCode.URL_INVALID, "missing host")
    if parsed.username is not None or parsed.password is not None:
        raise MdflowError(ErrorCode.URL_INVALID, "userinfo not allowed in URL")
    # `parsed.port` is computed lazily and raises ValueError on
    # non-integer / out-of-range port. Catching it here keeps malformed
    # URLs from reaching httpx, which would surface them as
    # httpx.InvalidURL (not a RequestError subclass) and leak past our
    # error handling.
    try:
        _ = parsed.port
    except ValueError as e:
        raise MdflowError(ErrorCode.URL_INVALID, f"invalid port: {e}") from e


# ---------------- step 2: fragment ----------------


def _drop_fragment(url: str) -> str:
    p = urlparse(url)
    return urlunparse(p._replace(fragment=""))


# ---------------- step 3: SSRF ----------------

_IP = ipaddress.IPv4Address | ipaddress.IPv6Address


def _is_blocked_ip(ip: _IP) -> bool:
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    )


def _resolve_host(host: str) -> list[_IP]:
    """Resolve a host name to a list of IP addresses (blocking)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as e:
        raise MdflowError(ErrorCode.URL_FETCH_FAILED, f"DNS resolution failed: {e}") from e
    out: list[_IP] = []
    for _family, _, _, _, sockaddr in infos:
        try:
            out.append(ipaddress.ip_address(sockaddr[0]))
        except ValueError:
            continue
    return out


def _enforce_ssrf(url: str, policy: UrlPolicy) -> None:
    if policy.allow_private_urls:
        return
    parsed = urlparse(url)
    host = parsed.hostname or ""
    try:
        ips: Iterable[_IP] = [ipaddress.ip_address(host)]
    except ValueError:
        ips = _resolve_host(host)
    for ip in ips:
        if _is_blocked_ip(ip):
            raise MdflowError(
                ErrorCode.URL_BLOCKED,
                f"address {ip} for host {host!r} blocked by policy",
            )


# ---------------- step 9 helpers: filename hint ----------------


def _content_disposition_filename(header: str | None) -> str | None:
    if not header:
        return None
    for part in (p.strip() for p in header.split(";")):
        if part.lower().startswith("filename="):
            value = part.split("=", 1)[1].strip().strip('"')
            return value or None
    return None


def _filename_from_path(url: str) -> str | None:
    path = urlparse(url).path
    if not path or path.endswith("/"):
        return None
    return path.rsplit("/", 1)[-1]


# ---------------- main entry ----------------


def fetch_url(
    url: str,
    policy: UrlPolicy,
    *,
    transport: httpx.BaseTransport | None = None,
) -> FetchResult:
    source_url = _drop_fragment(url)
    validate_url(source_url)
    _enforce_ssrf(source_url, policy)

    timeout = httpx.Timeout(
        connect=policy.connect_timeout_s,
        read=policy.read_timeout_s,
        write=policy.read_timeout_s,
        pool=policy.connect_timeout_s,
    )
    headers = {"user-agent": policy.user_agent, "accept": "*/*"}
    fetched_at = _dt.datetime.now(_dt.UTC).isoformat().replace("+00:00", "Z")

    current = source_url
    redirects = 0

    with httpx.Client(transport=transport, timeout=timeout, follow_redirects=False) as client:
        while True:
            try:
                with client.stream("GET", current, headers=headers) as resp:
                    if resp.is_redirect:
                        if redirects >= policy.max_redirects:
                            raise MdflowError(
                                ErrorCode.URL_REDIRECT_LIMIT,
                                f"exceeded max_redirects={policy.max_redirects}",
                            )
                        location = resp.headers.get("location")
                        if not location:
                            raise MdflowError(
                                ErrorCode.URL_FETCH_FAILED,
                                "redirect without Location header",
                            )
                        next_url = _drop_fragment(str(resp.url.join(location)))
                        validate_url(next_url)
                        _enforce_ssrf(next_url, policy)
                        current = next_url
                        redirects += 1
                        continue

                    if not (200 <= resp.status_code < 300):
                        raise MdflowError(
                            ErrorCode.URL_NON_2XX,
                            f"non-2xx status: {resp.status_code}",
                        )

                    data = bytearray()
                    for chunk in resp.iter_bytes():
                        data.extend(chunk)
                        if len(data) > policy.max_bytes:
                            raise MdflowError(
                                ErrorCode.URL_TOO_LARGE,
                                f"response exceeded max_bytes={policy.max_bytes}",
                            )

                    cd = resp.headers.get("content-disposition")
                    filename_hint = _content_disposition_filename(cd)
                    if not filename_hint:
                        filename_hint = _filename_from_path(str(resp.url))

                    return FetchResult(
                        data=bytes(data),
                        source_url=source_url,
                        effective_url=str(resp.url),
                        http_status=resp.status_code,
                        content_type=resp.headers.get("content-type"),
                        content_length=len(data),
                        content_disposition=cd,
                        filename_hint=filename_hint,
                        fetched_at=fetched_at,
                        redirect_count=redirects,
                    )
            except httpx.TimeoutException as e:
                raise MdflowError(ErrorCode.URL_TIMEOUT, str(e)) from e
            except httpx.RequestError as e:
                raise MdflowError(ErrorCode.URL_FETCH_FAILED, str(e)) from e
