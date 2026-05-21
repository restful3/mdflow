"""ConversionService — incremental: cache + format detect + dispatch wiring.

This first slice covers the local-bytes path: cache miss -> detect ->
dispatch -> cache write, and the second call hits the cache. URL fetch
integration (service + url_fetch) lands in the follow-up slice; this
service stays bytes-in / response-out, with URL fetching owned by the
API layer (Task 14).
"""

from pathlib import Path

import pytest

from mdflow.converters.text import TextConverter
from mdflow.core.cache import Cache
from mdflow.core.errors import ErrorCode, MdflowError
from mdflow.core.registry import Registry
from mdflow.core.service import ConversionService, ConvertRequest


@pytest.fixture
def service(tmp_cache_dir: Path) -> ConversionService:
    reg = Registry()
    reg.register(TextConverter())
    return ConversionService(registry=reg, cache=Cache(tmp_cache_dir))


def test_convert_txt_passthrough_first_call(service: ConversionService):
    out = service.convert(ConvertRequest(data=b"hello mdflow", filename_hint="a.txt"))
    assert out.cached is False
    assert out.detected_format == "txt"
    assert out.converter_name == "text-passthrough"
    assert out.result.markdown == "hello mdflow"
    assert len(out.sha256) == 64


def test_convert_returns_cached_on_second_call(service: ConversionService):
    req = ConvertRequest(data=b"hello mdflow", filename_hint="a.txt")
    first = service.convert(req)
    second = service.convert(req)
    assert first.cached is False
    assert second.cached is True
    assert first.sha256 == second.sha256
    assert first.result.markdown == second.result.markdown


def test_convert_unsupported_format_raises(service: ConversionService):
    """%PDF magic bytes -> format detected as pdf -> no converter -> UNSUPPORTED_FORMAT."""
    req = ConvertRequest(data=b"%PDF-1.4\n", filename_hint="x.pdf")
    with pytest.raises(MdflowError) as exc:
        service.convert(req)
    assert exc.value.code is ErrorCode.UNSUPPORTED_FORMAT


def test_convert_format_detect_failed_raises(service: ConversionService):
    req = ConvertRequest(data=b"\x00\x01\x02noisy", filename_hint=None)
    with pytest.raises(MdflowError) as exc:
        service.convert(req)
    assert exc.value.code is ErrorCode.FORMAT_DETECT_FAILED


def test_convert_options_change_cache_key(service: ConversionService):
    a = service.convert(ConvertRequest(data=b"hi", filename_hint="a.txt", options={"x": 1}))
    b = service.convert(ConvertRequest(data=b"hi", filename_hint="a.txt", options={"x": 2}))
    assert a.sha256 != b.sha256
    assert a.cached is False
    assert b.cached is False


def test_convert_cache_key_includes_detected_format(service: ConversionService):
    """Codex review blocker #1 (2026-05-21): same bytes with different
    filename hints must not share cache entries when detection routes
    them through different converters. Without including detected_format
    in the cache key, `.txt` first then `.csv` returns the txt-cached
    result instead of the csv table.

    Comma-free bytes are used so libmagic does not classify as text/csv
    (which would let magic-wins override the .txt hint).
    """
    data = b"hello world\n"

    txt_out = service.convert(ConvertRequest(data=data, filename_hint="t.txt"))
    csv_out = service.convert(ConvertRequest(data=data, filename_hint="t.csv"))

    assert txt_out.detected_format == "txt"
    assert csv_out.detected_format == "csv"
    assert txt_out.result.markdown == "hello world\n"
    assert csv_out.result.markdown.startswith("| hello world |")
    assert txt_out.sha256 != csv_out.sha256
    assert csv_out.cached is False


def test_convert_passes_content_type_hint_to_detect_format(service: ConversionService):
    """Codex blocker #2 slice 2 (2026-05-21): ConvertRequest carries an
    explicit Content-Type hint and ConversionService forwards it to
    detect_format(). Without this wiring, a URL fetch with no path
    extension and indeterminate magic (e.g. plain text served as
    `Content-Type: text/plain`) still raises FORMAT_DETECT_FAILED even
    though slice 1 already taught detect_format to consume the hint.
    """
    out = service.convert(
        ConvertRequest(
            data=b"plain text body\n",
            filename_hint=None,
            content_type_hint="text/plain; charset=utf-8",
        )
    )
    assert out.detected_format == "txt"
    assert out.converter_name == "text-passthrough"
    assert out.result.markdown == "plain text body\n"


def test_convert_progress_callback_invoked(service: ConversionService):
    seen: list[tuple[str, int]] = []
    service.convert(
        ConvertRequest(data=b"hi", filename_hint="a.txt"),
        progress=lambda s, p: seen.append((s, p)),
    )
    # TextConverter ends with ("done", 100)
    assert seen[-1] == ("done", 100)
