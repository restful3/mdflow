"""Detect input format.

Incremental: this slice covers extension-based detection only. Magic
bytes (with magic-wins-on-disagreement policy) land in a follow-up.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath


@dataclass
class DetectionResult:
    format: str | None
    source: str  # "ext", "magic", "agreement", "unknown"
    warnings: list[str] = field(default_factory=list)


_EXT_TO_FORMAT: dict[str, str] = {
    ".txt": "txt",
    ".md": "md",
    ".markdown": "md",
    ".csv": "csv",
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
    ".html": "html",
    ".htm": "html",
    ".hwp": "hwp",
    ".doc": "doc",
    ".ppt": "ppt",
}


def _ext_format(filename_hint: str | None) -> str | None:
    if not filename_hint:
        return None
    ext = PurePosixPath(filename_hint).suffix.lower()
    return _EXT_TO_FORMAT.get(ext)


def detect_format(data: bytes, filename_hint: str | None) -> DetectionResult:
    ext = _ext_format(filename_hint)
    if ext:
        return DetectionResult(format=ext, source="ext")
    return DetectionResult(format=None, source="unknown")
