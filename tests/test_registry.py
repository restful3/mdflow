"""Registry — incremental: register + select dispatch.

list_formats (used by /capabilities) lands in the follow-up slice.
"""

import pytest

from mdflow.converters.base import ConversionContext, ConversionResult
from mdflow.core.errors import ErrorCode, MdflowError
from mdflow.core.registry import Registry


class _Txt:
    name = "txt"
    formats = ("txt",)
    requires_gpu = False

    def can_handle(self, ctx):
        return ctx.format == "txt"

    def convert(self, ctx, progress):
        return ConversionResult(markdown="t")


class _Pdf:
    name = "pdf"
    formats = ("pdf",)
    requires_gpu = True

    def can_handle(self, ctx):
        return ctx.format == "pdf"

    def convert(self, ctx, progress):
        return ConversionResult(markdown="p")


def _ctx(fmt: str) -> ConversionContext:
    return ConversionContext(data=b"", filename_hint=None, format=fmt)


def test_register_returns_the_converter():
    reg = Registry()
    inst = _Txt()
    assert reg.register(inst) is inst


def test_select_by_format():
    reg = Registry()
    reg.register(_Txt())
    reg.register(_Pdf())
    assert reg.select(_ctx("txt")).name == "txt"
    assert reg.select(_ctx("pdf")).name == "pdf"


def test_select_unknown_format_raises_unsupported_format():
    reg = Registry()
    with pytest.raises(MdflowError) as exc:
        reg.select(_ctx("xyz"))
    assert exc.value.code is ErrorCode.UNSUPPORTED_FORMAT
    assert "xyz" in str(exc.value)


def test_first_registered_wins_for_same_format():
    reg = Registry()

    class _T1:
        name = "t1"
        formats = ("txt",)
        requires_gpu = False

        def can_handle(self, ctx):
            return True

        def convert(self, ctx, progress):
            return ConversionResult(markdown="t1")

    class _T2:
        name = "t2"
        formats = ("txt",)
        requires_gpu = False

        def can_handle(self, ctx):
            return True

        def convert(self, ctx, progress):
            return ConversionResult(markdown="t2")

    reg.register(_T1())
    reg.register(_T2())
    assert reg.select(_ctx("txt")).name == "t1"


def test_select_skips_converter_with_can_handle_false():
    """When can_handle is False, dispatch falls through to the next match."""
    reg = Registry()

    class _Refuser:
        name = "refuser"
        formats = ("txt",)
        requires_gpu = False

        def can_handle(self, ctx):
            return False

        def convert(self, ctx, progress):
            raise AssertionError("should not be called")

    reg.register(_Refuser())
    reg.register(_Txt())
    assert reg.select(_ctx("txt")).name == "txt"


def test_select_unknown_when_only_refuser_registered():
    reg = Registry()

    class _Refuser:
        name = "refuser"
        formats = ("txt",)
        requires_gpu = False

        def can_handle(self, ctx):
            return False

        def convert(self, ctx, progress):
            return ConversionResult(markdown="x")

    reg.register(_Refuser())
    with pytest.raises(MdflowError) as exc:
        reg.select(_ctx("txt"))
    assert exc.value.code is ErrorCode.UNSUPPORTED_FORMAT
