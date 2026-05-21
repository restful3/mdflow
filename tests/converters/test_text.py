"""TextConverter — full v1 slice: txt/md passthrough + csv → Markdown table."""

from mdflow.converters.base import ConversionContext
from mdflow.converters.text import TextConverter


def _ctx(data: bytes, fmt: str, hint: str | None = None) -> ConversionContext:
    return ConversionContext(data=data, filename_hint=hint, format=fmt)


def test_can_handle_txt_md_csv():
    conv = TextConverter()
    assert conv.can_handle(_ctx(b"", "txt")) is True
    assert conv.can_handle(_ctx(b"", "md")) is True
    assert conv.can_handle(_ctx(b"", "csv")) is True


def test_can_handle_rejects_other_formats():
    conv = TextConverter()
    assert conv.can_handle(_ctx(b"", "pdf")) is False
    assert conv.can_handle(_ctx(b"", "docx")) is False


def test_txt_passthrough_utf8():
    conv = TextConverter()
    out = conv.convert(_ctx(b"hello\nworld", "txt", "a.txt"), lambda s, p: None)
    assert out.markdown == "hello\nworld"
    assert out.metadata["encoding"] == "utf-8"


def test_txt_passthrough_cp949():
    # Use a longer Korean passage: chardet needs enough signal to identify
    # the cp949/euc-kr family (see plan risk R4 — short-text accuracy).
    text = (
        "안녕하세요 mdflow 입니다. 이 문장은 한국어 인코딩 감지를 검증하기 위한 "
        "충분히 긴 cp949 텍스트입니다. 가나다라마바사 아자차카타파하."
    )
    data = text.encode("cp949")
    conv = TextConverter()
    out = conv.convert(_ctx(data, "txt", "b.txt"), lambda s, p: None)
    assert "안녕하세요" in out.markdown
    # chardet may report cp949, euc-kr, or a close synonym
    assert out.metadata["encoding"].lower() in {"cp949", "euc-kr", "ks_c_5601-1987"}


def test_md_passthrough_unchanged():
    md = "# Title\n\n- item\n"
    conv = TextConverter()
    out = conv.convert(_ctx(md.encode("utf-8"), "md", "c.md"), lambda s, p: None)
    assert out.markdown == md


def test_progress_callback_invoked_with_done():
    seen: list[tuple[str, int]] = []
    conv = TextConverter()
    conv.convert(_ctx(b"hi", "txt", "x.txt"), lambda s, p: seen.append((s, p)))
    assert seen[-1] == ("done", 100)


def test_converter_protocol_attrs():
    conv = TextConverter()
    assert conv.name == "text-passthrough"
    assert "txt" in conv.formats
    assert "md" in conv.formats
    assert "csv" in conv.formats
    assert conv.requires_gpu is False


def test_csv_renders_header_and_body_as_table():
    data = b"name,score\nalice,1\nbob,2\n"
    conv = TextConverter()
    out = conv.convert(_ctx(data, "csv", "sample.csv"), lambda s, p: None)
    lines = out.markdown.splitlines()
    assert lines[0] == "| name | score |"
    assert lines[1] == "| --- | --- |"
    assert lines[2] == "| alice | 1 |"
    assert lines[3] == "| bob | 2 |"


def test_csv_pads_short_rows_to_header_width():
    data = b"a,b,c\n1\n2,3\n"
    conv = TextConverter()
    out = conv.convert(_ctx(data, "csv"), lambda s, p: None)
    lines = out.markdown.splitlines()
    assert lines[2] == "| 1 |  |  |"
    assert lines[3] == "| 2 | 3 |  |"


def test_csv_empty_returns_empty_markdown():
    conv = TextConverter()
    out = conv.convert(_ctx(b"", "csv"), lambda s, p: None)
    assert out.markdown == ""


def test_csv_truncates_rows_longer_than_header():
    """Extra trailing columns are dropped to match header width."""
    data = b"a,b\n1,2,3,4\n"
    conv = TextConverter()
    out = conv.convert(_ctx(data, "csv"), lambda s, p: None)
    lines = out.markdown.splitlines()
    assert lines[2] == "| 1 | 2 |"
