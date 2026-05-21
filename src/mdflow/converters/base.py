"""Converter base types.

Incremental: this slice defines the data carriers (ConversionContext,
ConversionResult). The Converter Protocol — and the ProgressCallback
type — land in the follow-up step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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
