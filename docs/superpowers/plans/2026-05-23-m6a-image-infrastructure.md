# M6a Implementation Plan — Image Support Infrastructure

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the canonical-form + view-synthesis + canonical-cache infrastructure that all 9 mdflow converters will eventually feed (M6b\~M6d). No API surface changes, no converter changes — pure backend foundation that keeps the existing 304 tests green.

**Architecture:** Add `ImageAsset` dataclass + `ConversionResult.images: list[ImageAsset]` field (additive in Tasks 1-8). Add `_image_util.py` for sha-based naming. Extend `Cache` with `write_canonical/read_canonical/build_bundle` (Tasks 3-5, alongside existing methods). Add `views.{none,embed,zip}` packages for mode-specific output synthesis (Tasks 6-8). Final Task 9 migrates `ConversionService` + API to the canonical API and removes `ConversionResult.assets`.

**Tech Stack:** Python 3.12, `dataclasses`, `hashlib`, `zipfile` (`ZIP_STORED`), pytest, ruff. No new runtime dependencies.

**Spec:** `docs/specs/2026-05-23-m6-image-support-design.md` (sections 4, 5, 7 are the binding contracts for this plan).

**Out of scope (deferred to M6b\~M6f):** No converter changes (no image extraction yet). No `options.images` handling in HTTP/MCP/CLI. No `GET /cache/<sha>/bundle.zip` endpoint. No `done.bundle_url` field. No `--images` CLI flag.

---

## File Structure

**Create:**

- `src/mdflow/converters/_image_util.py` — sha_filename, make_image_asset, canonical_ref, content_type_to_ext
- `src/mdflow/views/__init__.py` — package marker
- `src/mdflow/views/none.py` — mode=none view synthesizer (image refs removed)
- `src/mdflow/views/embed.py` — mode=embed view synthesizer (refs → base64 data URI)
- `src/mdflow/views/zip.py` — mode=zip view synthesizer (canonical + bundle.zip path)
- `tests/converters/test_image_util.py` — unit tests for image helpers
- `tests/views/__init__.py` — test package marker
- `tests/views/test_none.py` — none.synthesize tests
- `tests/views/test_embed.py` — embed.synthesize tests
- `tests/views/test_zip.py` — zip.synthesize tests
- `tests/test_cache_canonical.py` — write_canonical / read_canonical / build_bundle tests

**Modify:**

- `src/mdflow/converters/base.py` — add `ImageAsset`; add `ConversionResult.images` field (Task 1, additive). Remove `assets` field (Task 9).
- `src/mdflow/core/cache.py` — add `write_canonical/read_canonical/build_bundle` (Tasks 3-5, additive). In Task 9, rename canonical methods to replace existing `write/read`.
- `src/mdflow/core/service.py` — Task 9 only: switch to canonical API + propagate images.
- `src/mdflow/api/convert.py` — Task 9 only: `Done(assets=[])` shim.
- `src/mdflow/api/admin.py` — Task 9 only: `"assets": []` shim in GET /cache/{sha}.
- `tests/converters/test_base.py` — Task 1 adds tests, Task 9 removes assets-specific tests.
- `tests/test_cache.py` — Task 9: migrate `got.assets == [...]` assertions to `got.images`.

`src/mdflow/converters/{text,docx,pptx,xlsx,html,hwp,office,pdf,marker}.py` — **untouched** in M6a.

---

## Task 1: Add `ImageAsset` + extend `ConversionResult.images`

**Files:**
- Modify: `src/mdflow/converters/base.py`
- Test: `tests/converters/test_base.py`

This task is purely additive: `assets: list[str]` field stays for now (removed in Task 9). New `images: list[ImageAsset]` field defaults to empty list.

- [ ] **Step 1: Write failing tests**

Append to `tests/converters/test_base.py`:

```python
import pytest

from mdflow.converters.base import ImageAsset


def test_image_asset_is_frozen_dataclass():
    a = ImageAsset(name="abc.png", data=b"\x89PNG", content_type="image/png")
    with pytest.raises(Exception):
        a.name = "x"  # frozen=True → FrozenInstanceError


def test_image_asset_fields():
    a = ImageAsset(name="x.jpg", data=b"jpegdata", content_type="image/jpeg")
    assert a.name == "x.jpg"
    assert a.data == b"jpegdata"
    assert a.content_type == "image/jpeg"


def test_conversion_result_images_default_empty():
    from mdflow.converters.base import ConversionResult
    r = ConversionResult(markdown="x", metadata={})
    assert r.images == []


def test_conversion_result_images_field_accepts_list():
    from mdflow.converters.base import ConversionResult
    a = ImageAsset(name="a.png", data=b"d", content_type="image/png")
    r = ConversionResult(markdown="x", metadata={}, images=[a])
    assert r.images == [a]
```

- [ ] **Step 2: Run tests, expect failure**

Run: `.venv/bin/pytest tests/converters/test_base.py -v -k 'image_asset or images'`
Expected: 4 FAILED with `ImportError: cannot import name 'ImageAsset'` and `TypeError: __init__() got an unexpected keyword argument 'images'`.

- [ ] **Step 3: Implement**

Edit `src/mdflow/converters/base.py`. Add `ImageAsset` and extend `ConversionResult` (keep `assets` for now):

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ImageAsset:
    """Content-addressed image extracted by a converter.

    `name` is a sha-based filename (see _image_util.sha_filename). Same
    image bytes from any source produce the same `name`, enabling disk
    dedup in the cache's figs/ directory.
    """

    name: str
    data: bytes
    content_type: str


@dataclass
class ConversionResult:
    markdown: str
    metadata: dict[str, Any]
    assets: list[str] = field(default_factory=list)  # DEPRECATED, removed in Task 9
    images: list[ImageAsset] = field(default_factory=list)
