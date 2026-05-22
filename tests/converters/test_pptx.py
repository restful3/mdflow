from mdflow.converters.base import ConversionContext
from mdflow.converters.pptx import PptxConverter
from tests.golden import assert_golden


def _ctx(data: bytes) -> ConversionContext:
    return ConversionContext(data=data, filename_hint="sample.pptx", format="pptx")


def test_protocol_attrs():
    conv = PptxConverter()
    assert conv.name == "pptx-python-pptx"
    assert conv.formats == ("pptx",)
    assert conv.requires_gpu is False
    assert conv.can_handle(_ctx(b"")) is True


def test_pptx_structure(sample_pptx_bytes):
    out = PptxConverter().convert(_ctx(sample_pptx_bytes), lambda s, p: None)
    md = out.markdown
    assert "## First Slide" in md
    assert "- Bullet one" in md
    assert "  - Sub bullet" in md  # level 1 -> 2-space indent
    assert "## Second Slide" in md
    assert "> Notes:" in md
    assert "Presenter note here" in md


def test_pptx_progress_ends_done(sample_pptx_bytes):
    seen: list[tuple[str, int]] = []
    PptxConverter().convert(_ctx(sample_pptx_bytes), lambda s, p: seen.append((s, p)))
    assert seen[-1] == ("done", 100)


def test_pptx_golden(sample_pptx_bytes):
    out = PptxConverter().convert(_ctx(sample_pptx_bytes), lambda s, p: None)
    assert_golden(out.markdown, "pptx/sample.md")
