"""Converter registry — registration + format-based dispatch.

Incremental: this slice covers register() and select() (with
UNSUPPORTED_FORMAT on miss and first-registered-wins on ties).
list_formats() — used by the /capabilities endpoint — lands next.
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
