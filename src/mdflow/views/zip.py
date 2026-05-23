"""Mode=zip view synthesizer.

Returns (canonical_markdown_unchanged, bundle_path | None). The bundle
itself is built lazily by Cache.build_bundle — this module is a thin
adapter that fits the (str, Path|None) shape transport handlers consume.
"""

from __future__ import annotations

from pathlib import Path

from mdflow.core.cache import Cache


def synthesize(
    canonical_md: str, cache: Cache, sha: str
) -> tuple[str, Path | None]:
    bundle = cache.build_bundle(sha)
    return canonical_md, bundle
