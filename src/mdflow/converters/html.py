"""html -> Markdown via trafilatura (boilerplate removal), with a
markdownify fallback when no article body is detected.

trafilatura.extract removes nav/footer/ad boilerplate and emits Markdown.
When it returns None (no article-like content), fall back to parsing the
<body> (or whole doc) with BeautifulSoup and converting via the shared
html_to_markdown helper. Images are excluded from the trafilatura path.
Input bytes are decoded with the TextConverter decode logic. No internal
try/except.
"""

from __future__ import annotations

import trafilatura
from bs4 import BeautifulSoup

from mdflow.converters._html_to_md import html_to_markdown
from mdflow.converters.base import (
    ConversionContext,
    ConversionResult,
    ProgressCallback,
)
from mdflow.converters.text import _decode


class HtmlConverter:
    name = "html-trafilatura"
    formats: tuple[str, ...] = ("html",)
    requires_gpu = False

    def can_handle(self, ctx: ConversionContext) -> bool:
        return ctx.format in self.formats

    def convert(self, ctx: ConversionContext, progress: ProgressCallback) -> ConversionResult:
        progress("parse", 10)
        html_str, _ = _decode(ctx.data)
        extracted = trafilatura.extract(
            html_str,
            output_format="markdown",
            include_tables=True,
            include_images=False,
        )
        progress("render", 60)
        if extracted:
            markdown = extracted.strip()
            extractor = "trafilatura"
        else:
            soup = BeautifulSoup(html_str, "html.parser")
            root = soup.body or soup
            markdown = html_to_markdown(str(root))
            extractor = "markdownify-fallback"
        progress("done", 100)
        return ConversionResult(markdown=markdown, metadata={"extractor": extractor})