```

(Preserve the rest of the file. `Converter` Protocol and `Context` dataclass stay untouched.)

- [ ] **Step 4: Run tests, expect pass**

Run: `.venv/bin/pytest tests/converters/test_base.py -v`
Expected: all PASS including existing `r.assets` tests (still untouched).

- [ ] **Step 5: Full suite + ruff**

Run: `.venv/bin/pytest -q && .venv/bin/ruff check src tests`
Expected: 304 passed/2 skipped (existing) + 4 new passed = 308 passed/2 skipped. ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/mdflow/converters/base.py tests/converters/test_base.py
git commit -m "feat(m6a): add ImageAsset + ConversionResult.images field (additive)

ImageAsset frozen dataclass with name/data/content_type. ConversionResult
gains images: list[ImageAsset] alongside existing assets (deprecated,
removed in Task 9). All 9 converters still produce images=[] until
M6b~M6d.

Spec: docs/specs/2026-05-23-m6-image-support-design.md §4.2"
```

---

## Task 2: `_image_util.py` — sha-based naming + canonical ref helpers

**Files:**
- Create: `src/mdflow/converters/_image_util.py`
- Create: `tests/converters/test_image_util.py`

- [ ] **Step 1: Write failing tests**

Create `tests/converters/test_image_util.py`:

```python
import hashlib

import pytest

from mdflow.converters._image_util import (
    EXT_BY_CT,
    canonical_ref,
    content_type_to_ext,
    make_image_asset,
    sha_filename,
)


def test_content_type_to_ext_png():
    assert content_type_to_ext("image/png") == "png"


def test_content_type_to_ext_jpeg():
    assert content_type_to_ext("image/jpeg") == "jpg"


def test_content_type_to_ext_svg():
    assert content_type_to_ext("image/svg+xml") == "svg"


def test_content_type_to_ext_unknown_falls_back_to_bin():
    assert content_type_to_ext("application/octet-stream") == "bin"


def test_content_type_to_ext_case_insensitive():
    assert content_type_to_ext("IMAGE/PNG") == "png"


def test_sha_filename_is_sha256_plus_ext():
    data = b"hello world"
    expected = hashlib.sha256(data).hexdigest()
    assert sha_filename(data, "image/png") == f"{expected}.png"


def test_sha_filename_same_bytes_different_ct_same_digest():
    data = b"x"
    n_png = sha_filename(data, "image/png")
    n_jpg = sha_filename(data, "image/jpeg")
    assert n_png.split(".")[0] == n_jpg.split(".")[0]
    assert n_png.endswith(".png") and n_jpg.endswith(".jpg")


def test_make_image_asset_uses_sha_filename():
    a = make_image_asset(b"data", "image/png")
    assert a.name == sha_filename(b"data", "image/png")
    assert a.data == b"data"
    assert a.content_type == "image/png"


def test_canonical_ref_with_alt():
    a = make_image_asset(b"d", "image/png")
    assert canonical_ref(a, alt="A photo") == f"![A photo](figs/{a.name})"


def test_canonical_ref_no_alt_defaults_to_empty():
    a = make_image_asset(b"d", "image/png")
    assert canonical_ref(a) == f"![](figs/{a.name})"


def test_ext_by_ct_covers_spec_minimum():
    # spec §7.1 enumerates these — exact set guarded
    expected = {"image/png", "image/jpeg", "image/jpg", "image/gif",
                "image/svg+xml", "image/webp", "image/bmp", "image/tiff"}
    assert expected.issubset(EXT_BY_CT.keys())
```

- [ ] **Step 2: Run tests, expect failure**

Run: `.venv/bin/pytest tests/converters/test_image_util.py -v`
Expected: 11 FAILED with `ModuleNotFoundError: No module named 'mdflow.converters._image_util'`.

- [ ] **Step 3: Implement**

Create `src/mdflow/converters/_image_util.py`:

```python
"""Shared helpers for image asset handling.

Content-addressed naming (sha256 of bytes + ext from content-type) gives
mdflow disk-level dedup across documents and converters. canonical_ref
emits the standard `![alt](figs/<name>)` form that view synthesis
modules parse later.
"""

from __future__ import annotations

import hashlib

from mdflow.converters.base import ImageAsset

EXT_BY_CT: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/gif": "gif",
    "image/svg+xml": "svg",
    "image/webp": "webp",
    "image/bmp": "bmp",
    "image/tiff": "tiff",
}


def content_type_to_ext(content_type: str) -> str:
    return EXT_BY_CT.get(content_type.lower(), "bin")


def sha_filename(data: bytes, content_type: str) -> str:
    digest = hashlib.sha256(data).hexdigest()
    return f"{digest}.{content_type_to_ext(content_type)}"


def make_image_asset(data: bytes, content_type: str) -> ImageAsset:
    return ImageAsset(
        name=sha_filename(data, content_type),
        data=data,
        content_type=content_type,
    )


def canonical_ref(asset: ImageAsset, alt: str = "") -> str:
    return f"![{alt}](figs/{asset.name})"
```

- [ ] **Step 4: Run tests, expect pass**

Run: `.venv/bin/pytest tests/converters/test_image_util.py -v`
Expected: 11 PASS.

- [ ] **Step 5: Full suite + ruff**

Run: `.venv/bin/pytest -q && .venv/bin/ruff check src tests`
Expected: 319 passed/2 skipped. ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/mdflow/converters/_image_util.py tests/converters/test_image_util.py
git commit -m "feat(m6a): _image_util — sha-based image naming + canonical refs

EXT_BY_CT covers PNG/JPEG/GIF/SVG/WEBP/BMP/TIFF. sha_filename uses
sha256(bytes).hexdigest() + ext. canonical_ref emits standard
![alt](figs/<sha>.<ext>) form.

