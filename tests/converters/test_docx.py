from mdflow.converters.base import ConversionContext
from mdflow.converters.docx import DocxConverter
from tests.golden import assert_golden


def _ctx(data: bytes) -> ConversionContext:
    return ConversionContext(data=data, filename_hint="sample.docx", format="docx")


def test_protocol_attrs():
    conv = DocxConverter()
    assert conv.name == "docx-mammoth"
    assert conv.formats == ("docx",)
    assert conv.requires_gpu is False
    assert conv.can_handle(_ctx(b"")) is True
    assert conv.can_handle(ConversionContext(data=b"", filename_hint=None, format="pdf")) is False


def test_docx_structure(sample_docx_bytes):
    out = DocxConverter().convert(_ctx(sample_docx_bytes), lambda s, p: None)
    assert "# Document Title" in out.markdown
    assert "## Section" in out.markdown
    assert "**bold**" in out.markdown


def test_docx_progress_ends_done(sample_docx_bytes):
    seen: list[tuple[str, int]] = []
    DocxConverter().convert(_ctx(sample_docx_bytes), lambda s, p: seen.append((s, p)))
    assert seen[-1] == ("done", 100)


def test_docx_golden(sample_docx_bytes):
    out = DocxConverter().convert(_ctx(sample_docx_bytes), lambda s, p: None)
    assert_golden(out.markdown, "docx/sample.md")
