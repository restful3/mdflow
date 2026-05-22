"""pdf -> Markdown via pymupdf4llm.

pymupdf4llm extracts structure-preserving Markdown (headings/lists/tables
via font-size heuristics) from a PyMuPDF document. No internal try/except
(library errors propagate -> ConversionService wraps as CONVERSION_FAILED);
doc.close() is a resource-cleanup try/finally with no except.
"""

from __future__ import annotations

import fitz
import pymupdf4llm

from mdflow.converters.base import (
    ConversionContext,
    ConversionResult,
    ProgressCallback,
)


class PdfConverter:
    name = "pdf-pymupdf4llm"
    formats: tuple[str, ...] = ("pdf",)
    requires_gpu = False

    def can_handle(self, ctx: ConversionContext) -> bool:
        return ctx.format in self.formats

    def convert(self, ctx: ConversionContext, progress: ProgressCallback) -> ConversionResult:
        progress("parse", 10)
        doc = fitz.open(stream=ctx.data, filetype="pdf")
        try:
            pages = doc.page_count
            markdown = pymupdf4llm.to_markdown(doc)
        finally:
            doc.close()
        progress("render", 60)
        progress("done", 100)
        return ConversionResult(
            markdown=markdown.strip(),
            metadata={"pages": pages, "engine": "pymupdf4llm"},
        )