Spec: docs/specs/2026-05-23-m6-image-support-design.md §7.1"
```

---

## Task 3: `Cache.write_canonical` — atomic write + figs/ dedup

**Files:**
- Modify: `src/mdflow/core/cache.py` (add new method, do not touch existing `write`)
- Test: `tests/test_cache_canonical.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_cache_canonical.py`:

```python
import json
from pathlib import Path

import pytest

from mdflow.converters._image_util import make_image_asset
from mdflow.converters.base import ConversionResult
from mdflow.core.cache import Cache
from mdflow.core.errors import ErrorCode, MdflowError


@pytest.fixture
def cache(tmp_path: Path) -> Cache:
    return Cache(tmp_path)


def test_write_canonical_no_images_creates_md_and_meta(cache, tmp_path):
    sha = "a" * 64
    r = ConversionResult(markdown="hello", metadata={"x": 1}, images=[])
    cache.write_canonical(sha, r, options={})
    entry = tmp_path / sha
    assert (entry / "result.md").read_text() == "hello"
    meta = json.loads((entry / "meta.json").read_text())
    assert meta["sha256"] == sha
    assert meta["metadata"] == {"x": 1}
    assert meta["images"] == []
    assert not (entry / "figs").exists()


def test_write_canonical_with_images_creates_figs(cache, tmp_path):
    sha = "b" * 64
    img1 = make_image_asset(b"png-1", "image/png")
    img2 = make_image_asset(b"jpg-2", "image/jpeg")
    r = ConversionResult(
        markdown=f"![](figs/{img1.name}) ![](figs/{img2.name})",
        metadata={},
        images=[img1, img2],
    )
    cache.write_canonical(sha, r, options={})
    figs = tmp_path / sha / "figs"
    assert figs.is_dir()
    assert (figs / img1.name).read_bytes() == b"png-1"
    assert (figs / img2.name).read_bytes() == b"jpg-2"
    meta = json.loads((tmp_path / sha / "meta.json").read_text())
    assert meta["images"] == [
        {"name": img1.name, "content_type": "image/png"},
        {"name": img2.name, "content_type": "image/jpeg"},
    ]


def test_write_canonical_dedupes_same_sha(cache, tmp_path):
    sha = "c" * 64
    img = make_image_asset(b"shared", "image/png")
    r = ConversionResult(
        markdown=f"![](figs/{img.name}) ![](figs/{img.name})",
        metadata={},
        images=[img, img],
    )
    cache.write_canonical(sha, r, options={})
    figs = tmp_path / sha / "figs"
    assert len(list(figs.iterdir())) == 1


def test_write_canonical_oserror_wrapped_and_tmp_cleaned(cache, tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("fake replace failure")
    monkeypatch.setattr("mdflow.core.cache.os.replace", boom)
    sha = "d" * 64
    r = ConversionResult(markdown="x", metadata={}, images=[])
    with pytest.raises(MdflowError) as exc:
        cache.write_canonical(sha, r, options={})
    assert exc.value.code is ErrorCode.CACHE_IO_ERROR
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".tmp-")]
    assert leftovers == []
```

- [ ] **Step 2: Run tests, expect failure**

Run: `.venv/bin/pytest tests/test_cache_canonical.py -v`
Expected: 4 FAILED with `AttributeError: 'Cache' object has no attribute 'write_canonical'`.

- [ ] **Step 3: Implement**

Edit `src/mdflow/core/cache.py`. Add `write_canonical` method to the `Cache` class (do not delete existing `write`):

```python
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
```

Add this import at the top of `src/mdflow/core/cache.py` if not already present:

```python
from mdflow.converters.base import ConversionResult, ImageAsset
```

- [ ] **Step 4: Run tests, expect pass**

Run: `.venv/bin/pytest tests/test_cache_canonical.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Full suite + ruff**

Run: `.venv/bin/pytest -q && .venv/bin/ruff check src tests`
Expected: 323 passed/2 skipped. ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/mdflow/core/cache.py tests/test_cache_canonical.py
git commit -m "feat(m6a): Cache.write_canonical — atomic write with figs/ dedup

Adds figs/ subdirectory containing dedup'd image bytes (by sha-based
name). meta.json gains 'images' field (list of {name, content_type}).
Mirrors existing write_atomic pattern (mkdtemp + os.replace, OSError
wrapping). Old Cache.write untouched — Task 9 migrates callers.

Spec: docs/specs/2026-05-23-m6-image-support-design.md §4.4, §5"
```

---

## Task 4: `Cache.read_canonical` — round-trip + backward compat

**Files:**
- Modify: `src/mdflow/core/cache.py` (add new method)
- Test: `tests/test_cache_canonical.py` (append tests)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cache_canonical.py`:

