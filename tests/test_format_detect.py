"""Format detection — incremental: extension only.

Magic-bytes detection lands in a subsequent step; this slice covers
DetectionResult shape and extension-based lookup.
"""

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
