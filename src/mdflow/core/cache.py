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

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mdflow.converters.base import ConversionResult

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
        tmp = self.root / f".tmp-{sha}"
        if tmp.exists():
            shutil.rmtree(tmp)
        tmp.mkdir(parents=True)
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

    def read(self, sha: str) -> ConversionResult | None:
        entry = self._entry_dir(sha)
        result_file = entry / "result.md"
        meta_file = entry / "meta.json"
        if not (result_file.exists() and meta_file.exists()):
            self._stats.miss_count += 1
            return None
        markdown = result_file.read_text(encoding="utf-8")
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        self._stats.hit_count += 1
        return ConversionResult(
            markdown=markdown,
            metadata=meta.get("metadata", {}),
            assets=meta.get("assets", []),
        )

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
