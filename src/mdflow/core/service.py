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

from mdflow.converters.base import ConversionContext, ConversionResult, Converter
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


@dataclass
class LookupResult:
    sha: str
    detected_format: str
    detection_source: str
    detection_warnings: list[str]
    cached: ConversionResult | None
    cached_at: str | None
    converter: Converter | None  # selected on miss; None on hit


class ConversionService:
    def __init__(self, registry: Registry, cache: Cache) -> None:
        self.registry = registry
        self.cache = cache

    def lookup(self, req: ConvertRequest) -> LookupResult:
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
            return LookupResult(
                sha=sha,
                detected_format=detection.format,
                detection_source=detection.source,
                detection_warnings=detection.warnings,
                cached=cached,
                cached_at=self.cache.cached_at(sha),
                converter=None,
            )
        ctx = ConversionContext(
            data=req.data,
            filename_hint=req.filename_hint,
            format=detection.format,
            options=req.options,
            metadata={"format": detection.format},
        )
        converter = self.registry.select(ctx)
        return LookupResult(
            sha=sha,
            detected_format=detection.format,
            detection_source=detection.source,
            detection_warnings=detection.warnings,
            cached=None,
            cached_at=None,
            converter=converter,
        )

    def run_conversion(
        self,
        req: ConvertRequest,
        lookup: LookupResult,
        progress: ProgressCallback = _noop_progress,
    ) -> ConvertResponse:
        assert lookup.converter is not None  # caller guarantees a miss
        ctx = ConversionContext(
            data=req.data,
            filename_hint=req.filename_hint,
            format=lookup.detected_format,
            options=req.options,
            metadata={"format": lookup.detected_format},
        )
        try:
            result = lookup.converter.convert(ctx, progress)
        except MdflowError:
            raise
        except Exception as e:
            raise MdflowError(ErrorCode.CONVERSION_FAILED, str(e)) from e

        enriched_meta = dict(result.metadata)
        enriched_meta.setdefault("converter", lookup.converter.name)
        enriched_meta.setdefault("format", lookup.detected_format)
        enriched_meta.setdefault("detection_source", lookup.detection_source)
        if lookup.detection_warnings:
            enriched_meta.setdefault("detection_warnings", lookup.detection_warnings)
        result = ConversionResult(
            markdown=result.markdown,
            metadata=enriched_meta,
            images=result.images,
        )

        self.cache.write(lookup.sha, result, options=req.options)
        return ConvertResponse(
            result=result,
            sha256=lookup.sha,
            cached=False,
            detected_format=lookup.detected_format,
            converter_name=lookup.converter.name,
        )

    def convert(
        self,
        req: ConvertRequest,
        progress: ProgressCallback = _noop_progress,
    ) -> ConvertResponse:
        lr = self.lookup(req)
        if lr.cached is not None:
            return ConvertResponse(
                result=lr.cached,
                sha256=lr.sha,
                cached=True,
                detected_format=lr.detected_format,
                converter_name=lr.cached.metadata.get("converter", ""),
            )
        return self.run_conversion(req, lr, progress)