```python
def test_read_canonical_round_trip(cache, tmp_path):
    sha = "e" * 64
    img = make_image_asset(b"data", "image/png")
    r = ConversionResult(
        markdown=f"![](figs/{img.name})",
        metadata={"k": "v"},
        images=[img],
    )
    cache.write_canonical(sha, r, options={})
    got = cache.read_canonical(sha)
    assert got is not None
    assert got.markdown == r.markdown
    assert got.metadata == {"k": "v"}
    assert len(got.images) == 1
    assert got.images[0].name == img.name
    assert got.images[0].data == b"data"
    assert got.images[0].content_type == "image/png"


def test_read_canonical_miss_returns_none(cache):
    assert cache.read_canonical("f" * 64) is None


def test_read_canonical_legacy_no_figs_meta_assets_returns_empty_images(cache, tmp_path):
    """M0-style entry — meta.json has 'assets' key, no figs/ dir → images=[]."""
    sha = "1" + "0" * 63
    entry = tmp_path / sha
    entry.mkdir()
    (entry / "result.md").write_text("legacy markdown")
    (entry / "meta.json").write_text(json.dumps({
        "sha256": sha,
        "options": {},
        "metadata": {"converter": "old"},
        "assets": [],  # legacy field
    }))
    got = cache.read_canonical(sha)
    assert got is not None
    assert got.markdown == "legacy markdown"
    assert got.metadata == {"converter": "old"}
    assert got.images == []


def test_read_canonical_corrupt_meta_raises(cache, tmp_path):
    sha = "2" + "0" * 63
    entry = tmp_path / sha
    entry.mkdir()
    (entry / "result.md").write_text("x")
    (entry / "meta.json").write_text("not json {")
    with pytest.raises(MdflowError) as exc:
        cache.read_canonical(sha)
    assert exc.value.code is ErrorCode.CACHE_IO_ERROR


def test_read_canonical_missing_image_bytes_raises(cache, tmp_path):
    sha = "3" + "0" * 63
    entry = tmp_path / sha
    entry.mkdir()
    (entry / "result.md").write_text("![](figs/x.png)")
    (entry / "meta.json").write_text(json.dumps({
        "sha256": sha,
        "options": {},
        "metadata": {},
        "images": [{"name": "x.png", "content_type": "image/png"}],
    }))
    # figs/x.png is missing
    with pytest.raises(MdflowError) as exc:
        cache.read_canonical(sha)
    assert exc.value.code is ErrorCode.CACHE_IO_ERROR
```

- [ ] **Step 2: Run tests, expect failure**

Run: `.venv/bin/pytest tests/test_cache_canonical.py -v -k 'read_canonical'`
Expected: 5 FAILED with `AttributeError: 'Cache' object has no attribute 'read_canonical'`.

- [ ] **Step 3: Implement**

Add to `src/mdflow/core/cache.py`:

```python
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
```

- [ ] **Step 4: Run tests, expect pass**

Run: `.venv/bin/pytest tests/test_cache_canonical.py -v`
Expected: 9 PASS (4 from Task 3 + 5 from Task 4).

- [ ] **Step 5: Full suite + ruff**

Run: `.venv/bin/pytest -q && .venv/bin/ruff check src tests`
Expected: 328 passed/2 skipped. ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/mdflow/core/cache.py tests/test_cache_canonical.py
git commit -m "feat(m6a): Cache.read_canonical — round-trip + legacy compat

Reads result.md + meta.json + figs/<name> for each image. Legacy M0
entries (meta has 'assets' field, no figs/) read back as images=[].
OSError/JSONDecodeError → MdflowError(CACHE_IO_ERROR) per PRD §8.1.

Spec: docs/specs/2026-05-23-m6-image-support-design.md §5"
```

---

## Task 5: `Cache.build_bundle` — lazy ZIP_STORED bundle.zip

**Files:**
- Modify: `src/mdflow/core/cache.py` (add new method)
- Test: `tests/test_cache_canonical.py` (append tests)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cache_canonical.py`:

```python
import zipfile


def test_build_bundle_with_images_creates_zip(cache, tmp_path):
    sha = "4" + "0" * 63
    img = make_image_asset(b"image-bytes", "image/png")
    r = ConversionResult(
        markdown=f"![](figs/{img.name})",
        metadata={"x": 1},
        images=[img],
    )
    cache.write_canonical(sha, r, options={})
    bundle = cache.build_bundle(sha)
    assert bundle is not None
    assert bundle.exists()
    assert bundle.name == "bundle.zip"
    with zipfile.ZipFile(bundle) as zf:
        names = set(zf.namelist())
        assert "paper.md" in names
        assert "meta.json" in names
        assert f"figs/{img.name}" in names
        assert zf.read(f"figs/{img.name}") == b"image-bytes"
        assert zf.read("paper.md").decode() == r.markdown


def test_build_bundle_no_images_returns_none(cache, tmp_path):
    sha = "5" + "0" * 63
    r = ConversionResult(markdown="plain", metadata={}, images=[])
    cache.write_canonical(sha, r, options={})
    assert cache.build_bundle(sha) is None


def test_build_bundle_idempotent_does_not_rebuild(cache, tmp_path):
    sha = "6" + "0" * 63
    img = make_image_asset(b"x", "image/png")
    r = ConversionResult(markdown=f"![](figs/{img.name})", metadata={}, images=[img])
    cache.write_canonical(sha, r, options={})
    first = cache.build_bundle(sha)
    assert first is not None
    mtime1 = first.stat().st_mtime_ns
    import time
    time.sleep(0.01)
    second = cache.build_bundle(sha)
    assert second == first
    assert second.stat().st_mtime_ns == mtime1


def test_build_bundle_cache_miss_returns_none(cache):
    assert cache.build_bundle("7" + "0" * 63) is None


def test_build_bundle_uses_stored_compression(cache, tmp_path):
    sha = "8" + "0" * 63
    img = make_image_asset(b"compressible-bytes" * 100, "image/png")
    r = ConversionResult(markdown=f"![](figs/{img.name})", metadata={}, images=[img])
    cache.write_canonical(sha, r, options={})
    bundle = cache.build_bundle(sha)
    with zipfile.ZipFile(bundle) as zf:
        info = zf.getinfo(f"figs/{img.name}")
        assert info.compress_type == zipfile.ZIP_STORED
```

- [ ] **Step 2: Run tests, expect failure**

Run: `.venv/bin/pytest tests/test_cache_canonical.py -v -k 'build_bundle'`
Expected: 5 FAILED with `AttributeError: 'Cache' object has no attribute 'build_bundle'`.

- [ ] **Step 3: Implement**

Add to `src/mdflow/core/cache.py`:

```python
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
```

Add `import zipfile` to the top of `src/mdflow/core/cache.py` if not already present.

- [ ] **Step 4: Run tests, expect pass**

Run: `.venv/bin/pytest tests/test_cache_canonical.py -v`
Expected: 14 PASS (9 + 5 new).

