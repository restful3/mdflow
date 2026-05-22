from mdflow.converters.base import ConversionContext
from mdflow.converters.pdf import PdfConverter
from tests.golden import assert_golden


def _ctx(data: bytes) -> ConversionContext:
    return ConversionContext(data=data, filename_hint="sample.pdf", format="pdf")


def test_protocol_attrs():
    conv = PdfConverter()
    assert conv.name == "pdf-pymupdf4llm"
    assert conv.formats == ("pdf",)
    assert conv.requires_gpu is False
    assert conv.can_handle(_ctx(b"")) is True
    assert conv.can_handle(ConversionContext(data=b"", filename_hint=None, format="docx")) is False


def test_pdf_structure(sample_pdf_bytes):
    out = PdfConverter().convert(_ctx(sample_pdf_bytes), lambda s, p: None)
    assert "Document Title" in out.markdown
    assert "First paragraph of body text" in out.markdown
    assert out.metadata["engine"] == "pymupdf4llm"
    assert out.metadata["pages"] == 1


def test_pdf_progress_ends_done(sample_pdf_bytes):
    seen: list[tuple[str, int]] = []
    PdfConverter().convert(_ctx(sample_pdf_bytes), lambda s, p: seen.append((s, p)))
    assert seen[-1] == ("done", 100)


def test_empty_pdf_no_exception(empty_pdf_bytes):
    out = PdfConverter().convert(_ctx(empty_pdf_bytes), lambda s, p: None)
    assert isinstance(out.markdown, str)  # empty/minimal, not an exception
    assert out.metadata["pages"] == 1


def test_pdf_golden(sample_pdf_bytes):
    out = PdfConverter().convert(_ctx(sample_pdf_bytes), lambda s, p: None)
    assert_golden(out.markdown, "pdf/sample.md")
