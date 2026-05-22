import sys

import pytest

from mdflow.converters.base import ConversionContext
from mdflow.converters.hwp import HwpConverter
from mdflow.core.errors import ErrorCode, MdflowError


def _ctx(data: bytes) -> ConversionContext:
    return ConversionContext(data=data, filename_hint="sample.hwp", format="hwp")


def test_protocol_attrs():
    conv = HwpConverter()
    assert conv.name == "hwp-pyhwp"
    assert conv.formats == ("hwp",)
    assert conv.requires_gpu is False
    assert conv.can_handle(_ctx(b"")) is True
    assert (
        conv.can_handle(
            ConversionContext(data=b"", filename_hint="x.pdf", format="pdf")
        )
        is False
    )


def test_happy_path_monkeypatched(monkeypatch):
    xhtml = (
        b"<html><head><style>.x{color:red}</style></head><body>"
        b"<h1>\xeb\xac\xb8\xec\x84\x9c \xec\xa0\x9c\xeb\xaa\xa9</h1>"  # "문서 제목"
        b"<table><tr><td>A</td><td>B</td></tr></table>"
        b"<img src='bindata/x.png' alt='dropme'/>"
        b"</body></html>"
    )
    conv = HwpConverter()
    monkeypatch.setattr(conv, "_hwp_to_xhtml", lambda src_path: xhtml)
    seen: list[tuple[str, int]] = []
    out = conv.convert(_ctx(b"fake-hwp-bytes"), lambda s, p: seen.append((s, p)))
    assert "문서 제목" in out.markdown
    assert "A" in out.markdown and "B" in out.markdown  # table content preserved
    assert "dropme" not in out.markdown  # image stripped
    assert ".x{color:red}" not in out.markdown  # style dropped
    assert out.metadata == {"source_format": "hwp", "engine": "pyhwp"}
    pcts = [p for _, p in seen]
    assert pcts == sorted(pcts) and seen[-1][1] == 100


def test_missing_pyhwp_raises_hwp_unavailable(monkeypatch):
    # Block the lazy import so _hwp_to_xhtml's `from hwp5...` raises ImportError.
    monkeypatch.setitem(sys.modules, "hwp5.xmlmodel", None)
    monkeypatch.setitem(sys.modules, "hwp5.hwp5html", None)
    conv = HwpConverter()
    with pytest.raises(MdflowError) as exc:
        conv.convert(_ctx(b"anything"), lambda s, p: None)
    assert exc.value.code is ErrorCode.HWP_UNAVAILABLE


def test_library_error_propagates(monkeypatch):
    # pyhwp/lxml errors must NOT be swallowed (§6); run_conversion wraps them.
    conv = HwpConverter()

    def boom(src_path):
        raise ValueError("lxml.etree.XMLSyntaxError simulated")

    monkeypatch.setattr(conv, "_hwp_to_xhtml", boom)
    with pytest.raises(ValueError):
        conv.convert(_ctx(b"anything"), lambda s, p: None)
