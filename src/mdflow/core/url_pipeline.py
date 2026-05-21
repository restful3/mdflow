"""url_pipeline — fetch a URL and feed the bytes into ConversionService.

Implements URL handling agreement §3.7 + PRD §5.0:
- the conversion cache key is bytes+options (NOT the URL); two
  different URLs that return the same payload share one cache entry
- on every URL request, including cache hits, the response is composed
  with the *current* request's fetch metadata (source_url,
  effective_url, http_status, ...) so provenance is request-level

Layered so that `ConversionService` itself stays bytes-in / response-out;
the HTTP layer (Task 14) calls this helper for {url} requests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from mdflow.core.service import (
    ConversionService,
    ConvertRequest,
    ConvertResponse,
    ProgressCallback,
    _noop_progress,
)
from mdflow.core.url_fetch import FetchResult, UrlPolicy, fetch_url


@dataclass
class UrlConvertResponse:
    """ConvertResponse plus the request-level fetch metadata bundle."""

    response: ConvertResponse
    fetch: dict[str, Any]


def _fetch_metadata(fetched: FetchResult) -> dict[str, Any]:
    return {
        "input_kind": "url",
        "source_url": fetched.source_url,
        "effective_url": fetched.effective_url,
        "http_status": fetched.http_status,
        "content_type": fetched.content_type,
        "content_length": fetched.content_length,
        "content_disposition": fetched.content_disposition,
        "filename_hint": fetched.filename_hint,
        "fetched_at": fetched.fetched_at,
        "redirect_count": fetched.redirect_count,
        "fetch_warnings": list(fetched.fetch_warnings),
    }


def convert_from_url(
    url: str,
    *,
    policy: UrlPolicy,
    service: ConversionService,
    options: dict[str, Any] | None = None,
    progress: ProgressCallback = _noop_progress,
    transport: httpx.BaseTransport | None = None,
) -> UrlConvertResponse:
    fetched = fetch_url(url, policy, transport=transport)
    req = ConvertRequest(
        data=fetched.data,
        filename_hint=fetched.filename_hint,
        options=options or {},
        content_type_hint=fetched.content_type,
    )
    response = service.convert(req, progress=progress)
    return UrlConvertResponse(response=response, fetch=_fetch_metadata(fetched))
