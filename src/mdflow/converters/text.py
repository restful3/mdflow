"""txt/md passthrough converter with encoding detection.

Incremental: this slice covers txt and md. CSV → Markdown-table
rendering lands in the follow-up step.
"""

from __future__ import annotations

import chardet

from mdflow.converters.base import (
    ConversionContext,
    ConversionResult,
    ProgressCallback,
)


class TextConverter:
    name = "text-passthrough"
    formats: tuple[str, ...] = ("txt", "md")
    requires_gpu = False

    def can_handle(self, ctx: ConversionContext) -> bool:
        return ctx.format in self.formats

    def convert(self, ctx: ConversionContext, progress: ProgressCallback) -> ConversionResult:
        progress("decode", 10)
        text, encoding = _decode(ctx.data)
        progress("done", 100)
        return ConversionResult(
            markdown=text,
            metadata={"encoding": encoding},
        )


def _decode(data: bytes) -> tuple[str, str]:
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        detected = chardet.detect(data)
        encoding = (detected.get("encoding") or "latin-1").lower()
        try:
            return data.decode(encoding), encoding
        except (UnicodeDecodeError, LookupError):
            return data.decode("latin-1", errors="replace"), "latin-1"
