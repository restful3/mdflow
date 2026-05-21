"""ConversionService — entry point wiring cache, detection, and dispatch.

Incremental: this slice handles bytes-in requests. URL input is handled
by `mdflow.core.url_pipeline.convert_from_url`, which calls `fetch_url`,
builds a `ConvertRequest` (data + filename_hint + content_type_hint),
invokes `service.convert`, and composes the fetch metadata into a
sidecar `UrlConvertResponse.fetch` dict. The service itself does NOT
read URL provenance; it stays bytes-in / response-out.
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
    # Explicit HTTP `Content-Type` header from a URL fetch (agreement
    # §3.2 step 9 hint chain). None for local-file inputs.
    content_type_hint: str | None = None


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
        detection = detect_format(
            req.data,
            req.filename_hint,
            content_type_hint=req.content_type_hint,
        )
        if detection.format is None:
            raise MdflowError(
                ErrorCode.FORMAT_DETECT_FAILED,
                "extension and magic-bytes both unknown",
            )

        sha = compute_cache_key(req.data, req.options, detected_format=detection.format)

        cached = self.cache.read(sha)
        if cached is not None:
            return ConvertResponse(
                result=cached,
                sha256=sha,
                cached=True,
                detected_format=detection.format,
                converter_name=cached.metadata.get("converter", ""),
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
