"""Converter base — incremental: ConversionContext + ConversionResult."""

from pathlib import Path

from mdflow.converters.base import ConversionContext, ConversionResult


def test_context_required_fields():
    ctx = ConversionContext(
        data=b"abc",
        filename_hint="x.txt",
        format="txt",
    )
    assert ctx.data == b"abc"
    assert ctx.filename_hint == "x.txt"
    assert ctx.format == "txt"


def test_context_defaults():
    ctx = ConversionContext(data=b"", filename_hint=None, format="txt")
    assert ctx.options == {}
    assert ctx.tmp_path is None
    assert ctx.metadata == {}


def test_context_default_dicts_are_per_instance():
    a = ConversionContext(data=b"a", filename_hint=None, format="txt")
    b = ConversionContext(data=b"b", filename_hint=None, format="txt")
    a.options["k"] = 1
    a.metadata["m"] = 2
    assert b.options == {}
    assert b.metadata == {}


def test_context_accepts_tmp_path():
    p = Path("/tmp/x")
    ctx = ConversionContext(data=b"", filename_hint=None, format="txt", tmp_path=p)
    assert ctx.tmp_path == p


def test_result_minimal():
    r = ConversionResult(markdown="# x")
    assert r.markdown == "# x"
    assert r.metadata == {}
    assert r.assets == []


def test_result_with_metadata_and_assets():
    r = ConversionResult(markdown="# x", metadata={"k": 1}, assets=["a.png"])
    assert r.markdown == "# x"
    assert r.metadata == {"k": 1}
    assert r.assets == ["a.png"]


def test_result_default_collections_are_per_instance():
    a = ConversionResult(markdown="a")
    b = ConversionResult(markdown="b")
    a.metadata["k"] = 1
    a.assets.append("x")
    assert b.metadata == {}
    assert b.assets == []
