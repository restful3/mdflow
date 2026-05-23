"""pdf -> Markdown via Marker (GPU, high quality).

Registered ahead of PdfConverter in the runtime composition so the
Registry's first-wins + can_handle gating routes to Marker when a CUDA
GPU and the optional `[gpu]` extra are available, otherwise to PyMuPDF.

VRAM safety: ConcurrencyPool.gpu_semaphore(1) serialises the GPU branch
in api/convert.py; convert() additionally clears the model + CUDA cache
in a finally block (PaperFlow VRAM-leak avoidance, see CLAUDE.md).

Marker / torch are imported lazily inside the gating + pipeline helpers
so importing this module does NOT pull in the optional dependency.
"""

from __future__ import annotations

import gc
import os
import tempfile
from pathlib import Path
from typing import Any

from mdflow.converters.base import (
    ConversionContext,
    ConversionResult,
    ProgressCallback,
)

# ----- gating helpers (monkeypatched in tests) -----------------------------


def _force_cpu() -> bool:
    return os.environ.get("MDFLOW_FORCE_CPU", "").lower() in {"1", "true", "yes"}


def _cuda_available() -> bool:
    try:
        import torch  # type: ignore[import-not-found]
    except ImportError:
        return False
    try:
        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _marker_available() -> bool:
    try:
        import marker  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        return False
    return True


# ----- pipeline helpers (monkeypatched in tests) ---------------------------


def _load_models() -> Any:
    from marker.models import create_model_dict  # type: ignore[import-not-found]

    return create_model_dict()


def _marker_convert(pdf_path: Path, models: Any) -> Any:
    from marker.converters.pdf import (  # type: ignore[import-not-found]
        PdfConverter as _MarkerPdfConverter,
    )

    return _MarkerPdfConverter(artifact_dict=models)(str(pdf_path))


def _text_from_rendered(rendered: Any) -> tuple[str, Any, Any]:
    from marker.output import text_from_rendered  # type: ignore[import-not-found]

    return text_from_rendered(rendered)


def _cleanup_vram() -> None:
    gc.collect()
    try:
        import torch  # type: ignore[import-not-found]

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


# ----- converter -----------------------------------------------------------


class MarkerConverter:
    name = "pdf-marker"
    formats: tuple[str, ...] = ("pdf",)
    requires_gpu = True

    def can_handle(self, ctx: ConversionContext) -> bool:
        if ctx.format not in self.formats:
            return False
        if _force_cpu():
            return False
        if not _cuda_available():
            return False
        return _marker_available()

    def convert(self, ctx: ConversionContext, progress: ProgressCallback) -> ConversionResult:
        progress("load", 5)
        models = None
        try:
            models = _load_models()
            progress("parse", 20)
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                f.write(ctx.data)
                tmp = Path(f.name)
            try:
                progress("render", 50)
                rendered = _marker_convert(tmp, models)
                text, _, _images = _text_from_rendered(rendered)
            finally:
                tmp.unlink(missing_ok=True)
            pages = len(getattr(rendered, "metadata", {}).get("page_stats", []))
            progress("done", 100)
            return ConversionResult(
                markdown=text.strip(),
                metadata={"engine": "marker", "pages": pages},
            )
        finally:
            del models
            _cleanup_vram()
