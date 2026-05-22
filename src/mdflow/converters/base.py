"""Converter base types.

Full set: ConversionContext, ConversionResult, ProgressCallback type
alias, and the Converter Protocol (runtime-checkable so the Registry
can validate registrations).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

# Progress callback: converters call this synchronously from WITHIN convert(),
# before convert() returns. The SSE pump (api/convert.py) relies on this:
# progress events are marshalled to the event loop via call_soon_threadsafe
# in FIFO order, so calling progress() after convert() returns (e.g. from a
# background thread) is OUTSIDE the contract and can drop the final event.
ProgressCallback = Callable[[str, int], None]


@dataclass
class ConversionContext:
    """Input passed to a converter."""

    data: bytes
    filename_hint: str | None
    format: str
    options: dict[str, Any] = field(default_factory=dict)
    tmp_path: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConversionResult:
    """Output produced by a converter; cached as-is."""

    markdown: str
    metadata: dict[str, Any] = field(default_factory=dict)
    assets: list[str] = field(default_factory=list)


@runtime_checkable
class Converter(Protocol):
    """A converter turns a `ConversionContext` into a `ConversionResult`."""

    name: str
    formats: tuple[str, ...]
    requires_gpu: bool

    def can_handle(self, ctx: ConversionContext) -> bool: ...

    def convert(self, ctx: ConversionContext, progress: ProgressCallback) -> ConversionResult: ...
