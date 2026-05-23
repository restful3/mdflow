"""Shared composition root for the converter registry and URL policy.

Both the HTTP app lifespan (api/app.py) and the MCP server (mcp/server.py)
build their runtime from here, so the registered converter set and the URL
policy mapping cannot drift between the two transports.
"""

from __future__ import annotations

from mdflow.converters.docx import DocxConverter
from mdflow.converters.html import HtmlConverter
from mdflow.converters.hwp import HwpConverter
from mdflow.converters.marker import MarkerConverter
from mdflow.converters.office import LibreOfficeConverter
from mdflow.converters.pdf import PdfConverter
from mdflow.converters.pptx import PptxConverter
from mdflow.converters.spreadsheet import XlsxConverter
from mdflow.converters.text import TextConverter
from mdflow.core.registry import Registry
from mdflow.core.url_fetch import UrlPolicy
from mdflow.settings import Settings


def build_registry(settings: Settings, *, allow_gpu: bool = True) -> Registry:
    """Register every converter in dispatch order (first-wins per format).

    `allow_gpu=False` omits any `requires_gpu=True` converter. The
    HTTP-mounted MCP uses this to skip MarkerConverter so two
    transports in the same FastAPI process cannot concurrently load
    Marker (the `/convert` SSE path holds `gpu_semaphore`, but a
    request to `/mcp` would otherwise bypass it).
    """
    registry = Registry()
    registry.register(TextConverter())
    registry.register(DocxConverter())
    registry.register(PptxConverter())
    registry.register(XlsxConverter())
    registry.register(HtmlConverter())
    # Marker(GPU) precedes PyMuPDF(CPU) for `pdf`; first-wins + can_handle
    # gating routes to Marker only when GPU+marker-pdf are available.
    if allow_gpu:
        registry.register(MarkerConverter())
    registry.register(PdfConverter())
    registry.register(LibreOfficeConverter(timeout_s=settings.soffice_timeout_s))
    registry.register(HwpConverter())
    return registry


def url_policy_from_settings(settings: Settings) -> UrlPolicy:
    """Map the 6 URL-related MDFLOW_* settings onto a UrlPolicy.

    max_url_input_mb is megabytes; UrlPolicy.max_bytes is bytes.
    """
    return UrlPolicy(
        allow_private_urls=settings.allow_private_urls,
        max_redirects=settings.url_max_redirects,
        max_bytes=settings.max_url_input_mb * 1024 * 1024,
        connect_timeout_s=settings.url_connect_timeout_s,
        read_timeout_s=settings.url_read_timeout_s,
        user_agent=settings.url_user_agent,
    )
