"""Shared HTML -> Markdown conversion (markdownify).

Single responsibility: HTML string -> Markdown string. Used by the docx
converter (after mammoth) and the html converter's fallback path. Heading
style is ATX (`#`). Images are kept by default (alt text preserved,
best-effort); docx passes strip_images=True to drop them entirely.
"""

from __future__ import annotations

from markdownify import markdownify


def html_to_markdown(html: str, *, strip_images: bool = False) -> str:
    options: dict = {"heading_style": "ATX"}
    if strip_images:
        options["strip"] = ["img"]
    return markdownify(html, **options).strip()
