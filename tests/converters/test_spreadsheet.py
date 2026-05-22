import io

from mdflow.converters.base import ConversionContext
from mdflow.converters.spreadsheet import XlsxConverter
from tests.golden import assert_golden


def _ctx(data: bytes) -> ConversionContext:
    return ConversionContext(data=data, filename_hint="sample.xlsx", format="xlsx")


def test_xlsx_escapes_pipe_and_newline():
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "S"
    ws.append(["h1", "h|2"])
    ws.append(["a\nb", "c"])
    buf = io.BytesIO()
    wb.save(buf)
    out = XlsxConverter().convert(_ctx(buf.getvalue()), lambda s, p: None)
    assert "h\\|2" in out.markdown
    assert "a b" in out.markdown
    assert "a\nb" not in out.markdown


def test_protocol_attrs():
    conv = XlsxConverter()
    assert conv.name == "xlsx-openpyxl"
    assert conv.formats == ("xlsx",)
    assert conv.requires_gpu is False
    assert conv.can_handle(_ctx(b"")) is True
    assert conv.can_handle(ConversionContext(data=b"", filename_hint=None, format="pdf")) is False


def test_xlsx_structure(sample_xlsx_bytes):
    out = XlsxConverter().convert(_ctx(sample_xlsx_bytes), lambda s, p: None)
    md = out.markdown
    assert "## Sheet1" in md
    assert "| name | score |" in md
    assert "| alice | 1 |" in md
    assert "## Second" in md
    assert "| x | y |" in md
    assert out.metadata["formula_values"] == "cached"


def test_xlsx_progress_ends_done(sample_xlsx_bytes):
    seen: list[tuple[str, int]] = []
    XlsxConverter().convert(_ctx(sample_xlsx_bytes), lambda s, p: seen.append((s, p)))
    assert seen[-1] == ("done", 100)


def test_xlsx_golden(sample_xlsx_bytes):
    out = XlsxConverter().convert(_ctx(sample_xlsx_bytes), lambda s, p: None)
    assert_golden(out.markdown, "xlsx/sample.md")
