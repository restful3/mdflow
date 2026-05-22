"""Shared helper for rendering values into Markdown table cells.

A raw `|` or newline in a cell breaks the table row, so every converter
that emits Markdown tables (pptx, xlsx, csv) routes cell text through
`escape_table_cell` first.
"""

from __future__ import annotations


def escape_table_cell(text: str) -> str:
    """Make `text` safe inside a Markdown table cell: flatten newlines to
    spaces and escape pipes (both would otherwise break the row)."""
    flattened = text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    return flattened.replace("|", "\\|")
