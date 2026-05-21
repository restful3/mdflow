"""ConversionService — entry point wiring cache, detection, and dispatch.

Incremental: this slice handles bytes-in requests. URL input (fetch via
`mdflow.core.url_fetch`) is owned by the API layer in Task 14, which
converts a `{url}` request into a `ConvertRequest` (data + filename_hint
+ fetch metadata) before calling `service.convert`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from mdflow.converters.base import ConversionContext, ConversionResult
from mdflow.core.cache import Cache, compute_cache_key
from mdflow.core.errors import ErrorCode, MdflowError
from mdflow.core.format_detect import detect_format
from mdflow.core.registry import Registry

ProgressCallback = Callable[[str, int], None]


def _noop_progress(stage: str, pct: int) -> None:
    return None


@dataclass
class ConvertRequest:
    data: bytes
    filename_hint: str | None
    options: dict[str, Any] = field(default_factory=dict)
    # Populated by the API layer when the input is a URL (Task 14).
    fetch_metadata: dict[str, Any] | None = None


@dataclass
class ConvertResponse:
    result: ConversionResult
    sha256: str
    cached: bool
    detected_format: str
    converter_name: str


class ConversionService:
    def __init__(self, registry: Registry, cache: Cache) -> None:
        self.registry = registry
        self.cache = cache

    def convert(
        self,
        req: ConvertRequest,
        progress: ProgressCallback = _noop_progress,
    ) -> ConvertResponse:
        sha = compute_cache_key(req.data, req.options)

        cached = self.cache.read(sha)
        if cached is not None:
            return ConvertResponse(
                result=cached,
                sha256=sha,
                cached=True,
                detected_format=cached.metadata.get("format", ""),
                converter_name=cached.metadata.get("converter", ""),
            )

        detection = detect_format(req.data, req.filename_hint)
        if detection.format is None:
            raise MdflowError(
                ErrorCode.FORMAT_DETECT_FAILED,
                "extension and magic-bytes both unknown",
            )

        ctx = ConversionContext(
            data=req.data,
            filename_hint=req.filename_hint,
            format=detection.format,
            options=req.options,
            metadata={"format": detection.format},
        )
        converter = self.registry.select(ctx)
        result = converter.convert(ctx, progress)

        enriched_meta = dict(result.metadata)
        enriched_meta.setdefault("converter", converter.name)
        enriched_meta.setdefault("format", detection.format)
        enriched_meta.setdefault("detection_source", detection.source)
        if detection.warnings:
            enriched_meta.setdefault("detection_warnings", detection.warnings)
        result = ConversionResult(
            markdown=result.markdown,
            metadata=enriched_meta,
            assets=result.assets,
        )

        self.cache.write(sha, result, options=req.options)
        return ConvertResponse(
            result=result,
            sha256=sha,
            cached=False,
            detected_format=detection.format,
            converter_name=converter.name,
        )
