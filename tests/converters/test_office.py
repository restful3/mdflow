import subprocess

import pytest

from mdflow.converters.base import ConversionContext
from mdflow.converters.office import LibreOfficeConverter
from mdflow.core.errors import ErrorCode, MdflowError
from tests.conftest import requires_soffice


def _ctx(data: bytes, fmt: str) -> ConversionContext:
    return ConversionContext(data=data, filename_hint=f"sample.{fmt}", format=fmt)


def test_protocol_attrs():
    conv = LibreOfficeConverter(timeout_s=120.0)
    assert conv.name == "office-libreoffice"
    assert conv.formats == ("doc", "ppt")
    assert conv.requires_gpu is False
    assert conv.can_handle(_ctx(b"", "doc")) is True
    assert conv.can_handle(_ctx(b"", "ppt")) is True
    assert conv.can_handle(_ctx(b"", "pdf")) is False


@requires_soffice
def test_doc_structure(sample_doc_bytes):
    out = LibreOfficeConverter(timeout_s=120.0).convert(
        _ctx(sample_doc_bytes, "doc"), lambda s, p: None
    )
    assert "Document Title" in out.markdown
    assert "Section One" in out.markdown
    assert "First paragraph of body text" in out.markdown
    assert out.metadata["source_format"] == "doc"
    assert out.metadata["engine"] == "libreoffice+pymupdf4llm"
    assert out.metadata["pages"] == 1


@requires_soffice
def test_ppt_structure(sample_ppt_bytes):
    out = LibreOfficeConverter(timeout_s=120.0).convert(
        _ctx(sample_ppt_bytes, "ppt"), lambda s, p: None
    )
    assert "First Slide" in out.markdown
    assert "Bullet one" in out.markdown
    assert out.metadata["source_format"] == "ppt"


@requires_soffice
def test_progress_is_monotonic_nondecreasing(sample_doc_bytes):
    seen: list[tuple[str, int]] = []
    LibreOfficeConverter(timeout_s=120.0).convert(
        _ctx(sample_doc_bytes, "doc"), lambda s, p: seen.append((s, p))
    )
    pcts = [p for _, p in seen]
    assert pcts == sorted(pcts)  # never goes backwards
    assert seen[-1][1] == 100


def test_missing_soffice_raises_libreoffice_unavailable():
    conv = LibreOfficeConverter(timeout_s=120.0)
    conv._soffice = None  # simulate a host without LibreOffice
    with pytest.raises(MdflowError) as exc:
        conv.convert(_ctx(b"anything", "doc"), lambda s, p: None)
    assert exc.value.code is ErrorCode.LIBREOFFICE_UNAVAILABLE


def test_soffice_timeout_raises_timeout(monkeypatch):
    conv = LibreOfficeConverter(timeout_s=1.0)
    conv._soffice = "/usr/bin/soffice"  # pretend it exists; run() is patched

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="soffice", timeout=1.0)

    monkeypatch.setattr("mdflow.converters.office.subprocess.run", fake_run)
    with pytest.raises(MdflowError) as exc:
        conv.convert(_ctx(b"anything", "doc"), lambda s, p: None)
    assert exc.value.code is ErrorCode.TIMEOUT
    assert exc.value.retryable is True


def test_soffice_nonzero_exit_raises_conversion_failed(monkeypatch):
    conv = LibreOfficeConverter(timeout_s=120.0)
    conv._soffice = "/usr/bin/soffice"

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=1, stdout=b"", stderr=b"boom")

    monkeypatch.setattr("mdflow.converters.office.subprocess.run", fake_run)
    with pytest.raises(MdflowError) as exc:
        conv.convert(_ctx(b"anything", "doc"), lambda s, p: None)
    assert exc.value.code is ErrorCode.CONVERSION_FAILED


def test_soffice_missing_output_raises_conversion_failed(monkeypatch):
    conv = LibreOfficeConverter(timeout_s=120.0)
    conv._soffice = "/usr/bin/soffice"

    # returncode 0 but no input.pdf is ever written into the temp dir.
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr("mdflow.converters.office.subprocess.run", fake_run)
    with pytest.raises(MdflowError) as exc:
        conv.convert(_ctx(b"anything", "doc"), lambda s, p: None)
    assert exc.value.code is ErrorCode.CONVERSION_FAILED
