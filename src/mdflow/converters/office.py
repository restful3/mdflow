"""doc/ppt -> Markdown via LibreOffice headless -> PDF -> pymupdf4llm.

soffice converts the legacy binary office format to PDF in a temp dir
(per-call UserInstallation profile so concurrent conversions don't
collide on LibreOffice's shared profile lock); the produced PDF is then
handed to the existing PdfConverter via composition with a remapped
progress callback. No internal try/except that swallows errors: a
missing soffice raises LIBREOFFICE_UNAVAILABLE, a timeout raises TIMEOUT,
a nonzero exit / missing output raises CONVERSION_FAILED; PDF-stage
library errors propagate to ConversionService.run_conversion.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from mdflow.converters.base import (
    ConversionContext,
    ConversionResult,
    ProgressCallback,
)
from mdflow.converters.pdf import PdfConverter
from mdflow.core.errors import ErrorCode, MdflowError


class LibreOfficeConverter:
    name = "office-libreoffice"
    formats: tuple[str, ...] = ("doc", "ppt")
    requires_gpu = False

    def __init__(self, timeout_s: float, pdf: PdfConverter | None = None) -> None:
        self._soffice = shutil.which("soffice")
        self._timeout_s = timeout_s
        self._pdf = pdf or PdfConverter()

    def can_handle(self, ctx: ConversionContext) -> bool:
        return ctx.format in self.formats

    def convert(self, ctx: ConversionContext, progress: ProgressCallback) -> ConversionResult:
        if self._soffice is None:
            raise MdflowError(
                ErrorCode.LIBREOFFICE_UNAVAILABLE,
                "soffice (LibreOffice) not found on PATH",
            )
        progress("convert", 5)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / f"input.{ctx.format}"
            src.write_bytes(ctx.data)
            profile = f"-env:UserInstallation=file://{tmp_path / 'lo_profile'}"
            try:
                proc = subprocess.run(
                    [
                        self._soffice,
                        "--headless",
                        "--convert-to",
                        "pdf",
                        "--outdir",
                        str(tmp_path),
                        profile,
                        str(src),
                    ],
                    capture_output=True,
                    timeout=self._timeout_s,
                    check=False,
                )
            except subprocess.TimeoutExpired as e:
                raise MdflowError(
                    ErrorCode.TIMEOUT,
                    f"soffice timed out after {self._timeout_s}s",
                ) from e
            pdf_path = tmp_path / "input.pdf"
            if proc.returncode != 0 or not pdf_path.exists():
                stderr = proc.stderr.decode("utf-8", "replace").strip()
                raise MdflowError(
                    ErrorCode.CONVERSION_FAILED,
                    f"soffice failed (rc={proc.returncode}): {stderr[:500]}",
                )
            pdf_bytes = pdf_path.read_bytes()
        progress("convert", 50)
        pdf_ctx = ConversionContext(
            data=pdf_bytes,
            filename_hint="input.pdf",
            format="pdf",
            options=ctx.options,
            metadata={"format": "pdf"},
        )
        pdf_result = self._pdf.convert(pdf_ctx, lambda s, p: progress(s, 50 + p // 2))
        return ConversionResult(
            markdown=pdf_result.markdown,
            metadata={
                "source_format": ctx.format,
                "engine": "libreoffice+pymupdf4llm",
                "pages": pdf_result.metadata.get("pages"),
            },
        )
