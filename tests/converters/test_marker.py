"""Tests for the Marker (GPU) PDF converter.

The unit tests monkeypatch the gating helpers (`_force_cpu`,
`_cuda_available`, `_marker_available`) so the suite is deterministic
regardless of whether torch/CUDA/marker-pdf are installed on the host.

The end-to-end conversion is checked via `_load_models` /
`_marker_convert` / `_text_from_rendered` stubs in the unit layer, and
once via a real GPU smoke test gated behind `requires_gpu_runtime`
(skipped if torch+CUDA or marker-pdf is missing).
"""

from __future__ import annotations

from typing import Any

import pytest

from mdflow.converters import marker as marker_mod
from mdflow.converters.base import ConversionContext
from mdflow.converters.marker import MarkerConverter
from tests.conftest import requires_gpu_runtime


def _ctx(data: bytes = b"%PDF-1.4\n%%EOF\n", fmt: str = "pdf") -> ConversionContext:
    return ConversionContext(data=data, filename_hint="sample.pdf", format=fmt)


def test_protocol_attrs():
    conv = MarkerConverter()
    assert conv.name == "pdf-marker"
    assert conv.formats == ("pdf",)
    assert conv.requires_gpu is True


def _patch_gates(
    monkeypatch: pytest.MonkeyPatch,
    *,
    force_cpu: bool = False,
    cuda: bool = True,
    marker: bool = True,
) -> None:
    monkeypatch.setattr(marker_mod, "_force_cpu", lambda: force_cpu)
    monkeypatch.setattr(marker_mod, "_cuda_available", lambda: cuda)
    monkeypatch.setattr(marker_mod, "_marker_available", lambda: marker)


def test_can_handle_all_gates_pass(monkeypatch):
    _patch_gates(monkeypatch)
    assert MarkerConverter().can_handle(_ctx()) is True


def test_can_handle_rejects_non_pdf(monkeypatch):
    _patch_gates(monkeypatch)
    assert MarkerConverter().can_handle(_ctx(fmt="docx")) is False


def test_can_handle_force_cpu_blocks(monkeypatch):
    _patch_gates(monkeypatch, force_cpu=True)
    assert MarkerConverter().can_handle(_ctx()) is False


def test_can_handle_no_cuda_blocks(monkeypatch):
    _patch_gates(monkeypatch, cuda=False)
    assert MarkerConverter().can_handle(_ctx()) is False


def test_can_handle_no_marker_blocks(monkeypatch):
    _patch_gates(monkeypatch, marker=False)
    assert MarkerConverter().can_handle(_ctx()) is False


# --- convert() with stubbed marker pipeline ---------------------------------


class _FakeRendered:
    """Stand-in for marker's rendered object; metadata shape mirrors marker."""

    def __init__(self, text: str, pages: int) -> None:
        self._text = text
        self.metadata = {"page_stats": [{"page": i} for i in range(pages)]}


def _patch_marker_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    *,
    text: str = "# Hello\n\nWorld\n",
    pages: int = 2,
    load_raises: BaseException | None = None,
    convert_raises: BaseException | None = None,
) -> dict[str, Any]:
    """Stub `_load_models`/`_marker_convert`/`_text_from_rendered` and record calls."""
    state: dict[str, Any] = {"load": 0, "convert": 0, "cleanup": 0}

    def _load() -> object:
        state["load"] += 1
        if load_raises is not None:
            raise load_raises
        return {"fake": "models"}

    def _convert(path: Any, models: Any) -> _FakeRendered:
        state["convert"] += 1
        state["last_path"] = path
        state["last_models"] = models
        if convert_raises is not None:
            raise convert_raises
        return _FakeRendered(text, pages)

    def _text(rendered: _FakeRendered) -> tuple[str, dict, dict]:
        return rendered._text, {}, {}

    def _cleanup() -> None:
        state["cleanup"] += 1

    monkeypatch.setattr(marker_mod, "_load_models", _load)
    monkeypatch.setattr(marker_mod, "_marker_convert", _convert)
    monkeypatch.setattr(marker_mod, "_text_from_rendered", _text)
    monkeypatch.setattr(marker_mod, "_cleanup_vram", _cleanup)
    return state


def test_convert_happy_path(monkeypatch):
    state = _patch_marker_pipeline(monkeypatch, text="# Title\n\nBody.\n", pages=3)
    seen: list[tuple[str, int]] = []
    out = MarkerConverter().convert(_ctx(b"%PDF-fake"), lambda s, p: seen.append((s, p)))
    assert out.markdown == "# Title\n\nBody."
    assert out.metadata["engine"] == "marker"
    assert out.metadata["pages"] == 3
    assert seen[-1] == ("done", 100)
    assert state["load"] == 1
    assert state["convert"] == 1
    assert state["cleanup"] == 1  # VRAM cleanup always runs


def test_convert_writes_bytes_to_path(monkeypatch):
    state = _patch_marker_pipeline(monkeypatch)
    payload = b"%PDF-1.4\nhello-from-test\n"
    MarkerConverter().convert(_ctx(payload), lambda s, p: None)
    # marker received a real file path containing our bytes (then deleted)
    last = state["last_path"]
    assert last is not None
    # path object handed to _marker_convert; file no longer on disk (finally cleanup)
    assert not last.exists()


def test_convert_propagates_marker_errors(monkeypatch):
    state = _patch_marker_pipeline(monkeypatch, convert_raises=RuntimeError("CUDA OOM"))
    with pytest.raises(RuntimeError, match="CUDA OOM"):
        MarkerConverter().convert(_ctx(), lambda s, p: None)
    assert state["cleanup"] == 1  # cleanup runs even on error


def test_convert_propagates_load_errors(monkeypatch):
    state = _patch_marker_pipeline(monkeypatch, load_raises=ImportError("no marker"))
    with pytest.raises(ImportError):
        MarkerConverter().convert(_ctx(), lambda s, p: None)
    # cleanup still runs because finally guards the whole try block
    assert state["cleanup"] == 1


# --- real GPU smoke (skipped if torch+CUDA or marker-pdf missing) ----------


@pytest.mark.gpu
@requires_gpu_runtime
def test_marker_real_gpu_smoke(monkeypatch, sample_pdf_bytes):
    """End-to-end: code-generated PDF -> Marker on GPU -> Markdown."""
    # Opt out of the suite-wide MDFLOW_FORCE_CPU=1 autouse fixture.
    monkeypatch.delenv("MDFLOW_FORCE_CPU", raising=False)
    conv = MarkerConverter()
    assert conv.can_handle(_ctx(sample_pdf_bytes)) is True
    out = conv.convert(_ctx(sample_pdf_bytes), lambda s, p: None)
    assert isinstance(out.markdown, str)
    assert out.metadata["engine"] == "marker"
    # The code-generated fixture contains "Document Title"; Marker should
    # surface that text somewhere in its Markdown output.
    assert "Document Title" in out.markdown
