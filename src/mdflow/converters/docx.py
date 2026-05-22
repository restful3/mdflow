"""docx -> Markdown via mammoth (semantic HTML) + markdownify.

mammoth maps Word styles to semantic HTML (headings, lists, tables,
bold/italic). Images are dropped: the image handler returns no attributes
so no base64 data URI is emitted, and markdownify strips any residual
<img>. No internal try/except — library errors propagate to
ConversionService.run_conversion (wrapped as CONVERSION_FAILED).
"""

from __future__ import annotations

import io
from typing import Any

import mammoth

from mdflow.converters._html_to_md import html_to_markdown
from mdflow.converters.base import (
    ConversionContext,
    ConversionResult,
    ProgressCallback,
)


class DocxConverter:
    name = "docx-mammoth"
    formats: tuple[str, ...] = ("docx",)
    requires_gpu = False

    def can_handle(self, ctx: ConversionContext) -> bool:
        return ctx.format in self.formats

    def convert(self, ctx: ConversionContext, progress: ProgressCallback) -> ConversionResult:
        progress("parse", 10)
        result = mammoth.convert_to_html(
            io.BytesIO(ctx.data),
            convert_image=mammoth.images.img_element(lambda image: {}),
        )
        progress("render", 60)
        markdown = html_to_markdown(result.value, strip_images=True)
        metadata: dict[str, Any] = {}
        warnings = [m.message for m in result.messages]
        if warnings:
            metadata["warnings"] = warnings
        progress("done", 100)
        return ConversionResult(markdown=markdown, metadata=metadata)
