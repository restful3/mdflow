"""txt/md/csv passthrough converter with encoding detection.

Full v1 slice: txt and md decode as-is; csv renders as a Markdown
table (header row + alignment row + body, rows padded/truncated to
header width).
"""

from __future__ import annotations

import csv
import io

import chardet

from mdflow.converters._md_table import escape_table_cell
from mdflow.converters.base import (
    ConversionContext,
    ConversionResult,
    ProgressCallback,
)


class TextConverter:
    name = "text-passthrough"
    formats: tuple[str, ...] = ("txt", "md", "csv")
    requires_gpu = False

    def can_handle(self, ctx: ConversionContext) -> bool:
        return ctx.format in self.formats

    def convert(self, ctx: ConversionContext, progress: ProgressCallback) -> ConversionResult:
        progress("decode", 10)
        text, encoding = _decode(ctx.data)
        if ctx.format == "csv":
            progress("render", 50)
            markdown = _csv_to_table(text)
        else:
            markdown = text
        progress("done", 100)
        return ConversionResult(
            markdown=markdown,
            metadata={"encoding": encoding},
        )


def _csv_to_table(text: str) -> str:
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return ""
    header, *body = rows
    width = len(header)
    out = ["| " + " | ".join(escape_table_cell(c) for c in header) + " |"]
    out.append("| " + " | ".join("---" for _ in header) + " |")
    for row in body:
        padded = row + [""] * (width - len(row))
        out.append("| " + " | ".join(escape_table_cell(c) for c in padded[:width]) + " |")
    return "\n".join(out)


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
