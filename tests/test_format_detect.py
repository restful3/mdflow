"""Format detection — full slice: extension + magic bytes."""

import zipfile
from io import BytesIO

from mdflow.core.format_detect import DetectionResult, detect_format


def test_detect_txt_by_extension():
    result = detect_format(b"hello", filename_hint="sample.txt")
    assert result.format == "txt"
    assert result.source == "ext"
    assert result.warnings == []


def test_detect_md_uppercase_extension():
    result = detect_format(b"# x", filename_hint="README.MD")
    assert result.format == "md"
    assert result.source == "ext"


def test_detect_office_extensions():
    cases = [
        ("a.docx", "docx"),
        ("a.pptx", "pptx"),
        ("a.xlsx", "xlsx"),
        ("a.pdf", "pdf"),
        ("a.html", "html"),
        ("a.htm", "html"),
        ("a.hwp", "hwp"),
    ]
    for hint, expected in cases:
        result = detect_format(b"", filename_hint=hint)
        assert result.format == expected, f"{hint} -> {result.format}"
        assert result.source == "ext"


def test_detect_unknown_extension_returns_unknown():
    result = detect_format(b"x", filename_hint="x.unknownext")
    assert result.format is None
    assert result.source == "unknown"


def test_detect_no_hint_returns_unknown():
    result = detect_format(b"x", filename_hint=None)
    assert result.format is None
    assert result.source == "unknown"


def test_detection_result_dataclass_fields():
    r = DetectionResult(format="pdf", source="magic", warnings=["w"])
    assert r.format == "pdf"
    assert r.source == "magic"
    assert r.warnings == ["w"]


def test_detection_result_default_warnings_empty():
    r = DetectionResult(format="txt", source="ext")
    assert r.warnings == []


def _make_ooxml(marker_path: str) -> bytes:
    """Build a minimal ZIP containing one entry under the given OOXML marker."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(marker_path, b"x")
    return buf.getvalue()


def test_detect_pdf_by_magic_only():
    pdf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    result = detect_format(pdf, filename_hint=None)
    assert result.format == "pdf"
    assert result.source == "magic"


def test_detect_docx_by_magic_ooxml():
    blob = _make_ooxml("word/document.xml")
    result = detect_format(blob, filename_hint=None)
    assert result.format == "docx"
    assert result.source == "magic"


def test_detect_pptx_by_magic_ooxml():
    blob = _make_ooxml("ppt/presentation.xml")
    result = detect_format(blob, filename_hint=None)
    assert result.format == "pptx"
    assert result.source == "magic"


def test_detect_xlsx_by_magic_ooxml():
    blob = _make_ooxml("xl/workbook.xml")
    result = detect_format(blob, filename_hint=None)
    assert result.format == "xlsx"
    assert result.source == "magic"


def test_detect_html_by_doctype():
    result = detect_format(b"<!DOCTYPE html><html><body>x</body></html>", filename_hint=None)
    assert result.format == "html"
    assert result.source == "magic"


def test_detect_html_by_open_tag_with_leading_whitespace():
    result = detect_format(b"   \n<html><body></body></html>", filename_hint=None)
    assert result.format == "html"


def test_detect_agreement_no_warning():
    pdf = b"%PDF-1.4\n"
    result = detect_format(pdf, filename_hint="report.pdf")
    assert result.format == "pdf"
    assert result.source == "agreement"
    assert result.warnings == []


def test_detect_disagreement_prefers_magic_and_warns():
    pdf = b"%PDF-1.4\n"
    result = detect_format(pdf, filename_hint="trick.txt")
    assert result.format == "pdf"
    assert result.source == "magic"
    assert any("disagreement" in w.lower() for w in result.warnings)


def test_detect_unknown_returns_unknown():
    result = detect_format(b"\x00\x01\x02noisy", filename_hint=None)
    assert result.format is None
    assert result.source == "unknown"


def test_detect_uses_content_type_when_magic_and_ext_absent():
    """Codex blocker #2 (2026-05-21): agreement §3.2 step 9 places
    Content-Type between magic and filename in the hint chain. A URL
    fetch with no path extension and indeterminate magic (plain text
    body served as ``Content-Type: text/plain``) must still resolve.
    """
    result = detect_format(
        b"plain text body\n",
        filename_hint=None,
        content_type_hint="text/plain; charset=utf-8",
    )
    assert result.format == "txt"
    assert result.source == "content-type"
