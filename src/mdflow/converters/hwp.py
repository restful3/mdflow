"""hwp (HWP 5.0) -> Markdown via pyhwp in-process XHTML -> markdownify.

pyhwp opens the HWP OLE storage from a temp file path (no stable bytes
API), then HTMLTransform.transform_hwp5_to_xhtml emits a single XHTML
stream (UTF-8) which is converted to Markdown by the shared
html_to_markdown helper (images dropped: the single-file transform does
not extract bindata images, so refs would be broken; <style> CSS is
dropped by markdownify). LibreOffice cannot convert HWP 5.0 (its bundled
filter is HWP 3.0 only), so pyhwp is the engine.

pyhwp is an optional [hwp] extra and is lazy-imported inside
_hwp_to_xhtml: a missing pyhwp raises HWP_UNAVAILABLE, while pyhwp/lxml
parse errors propagate to ConversionService.run_conversion
(-> CONVERSION_FAILED). No internal try/except swallows conversion
errors.
"""

from __future__ import annotations

import io
import tempfile
from contextlib import closing
from pathlib import Path

from mdflow.converters._html_to_md import html_to_markdown
from mdflow.converters.base import (
    ConversionContext,
    ConversionResult,
    ProgressCallback,
)
from mdflow.core.errors import ErrorCode, MdflowError


class HwpConverter:
    name = "hwp-pyhwp"
    formats: tuple[str, ...] = ("hwp",)
    requires_gpu = False

    def can_handle(self, ctx: ConversionContext) -> bool:
        return ctx.format in self.formats

    def _hwp_to_xhtml(self, src_path: str) -> bytes:
        try:
            from hwp5.hwp5html import HTMLTransform
            from hwp5.xmlmodel import Hwp5File
        except ImportError as e:
            raise MdflowError(
                ErrorCode.HWP_UNAVAILABLE,
                "pyhwp not installed (pip install 'mdflow[hwp]')",
            ) from e
        buf = io.BytesIO()
        with closing(Hwp5File(src_path)) as hwp5:
            HTMLTransform().transform_hwp5_to_xhtml(hwp5, buf)
        return buf.getvalue()

    def convert(self, ctx: ConversionContext, progress: ProgressCallback) -> ConversionResult:
        progress("parse", 5)
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.hwp"
            src.write_bytes(ctx.data)
            xhtml_bytes = self._hwp_to_xhtml(str(src))
        progress("render", 60)
        html = xhtml_bytes.decode("utf-8", "replace")
        markdown = html_to_markdown(html, strip_images=True)
        progress("done", 100)
        return ConversionResult(
            markdown=markdown,
            metadata={"source_format": "hwp", "engine": "pyhwp"},
        )