- [ ] **Step 5: Full suite + ruff**

Run: `.venv/bin/pytest -q && .venv/bin/ruff check src tests`
Expected: 333 passed/2 skipped. ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/mdflow/core/cache.py tests/test_cache_canonical.py
git commit -m "feat(m6a): Cache.build_bundle — lazy ZIP_STORED bundle.zip

Builds <entry>/bundle.zip on first call (paper.md + meta.json + figs/*),
returns existing path on subsequent calls. ZIP_STORED — images are
already compressed; DEFLATE would waste CPU. Returns None when canonical
entry has 0 images (per spec D8). OSError wrapped as CACHE_IO_ERROR.

Spec: docs/specs/2026-05-23-m6-image-support-design.md §5.4"
```

---

## Task 6: `views/none.py` — strip figs/ refs with code-block protection

**Files:**
- Create: `src/mdflow/views/__init__.py`
- Create: `src/mdflow/views/none.py`
- Create: `tests/views/__init__.py`
- Create: `tests/views/test_none.py`

- [ ] **Step 1: Write failing tests**

Create `tests/views/__init__.py` (empty file).

Create `tests/views/test_none.py`:

```python
from mdflow.views.none import synthesize


def test_no_image_refs_unchanged():
    md = "plain markdown\n\nsecond paragraph"
    assert synthesize(md) == md


def test_standalone_image_no_alt_drops_line():
    md = "before\n\n![](figs/abc.png)\n\nafter"
    out = synthesize(md)
    assert "figs/" not in out
    assert "before" in out
    assert "after" in out


def test_standalone_image_with_alt_replaces_with_alt():
    md = "before\n\n![A photo](figs/abc.png)\n\nafter"
    out = synthesize(md)
    assert "figs/" not in out
    assert "A photo" in out


def test_inline_image_with_alt_replaced_by_alt():
    md = "see this ![logo](figs/x.png) here"
    assert synthesize(md) == "see this logo here"


def test_inline_image_no_alt_removed():
    md = "see ![](figs/x.png) end"
    out = synthesize(md)
    assert "figs/" not in out
    assert "see" in out and "end" in out


def test_code_block_refs_protected():
    md = "```md\n![alt](figs/x.png)\n```\n\nbody ![](figs/y.png) end"
    out = synthesize(md)
    assert "![alt](figs/x.png)" in out  # inside code fence — preserved
    assert "figs/y.png" not in out  # outside — removed


def test_collapses_3plus_blank_lines():
    md = "a\n\n\n\n\nb"
    out = synthesize(md)
    assert "\n\n\n" not in out
    assert "a" in out and "b" in out


def test_multiple_images_on_one_line():
    md = "![a](figs/1.png) and ![b](figs/2.png)"
    assert synthesize(md) == "a and b"


def test_non_figs_image_ref_untouched():
    # External URL refs (HTML converter case D7) should pass through
    md = "see ![alt](https://example.com/x.png)"
    assert synthesize(md) == md
```

- [ ] **Step 2: Run tests, expect failure**

Run: `.venv/bin/pytest tests/views/test_none.py -v`
Expected: 9 FAILED with `ModuleNotFoundError: No module named 'mdflow.views'`.

- [ ] **Step 3: Implement**

Create `src/mdflow/views/__init__.py` (empty file).

Create `src/mdflow/views/none.py`:

```python
"""Mode=none view synthesizer.

Strips canonical markdown's `figs/<sha>.<ext>` image refs while
preserving alt text where present. External URL refs (non-figs/ paths)
pass through unchanged — they belong to the HTML converter's D7 policy.

Code blocks (``` ... ```) are protected: refs inside fences are not
touched.
"""

from __future__ import annotations

import re

_STANDALONE = re.compile(r"^\s*!\[(.*?)\]\(figs/[^)]+\)\s*$")
_INLINE = re.compile(r"!\[(.*?)\]\(figs/[^)]+\)")


def synthesize(canonical_md: str) -> str:
    out_lines: list[str] = []
    in_code = False
    for line in canonical_md.split("\n"):
        if line.lstrip().startswith("```"):
            out_lines.append(line)
            in_code = not in_code
            continue
        if in_code:
            out_lines.append(line)
            continue
        sm = _STANDALONE.fullmatch(line)
        if sm:
            alt = sm.group(1)
            if alt:
                out_lines.append(alt)
            # else: drop the line entirely
            continue
        replaced = _INLINE.sub(lambda m: m.group(1), line)
        out_lines.append(replaced)
    text = "\n".join(out_lines)
    return re.sub(r"\n{3,}", "\n\n", text)
```

- [ ] **Step 4: Run tests, expect pass**

Run: `.venv/bin/pytest tests/views/test_none.py -v`
Expected: 9 PASS.

- [ ] **Step 5: Full suite + ruff**

Run: `.venv/bin/pytest -q && .venv/bin/ruff check src tests`
Expected: 342 passed/2 skipped. ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/mdflow/views/__init__.py src/mdflow/views/none.py tests/views/__init__.py tests/views/test_none.py
git commit -m "feat(m6a): views.none — strip figs/ refs with code-block protection

Standalone image-only lines drop entirely (or collapse to alt text).
Inline refs collapse to alt or empty string. Code blocks (\`\`\`...\`\`\`)
protected via line-by-line fence toggle. External URL refs (non-figs/)
pass through.

Spec: docs/specs/2026-05-23-m6-image-support-design.md §5.3"
```

---

## Task 7: `views/embed.py` — base64 data URI inlining

**Files:**
- Create: `src/mdflow/views/embed.py`
- Create: `tests/views/test_embed.py`

- [ ] **Step 1: Write failing tests**

Create `tests/views/test_embed.py`:

```python
import base64
from pathlib import Path

import pytest

from mdflow.core.errors import ErrorCode, MdflowError
from mdflow.views.embed import synthesize


def test_embeds_png_as_data_uri(tmp_path):
    figs = tmp_path / "figs"
    figs.mkdir()
    (figs / "abc.png").write_bytes(b"PNG-DATA")
    md = "before\n![alt](figs/abc.png)\nafter"
    out = synthesize(md, figs)
    b64 = base64.b64encode(b"PNG-DATA").decode("ascii")
    assert f"data:image/png;base64,{b64}" in out
    assert "![alt](data:image/png;base64," in out
    assert "before" in out and "after" in out


def test_no_refs_unchanged(tmp_path):
    assert synthesize("plain text", tmp_path / "figs") == "plain text"


def test_jpeg_mapping(tmp_path):
    figs = tmp_path / "figs"
    figs.mkdir()
    (figs / "x.jpg").write_bytes(b"jpgdata")
    md = "![](figs/x.jpg)"
    out = synthesize(md, figs)
    assert "data:image/jpeg;base64," in out


def test_svg_mapping(tmp_path):
    figs = tmp_path / "figs"
    figs.mkdir()
    (figs / "v.svg").write_bytes(b"<svg/>")
    md = "![](figs/v.svg)"
    out = synthesize(md, figs)
    assert "data:image/svg+xml;base64," in out


def test_gif_mapping(tmp_path):
    figs = tmp_path / "figs"
    figs.mkdir()
    (figs / "g.gif").write_bytes(b"GIF89a")
    md = "![](figs/g.gif)"
    out = synthesize(md, figs)
    assert "data:image/gif;base64," in out


def test_missing_figs_raises_cache_io_error(tmp_path):
    figs = tmp_path / "figs"
    figs.mkdir()
    md = "![](figs/missing.png)"
    with pytest.raises(MdflowError) as exc:
        synthesize(md, figs)
    assert exc.value.code is ErrorCode.CACHE_IO_ERROR


def test_code_block_refs_protected(tmp_path):
    figs = tmp_path / "figs"
    figs.mkdir()
    (figs / "x.png").write_bytes(b"d")
    md = "```\n![](figs/x.png)\n```\n\n![](figs/x.png)"
    out = synthesize(md, figs)
    assert "```\n![](figs/x.png)\n```" in out  # code fence untouched
    assert "data:image/png;base64," in out  # body ref embedded


def test_external_url_ref_untouched(tmp_path):
    figs = tmp_path / "figs"
    figs.mkdir()
    md = "![alt](https://example.com/x.png)"
    assert synthesize(md, figs) == md
```

- [ ] **Step 2: Run tests, expect failure**

Run: `.venv/bin/pytest tests/views/test_embed.py -v`
Expected: 8 FAILED with `ModuleNotFoundError: No module named 'mdflow.views.embed'`.

- [ ] **Step 3: Implement**

Create `src/mdflow/views/embed.py`:

```python
"""Mode=embed view synthesizer.

Replaces each `![alt](figs/<sha>.<ext>)` ref with a base64 data URI:
`![alt](data:<content_type>;base64,<b64>)`. Code blocks protected.

Content-type is inferred from the ext segment of the canonical name
(reverse of _image_util.EXT_BY_CT). Missing figs/ file →
MdflowError(CACHE_IO_ERROR).
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

from mdflow.converters._image_util import EXT_BY_CT
from mdflow.core.errors import ErrorCode, MdflowError

# Reverse EXT_BY_CT: ext -> content_type. First wins for duplicate exts.
_CT_BY_EXT: dict[str, str] = {}
for ct, ext in EXT_BY_CT.items():
    _CT_BY_EXT.setdefault(ext, ct)

_REF = re.compile(r"!\[(.*?)\]\(figs/([^)]+)\)")


def _content_type_for(name: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return _CT_BY_EXT.get(ext, "application/octet-stream")


def synthesize(canonical_md: str, figs_dir: Path) -> str:
    out_lines: list[str] = []
    in_code = False
    for line in canonical_md.split("\n"):
        if line.lstrip().startswith("```"):
            out_lines.append(line)
            in_code = not in_code
            continue
        if in_code:
            out_lines.append(line)
            continue

        def repl(m: re.Match[str]) -> str:
            alt = m.group(1)
            name = m.group(2)
            path = figs_dir / name
            try:
                data = path.read_bytes()
            except OSError as e:
                raise MdflowError(
                    ErrorCode.CACHE_IO_ERROR,
                    f"image {name} unreadable from figs/: {e}",
                ) from e
            b64 = base64.b64encode(data).decode("ascii")
            ct = _content_type_for(name)
            return f"![{alt}](data:{ct};base64,{b64})"

        out_lines.append(_REF.sub(repl, line))
    return "\n".join(out_lines)
```

- [ ] **Step 4: Run tests, expect pass**

Run: `.venv/bin/pytest tests/views/test_embed.py -v`
Expected: 8 PASS.

- [ ] **Step 5: Full suite + ruff**

Run: `.venv/bin/pytest -q && .venv/bin/ruff check src tests`
Expected: 350 passed/2 skipped. ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/mdflow/views/embed.py tests/views/test_embed.py
git commit -m "feat(m6a): views.embed — base64 data URI inlining

Reverses _image_util.EXT_BY_CT to map ext → content_type. Each
figs/<sha>.<ext> ref becomes ![alt](data:<ct>;base64,<b64>). Code blocks
protected. Missing figs/ file → CACHE_IO_ERROR. External URLs untouched.

Spec: docs/specs/2026-05-23-m6-image-support-design.md §5.3"
```

---

## Task 8: `views/zip.py` — wrap canonical markdown + bundle path

**Files:**
- Create: `src/mdflow/views/zip.py`
- Create: `tests/views/test_zip.py`

- [ ] **Step 1: Write failing tests**

Create `tests/views/test_zip.py`:

```python
import zipfile
from pathlib import Path

import pytest

from mdflow.converters._image_util import make_image_asset
from mdflow.converters.base import ConversionResult
from mdflow.core.cache import Cache
from mdflow.views.zip import synthesize


@pytest.fixture
def cache(tmp_path: Path) -> Cache:
    return Cache(tmp_path)


def test_with_images_returns_markdown_and_bundle_path(cache, tmp_path):
    sha = "a" * 64
    img = make_image_asset(b"d", "image/png")
    r = ConversionResult(markdown=f"![](figs/{img.name})", metadata={}, images=[img])
    cache.write_canonical(sha, r, options={})
    md, bundle = synthesize(r.markdown, cache, sha)
    assert md == r.markdown
    assert bundle is not None and bundle.exists()
    with zipfile.ZipFile(bundle) as zf:
        assert "paper.md" in zf.namelist()
        assert f"figs/{img.name}" in zf.namelist()


def test_no_images_returns_canonical_and_none(cache, tmp_path):
    sha = "b" * 64
    r = ConversionResult(markdown="plain", metadata={}, images=[])
    cache.write_canonical(sha, r, options={})
    md, bundle = synthesize("plain", cache, sha)
    assert md == "plain"
    assert bundle is None


def test_cache_miss_returns_none_bundle(cache):
    md, bundle = synthesize("anything", cache, "c" * 64)
    assert md == "anything"
    assert bundle is None
```

- [ ] **Step 2: Run tests, expect failure**

Run: `.venv/bin/pytest tests/views/test_zip.py -v`
Expected: 3 FAILED with `ModuleNotFoundError: No module named 'mdflow.views.zip'`.

- [ ] **Step 3: Implement**

Create `src/mdflow/views/zip.py`:

```python
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
```

- [ ] **Step 4: Run tests, expect pass**

Run: `.venv/bin/pytest tests/views/test_zip.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Full suite + ruff**

Run: `.venv/bin/pytest -q && .venv/bin/ruff check src tests`
Expected: 353 passed/2 skipped. ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/mdflow/views/zip.py tests/views/test_zip.py
git commit -m "feat(m6a): views.zip — canonical passthrough + lazy bundle path

Thin adapter over Cache.build_bundle. Returns (canonical_md, Path) when
the canonical entry has images, otherwise (canonical_md, None). M6e will
plug this into transport handlers (HTTP done.bundle_url, MCP bundle_b64).

Spec: docs/specs/2026-05-23-m6-image-support-design.md §5.3"
```

---

## Task 9: Migrate to canonical API + remove `ConversionResult.assets`

**Files:**
- Modify: `src/mdflow/converters/base.py` (remove assets field)
- Modify: `src/mdflow/core/cache.py` (delete old write/read, rename canonical methods)
- Modify: `src/mdflow/core/service.py` (use images, propagate via canonical write)
- Modify: `src/mdflow/api/convert.py` (Done assets=[] shim)
- Modify: `src/mdflow/api/admin.py` (`"assets": []` shim in /cache/{sha})
- Modify: `tests/converters/test_base.py` (remove assets-specific tests, keep ImageAsset tests)
- Modify: `tests/test_cache.py` (migrate `got.assets` → `got.images`)

This is a single coordinated migration. Tests touch multiple modules but the change is atomic — `assets: list[str]` field disappears from `ConversionResult` and `Cache` storage, replaced by `images: list[ImageAsset]`. API JSON responses keep `"assets": []` as a v2.0 compat shim.

- [ ] **Step 1: Update test_base.py to drop assets-specific tests**

Edit `tests/converters/test_base.py`. Delete the three existing assertions about `.assets`:

Search for these lines and remove them (along with their containing assertions):

```python
assert r.assets == []            # line ~50, remove
assert r.assets == ["a.png"]     # line ~57, remove
a.assets.append("x")             # line ~64, remove
assert b.assets == []            # line ~66, remove
```

If those assertions live inside test functions that test only `assets`, delete those functions entirely. ImageAsset tests added in Task 1 should remain.

After edit, run: `.venv/bin/pytest tests/converters/test_base.py -v`
Expected: PASS (only image-related and other surviving tests).

- [ ] **Step 2: Update tests/test_cache.py to drop assets references**

Edit `tests/test_cache.py` line 54. Find:

```python
assert got.assets == ["asset1.png"]
```

Replace the surrounding test to use `images: list[ImageAsset]` instead. If the test was specifically about round-tripping the old `assets` field, replace it with this round-trip test:

```python
from mdflow.converters._image_util import make_image_asset


def test_cache_round_trips_images(tmp_path):
    cache = Cache(tmp_path)
    img = make_image_asset(b"png-bytes", "image/png")
    r = ConversionResult(
        markdown=f"![](figs/{img.name})",
        metadata={},
        images=[img],
    )
    sha = "a" * 64
    cache.write(sha, r, options={})
    got = cache.read(sha)
    assert got is not None
    assert len(got.images) == 1
    assert got.images[0].data == b"png-bytes"
```

(Anywhere else in `test_cache.py` that references `.assets` — replace with the equivalent `.images` assertion, or delete if the test was solely about the deprecated field.)

- [ ] **Step 3: Run partial test suite to map remaining failures**

Run: `.venv/bin/pytest -q 2>&1 | tail -40`

Expect failures from src modules still referencing `.assets`. Note each file (likely `src/mdflow/core/cache.py:95,134`, `src/mdflow/core/service.py:136`, `src/mdflow/api/convert.py:40`, `src/mdflow/api/admin.py:56`).

- [ ] **Step 4: Migrate `src/mdflow/core/cache.py` — delete old write/read, rename canonical**

In `src/mdflow/core/cache.py`:

1. Delete the existing `write` method (the one that uses `result.assets`).
2. Delete the existing `read` method (the one that returns `assets=meta.get("assets", [])`).
3. Rename `write_canonical` → `write`.
4. Rename `read_canonical` → `read`.

After rename, the public API is identical to before (`cache.write(sha, result, options=...)`, `cache.read(sha)`) — only the persisted shape changed (figs/ + meta.images).

`build_bundle` keeps its name (new method, no rename).

- [ ] **Step 5: Migrate `src/mdflow/core/service.py`**

Edit `src/mdflow/core/service.py` line ~136. Find:

```python
result = ConversionResult(
    markdown=result.markdown,
    metadata=enriched_meta,
    assets=result.assets,
)
```

Replace with:

```python
result = ConversionResult(
    markdown=result.markdown,
    metadata=enriched_meta,
    images=result.images,
)
```

(In M6a no converter produces images, so `result.images` is always `[]`. The wiring is in place for M6b\~M6d.)

- [ ] **Step 6: Migrate `src/mdflow/api/convert.py`**

Edit `src/mdflow/api/convert.py` line ~40. Find:

```python
return Done(markdown=result.markdown, metadata=metadata, assets=result.assets)
```

Replace with:

```python
return Done(markdown=result.markdown, metadata=metadata, assets=[])
```

`Done.assets: list[str]` (in `events.py`) is the v2.0 SSE compat shim. M6e may change Done schema; M6a keeps it `[]`.

- [ ] **Step 7: Migrate `src/mdflow/api/admin.py`**

Edit `src/mdflow/api/admin.py` line ~56. Find:

```python
"assets": entry.assets,
```

Replace with:

```python
"assets": [],
```

- [ ] **Step 8: Remove `ConversionResult.assets` field**

Edit `src/mdflow/converters/base.py`. Remove the `assets` field:

```python
@dataclass
class ConversionResult:
    markdown: str
    metadata: dict[str, Any]
    images: list[ImageAsset] = field(default_factory=list)
    # assets field deleted (was: list[str] = field(default_factory=list))
```

- [ ] **Step 9: Run full suite + ruff**

Run: `.venv/bin/pytest -q && .venv/bin/ruff check src tests`

Expected: **353 passed/2 skipped** (304 pre-M6a + ~49 new across Tasks 1-8, minus a few removed assets-specific tests from Task 9 Steps 1-2). Exact count may vary by ±5 depending on how many assets tests existed.

If anything fails, grep for remaining `.assets` or `"assets"` references in src/:

```bash
grep -rn '\.assets\b\|"assets"' src/mdflow/ --include='*.py' | grep -v __pycache__
```

Expected hits are only the SSE shim (`events.py: assets: list[str]`), the `Done(assets=[])` shim, the admin shim, and maybe Console docs/comments — no functional references.

- [ ] **Step 10: Verify backward compat with legacy cache entries**

Run: `.venv/bin/pytest tests/test_cache_canonical.py::test_read_canonical_legacy_no_figs_meta_assets_returns_empty_images -v`

Expected: PASS. This confirms M0-style on-disk entries still round-trip via the renamed `read` method.

- [ ] **Step 11: Commit**

```bash
git add src/mdflow/converters/base.py src/mdflow/core/cache.py src/mdflow/core/service.py src/mdflow/api/convert.py src/mdflow/api/admin.py tests/converters/test_base.py tests/test_cache.py
git commit -m "refactor(m6a): migrate to canonical cache + remove ConversionResult.assets

Cache.write/read renamed from canonical_* — same public signature, new
on-disk shape (figs/ + meta.images). Service propagates result.images
(empty in M6a, populated by converters in M6b~M6d). API/admin keep
'assets': [] JSON shim per spec §7.3 v2.0 compat.

Legacy on-disk entries (M0-style meta.json with 'assets' field, no
figs/ dir) round-trip as images=[].

Spec: docs/specs/2026-05-23-m6-image-support-design.md §4.2, §7.3, §10.2"
```

---

## Self-Review Notes (run after Task 9 commits)

These are sanity checks; not separate tasks. If any fail, fix and re-commit.

**Spec coverage (§4-§7 of spec):**
- §4.2 `ImageAsset`, `ConversionResult.images` → Task 1 ✓
- §4.3 `_image_util.py` helpers → Task 2 ✓
- §4.4 Cache disk layout (result.md, meta.json, figs/, bundle.zip) → Tasks 3-5 ✓
- §5.1 Data flow [1]\~[7] → handler-side flow is M6e; canonical write/read + view synthesis covered Tasks 3-8
- §5.2 Canonical markdown form (`![alt](figs/<sha>.<ext>)`) → Task 2 helper + view synth consumers ✓
- §5.3 View synthesis 3 modes → Tasks 6-8 ✓
- §5.4 build_bundle ZIP_STORED + atomic → Task 5 ✓
- §7 Converter mappings → out of M6a scope (M6b\~M6d)
- §7.1 Common helpers → Task 2 ✓

**Placeholder scan:**

```bash
grep -n 'TBD\|TODO\|FIXME\|fill in\|implement later' docs/superpowers/plans/2026-05-23-m6a-image-infrastructure.md
```

Expected: 0 matches.

**Type consistency:**

- `ImageAsset(name: str, data: bytes, content_type: str)` — same signature in Tasks 1, 2, 3, 4, 5, 7, 8, 9 ✓
- `Cache.build_bundle(sha: str) -> Path | None` — same in Tasks 5, 8 ✓
- `views.none.synthesize(canonical_md: str) -> str` — single arg ✓
- `views.embed.synthesize(canonical_md: str, figs_dir: Path) -> str` — two args ✓
- `views.zip.synthesize(canonical_md: str, cache: Cache, sha: str) -> tuple[str, Path | None]` — three args ✓
- `Cache.write(sha, result, *, options)` — same public signature as before, only persisted shape changed (Task 9) ✓
