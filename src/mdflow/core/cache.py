"""sha256 disk cache for conversion results.

PRD §9 + URL handling agreement §3.7:
- key = sha256(input_bytes || NUL || canonical_options_json || NUL || detected_format)
- detected_format is part of the key because the converter routed for
  the same bytes can differ by filename hint (e.g. ".txt" vs ".csv"),
  and those routes produce distinct outputs. Without it, the second
  request would get the first request's cached (wrong) result.
  (Codex review blocker #1, 2026-05-21)
- URL provenance (source_url/effective_url/...) is NOT in the key; it
  is reconciled at the request-metadata level by ConversionService
- entries are written atomically (tmp dir + os.replace) so a crash
  cannot leave a half-written meta.json
- sha values are validated as 64-char lowercase hex to prevent path
  traversal via crafted cache keys
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mdflow.converters.base import ConversionResult, ImageAsset
from mdflow.core.errors import ErrorCode, MdflowError

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def compute_cache_key(
    data: bytes,
    options: dict[str, Any],
    *,
    detected_format: str,
) -> str:
    canonical = json.dumps(options, sort_keys=True, separators=(",", ":")).encode("utf-8")
    h = hashlib.sha256()
    h.update(data)
    h.update(b"\x00")
    h.update(canonical)
    h.update(b"\x00")
    h.update(detected_format.encode("utf-8"))
    return h.hexdigest()


def _validate_sha(sha: str) -> None:
    if not _SHA256_RE.match(sha):
        raise ValueError(f"invalid sha256: {sha!r}")


@dataclass
class _Stats:
    hit_count: int = 0
    miss_count: int = 0


class Cache:
    """sha256-keyed disk cache; one directory per entry."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._stats = _Stats()

    def _entry_dir(self, sha: str) -> Path:
        _validate_sha(sha)
        return self.root / sha

    def write(self, sha: str, result: ConversionResult, options: dict[str, Any]) -> None:
        entry = self._entry_dir(sha)
        # mkdtemp() gives every writer a unique tmp dir under self.root, so
        # two concurrent writes against the same sha can't clobber a shared
        # `.tmp-{sha}` path. Publish (rmtree+os.replace) is still a two-step
        # operation, so a concurrent same-sha writer can still race at the
        # destination; under contention one writer succeeds and the other
        # surfaces CACHE_IO_ERROR. This is acceptable for M0 (sequential
        # API path; identical keys → identical converter output → next
        # request is a cache hit). Stronger publish atomicity is deferred
        # to M1+ (per-sha lock or first-writer-wins semantics change).
        tmp: Path | None = None
        try:
            tmp = Path(tempfile.mkdtemp(prefix=f".tmp-{sha}-", dir=self.root))
            (tmp / "result.md").write_text(result.markdown, encoding="utf-8")
            meta = {
                "sha256": sha,
                "options": options,
                "metadata": result.metadata,
                "assets": result.assets,
            }
            (tmp / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            if entry.exists():
                shutil.rmtree(entry)
            os.replace(tmp, entry)
        except OSError as e:
            # Best-effort cleanup of any partial tmp dir before surfacing
            # the standard retryable code (PRD §8.1).
            if tmp is not None and tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)
            raise MdflowError(
                ErrorCode.CACHE_IO_ERROR,
                f"cache entry {sha} unwritable: {e}",
            ) from e

    def write_canonical(
        self,
        sha: str,
        result: ConversionResult,
        *,
        options: dict[str, Any],
    ) -> None:
        """Atomic write: result.md + meta.json + figs/<image_name> for each unique ImageAsset.

        Disk write dedupes by ImageAsset.name (sha-based) — same-sha images
        written once even if the converter passes duplicates.

        Errors: OSError → MdflowError(CACHE_IO_ERROR), tmp dir cleaned up.
        """
        entry = self._entry_dir(sha)
        tmp: Path | None = None
        try:
            tmp = Path(tempfile.mkdtemp(prefix=f".tmp-{sha}-", dir=self.root))
            (tmp / "result.md").write_text(result.markdown, encoding="utf-8")
            # Dedupe images by name (sha-based) before writing meta + bytes
            seen: dict[str, ImageAsset] = {}
            for img in result.images:
                if img.name not in seen:
                    seen[img.name] = img
            unique_images = list(seen.values())
            meta = {
                "sha256": sha,
                "options": options,
                "metadata": result.metadata,
                "images": [
                    {"name": img.name, "content_type": img.content_type}
                    for img in unique_images
                ],
            }
            (tmp / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            if unique_images:
                figs = tmp / "figs"
                figs.mkdir()
                for img in unique_images:
                    (figs / img.name).write_bytes(img.data)
            if entry.exists():
                shutil.rmtree(entry)
            os.replace(tmp, entry)
        except OSError as e:
            if tmp is not None and tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)
            raise MdflowError(
                ErrorCode.CACHE_IO_ERROR,
                f"cache entry {sha} unwritable: {e}",
            ) from e

    def read_canonical(self, sha: str) -> ConversionResult | None:
        """Round-trip read. Returns None on cache miss.

        Backward compat: legacy M0-style entries with only `assets` in
        meta.json and no figs/ dir return ConversionResult(images=[]).
        """
        entry = self._entry_dir(sha)
        result_file = entry / "result.md"
        meta_file = entry / "meta.json"
        if not (result_file.exists() and meta_file.exists()):
            return None
        try:
            markdown = result_file.read_text(encoding="utf-8")
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise MdflowError(
                ErrorCode.CACHE_IO_ERROR,
                f"cache entry {sha} unreadable: {e}",
            ) from e

        images: list[ImageAsset] = []
        figs = entry / "figs"
        for img_meta in meta.get("images", []):
            name = img_meta["name"]
            path = figs / name
            try:
                data = path.read_bytes()
            except OSError as e:
                raise MdflowError(
                    ErrorCode.CACHE_IO_ERROR,
                    f"cache image {name} unreadable: {e}",
                ) from e
            images.append(
                ImageAsset(
                    name=name,
                    data=data,
                    content_type=img_meta["content_type"],
                )
            )

        return ConversionResult(
            markdown=markdown,
            metadata=meta.get("metadata", {}),
            images=images,
        )

    def build_bundle(self, sha: str) -> Path | None:
        """Lazy-build entry_dir/bundle.zip for mode=zip responses.

        Returns:
            None — cache miss, or canonical entry has zero images.
            Path — existing or newly built bundle.zip.

        Compression: ZIP_STORED (images already compressed; markdown is tiny).
        Concurrency: first-writer-wins (same as existing cache write semantics).
        """
        entry = self._entry_dir(sha)
        if not entry.exists():
            return None
        figs = entry / "figs"
        if not figs.exists() or not any(figs.iterdir()):
            return None
        bundle = entry / "bundle.zip"
        if bundle.exists():
            return bundle
        tmp: Path | None = None
        try:
            fd, tmp_name = tempfile.mkstemp(
                prefix=".tmp-bundle-", suffix=".zip", dir=str(entry)
            )
            os.close(fd)
            tmp = Path(tmp_name)
            with zipfile.ZipFile(tmp, mode="w", compression=zipfile.ZIP_STORED) as zf:
                zf.write(entry / "result.md", arcname="paper.md")
                zf.write(entry / "meta.json", arcname="meta.json")
                for img_path in sorted(figs.iterdir()):
                    zf.write(img_path, arcname=f"figs/{img_path.name}")
            os.replace(tmp, bundle)
            return bundle
        except OSError as e:
            if tmp is not None and tmp.exists():
                tmp.unlink(missing_ok=True)
            raise MdflowError(
                ErrorCode.CACHE_IO_ERROR,
                f"bundle build for {sha} failed: {e}",
            ) from e

    def read(self, sha: str) -> ConversionResult | None:
        entry = self._entry_dir(sha)
        result_file = entry / "result.md"
        meta_file = entry / "meta.json"
        if not (result_file.exists() and meta_file.exists()):
            self._stats.miss_count += 1
            return None
        # Disk I/O or a corrupted meta.json must surface as the standard
        # retryable code (PRD §8.1) — never a raw OSError or JSONDecodeError.
        try:
            markdown = result_file.read_text(encoding="utf-8")
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise MdflowError(
                ErrorCode.CACHE_IO_ERROR,
                f"cache entry {sha} unreadable: {e}",
            ) from e
        self._stats.hit_count += 1
        return ConversionResult(
            markdown=markdown,
            metadata=meta.get("metadata", {}),
            assets=meta.get("assets", []),
        )

    def cached_at(self, sha: str) -> str | None:
        """ISO-8601 (UTC) publish time of a cache entry, derived from the
        entry directory mtime (set by os.replace in write). None if absent.
        Used by the SSE `cached` event; the cache does not store a separate
        timestamp in meta.json.
        """
        entry = self._entry_dir(sha)
        if not entry.exists():
            return None
        ts = entry.stat().st_mtime
        return _dt.datetime.fromtimestamp(ts, tz=_dt.UTC).isoformat()

    def delete(self, sha: str) -> bool:
        entry = self._entry_dir(sha)
        if not entry.exists():
            return False
        shutil.rmtree(entry)
        return True

    def purge(self) -> int:
        count = 0
        for child in self.root.iterdir():
            if child.is_dir() and _SHA256_RE.match(child.name):
                shutil.rmtree(child)
                count += 1
        return count

    def stats(self) -> dict[str, Any]:
        entries = sum(1 for c in self.root.iterdir() if c.is_dir() and _SHA256_RE.match(c.name))
        size_mb = sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file()) / 1_048_576
        return {
            "entries": entries,
            "size_mb": round(size_mb, 3),
            "hit_count": self._stats.hit_count,
            "miss_count": self._stats.miss_count,
        }
