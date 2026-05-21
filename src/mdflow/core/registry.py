"""Converter registry — registration + format-based dispatch.

Full v1 surface: register(), select() (UNSUPPORTED_FORMAT on miss,
first-registered-wins on ties), list_formats() (one row per
(converter, advertised format) for /capabilities).
"""

from __future__ import annotations

from mdflow.converters.base import ConversionContext, Converter
from mdflow.core.errors import ErrorCode, MdflowError


class Registry:
    """Holds converter instances and dispatches on `ConversionContext.format`."""

    def __init__(self) -> None:
        self._converters: list[Converter] = []

    def register(self, converter: Converter) -> Converter:
        self._converters.append(converter)
        return converter

    def select(self, ctx: ConversionContext) -> Converter:
        for c in self._converters:
            if ctx.format in c.formats and c.can_handle(ctx):
                return c
        raise MdflowError(
            ErrorCode.UNSUPPORTED_FORMAT,
            f"no converter for format={ctx.format!r}",
        )

    def list_formats(self) -> list[dict]:
        """Enumerate (ext, converter, requires_gpu) rows in registration order.

        Used by `/capabilities`. Each advertised format produces one row, so a
        fallback chain (e.g. PDF: Marker then PyMuPDF) shows up as multiple
        rows for the same ext.
        """
        rows: list[dict] = []
        for c in self._converters:
            for ext in c.formats:
                rows.append({"ext": ext, "converter": c.name, "requires_gpu": c.requires_gpu})
        return rows
