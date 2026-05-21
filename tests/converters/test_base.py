"""Converter base — full: ConversionContext, ConversionResult, Converter Protocol."""

from pathlib import Path

from mdflow.converters.base import (
    ConversionContext,
    ConversionResult,
    Converter,
    ProgressCallback,
)


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


class _DummyConverter:
    name = "dummy"
    formats = ("txt",)
    requires_gpu = False

    def can_handle(self, ctx: ConversionContext) -> bool:
        return ctx.format == "txt"

    def convert(self, ctx: ConversionContext, progress: ProgressCallback) -> ConversionResult:
        progress("done", 100)
        return ConversionResult(markdown="x")


def test_dummy_satisfies_protocol_at_runtime():
    inst: Converter = _DummyConverter()
    assert isinstance(inst, Converter)
    assert inst.name == "dummy"
    assert inst.formats == ("txt",)
    assert inst.requires_gpu is False


def test_dummy_can_handle_matches_format():
    inst = _DummyConverter()
    yes = ConversionContext(data=b"", filename_hint=None, format="txt")
    no = ConversionContext(data=b"", filename_hint=None, format="pdf")
    assert inst.can_handle(yes) is True
    assert inst.can_handle(no) is False


def test_dummy_convert_invokes_progress_and_returns_result():
    seen: list[tuple[str, int]] = []

    def progress(stage: str, pct: int) -> None:
        seen.append((stage, pct))

    ctx = ConversionContext(data=b"hi", filename_hint="a.txt", format="txt")
    inst = _DummyConverter()
    out = inst.convert(ctx, progress)
    assert out.markdown == "x"
    assert seen == [("done", 100)]


def test_progress_callback_type_alias_callable():
    """ProgressCallback should accept a (stage:str, pct:int) -> None callable."""
    calls: list[tuple[str, int]] = []
    cb: ProgressCallback = lambda s, p: calls.append((s, p))  # noqa: E731
    cb("parse", 50)
    assert calls == [("parse", 50)]


def test_object_missing_attrs_is_not_converter():
    class _Bare:
        pass

    assert not isinstance(_Bare(), Converter)
