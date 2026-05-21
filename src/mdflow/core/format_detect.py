"""Detect input format using extension + magic bytes.

Policy (from PRD §5 step 2 + URL handling agreement §3.2 step 9):
- magic bytes win when extension and magic disagree
- agreement on a single format yields source="agreement"
- magic-only yields source="magic"; extension-only yields source="ext"
- when magic is absent, explicit HTTP Content-Type (`content_type_hint`)
  beats filename extension (agreement §3.2 step 9: magic > Content-Type
  > Content-Disposition filename > URL path extension). Source label
  "content-type" is used in that branch.
- unknown returns format=None with source="unknown"

libmagic (python-magic) is consulted as a last-resort MIME probe when
the in-line prefix probes (PDF/OOXML ZIP/HTML) don't match; if libmagic
is unavailable on the host, the in-line probes still cover M0 fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath

try:
    import magic  # python-magic
except ImportError:  # pragma: no cover - libmagic optional
    magic = None  # type: ignore[assignment]


@dataclass
class DetectionResult:
    format: str | None
    source: str  # "ext", "magic", "agreement", "unknown"
    warnings: list[str] = field(default_factory=list)


_MIME_TO_FORMAT: dict[str, str] = {
    # text/plain is intentionally excluded: libmagic returns it for nearly
    # any text input (txt/md/csv), which would create false agreements or
    # false magic-wins disagreements against the extension hint.
    "text/markdown": "md",
    "text/csv": "csv",
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "text/html": "html",
    "application/xhtml+xml": "html",
}

# Used for the explicit HTTP `Content-Type` hint. Unlike the libmagic
# path, `text/plain` here is accepted because the server (or fetch
# layer) has positively asserted it — there is no auto-over-classify
# risk like libmagic.
_CT_TO_FORMAT: dict[str, str] = {
    **_MIME_TO_FORMAT,
    "text/plain": "txt",
}

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


def _content_type_format(content_type_hint: str | None) -> str | None:
    if not content_type_hint:
        return None
    media = content_type_hint.split(";", 1)[0].strip().lower()
    return _CT_TO_FORMAT.get(media)


def _magic_format(data: bytes) -> str | None:
    if data.startswith(b"%PDF"):
        return "pdf"
    if data[:4] == b"PK\x03\x04":
        head = data[:4096]
        if b"word/" in head:
            return "docx"
        if b"ppt/" in head:
            return "pptx"
        if b"xl/" in head:
            return "xlsx"
        return None
    lowered = data[:1024].lstrip().lower()
    if lowered.startswith(b"<!doctype html") or lowered.startswith(b"<html"):
        return "html"
    if magic is not None:
        try:
            mime = magic.from_buffer(data, mime=True)
            return _MIME_TO_FORMAT.get(mime)
        except Exception:  # noqa: BLE001 - libmagic is best-effort
            return None
    return None


def detect_format(
    data: bytes,
    filename_hint: str | None,
    content_type_hint: str | None = None,
) -> DetectionResult:
    ext = _ext_format(filename_hint)
    magic_fmt = _magic_format(data)

    if ext and magic_fmt:
        if ext == magic_fmt:
            return DetectionResult(format=ext, source="agreement")
        return DetectionResult(
            format=magic_fmt,
            source="magic",
            warnings=[f"extension/magic disagreement: ext={ext}, magic={magic_fmt}; using magic"],
        )
    if magic_fmt:
        return DetectionResult(format=magic_fmt, source="magic")
    # Magic absent — Content-Type beats filename hint per agreement §3.2 step 9.
    ct = _content_type_format(content_type_hint)
    if ct:
        return DetectionResult(format=ct, source="content-type")
    if ext:
        return DetectionResult(format=ext, source="ext")
    return DetectionResult(format=None, source="unknown")
