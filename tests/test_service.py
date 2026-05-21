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


def test_convert_progress_callback_invoked(service: ConversionService):
    seen: list[tuple[str, int]] = []
    service.convert(
        ConvertRequest(data=b"hi", filename_hint="a.txt"),
        progress=lambda s, p: seen.append((s, p)),
    )
    # TextConverter ends with ("done", 100)
    assert seen[-1] == ("done", 100)
