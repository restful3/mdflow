import json
import zipfile
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
    cache.write(sha, r, options={})
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
    cache.write(sha, r, options={})
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
    cache.write(sha, r, options={})
    figs = tmp_path / sha / "figs"
    assert len(list(figs.iterdir())) == 1


def test_write_canonical_oserror_wrapped_and_tmp_cleaned(cache, tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("fake replace failure")
    monkeypatch.setattr("mdflow.core.cache.os.replace", boom)
    sha = "d" * 64
    r = ConversionResult(markdown="x", metadata={}, images=[])
    with pytest.raises(MdflowError) as exc:
        cache.write(sha, r, options={})
    assert exc.value.code is ErrorCode.CACHE_IO_ERROR
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".tmp-")]
    assert leftovers == []


def test_read_canonical_round_trip(cache, tmp_path):
    sha = "e" * 64
    img = make_image_asset(b"data", "image/png")
    r = ConversionResult(
        markdown=f"![](figs/{img.name})",
        metadata={"k": "v"},
        images=[img],
    )
    cache.write(sha, r, options={})
    got = cache.read(sha)
    assert got is not None
    assert got.markdown == r.markdown
    assert got.metadata == {"k": "v"}
    assert len(got.images) == 1
    assert got.images[0].name == img.name
    assert got.images[0].data == b"data"
    assert got.images[0].content_type == "image/png"


def test_read_canonical_miss_returns_none(cache):
    assert cache.read("f" * 64) is None


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
    got = cache.read(sha)
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
        cache.read(sha)
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
        cache.read(sha)
    assert exc.value.code is ErrorCode.CACHE_IO_ERROR


def test_build_bundle_with_images_creates_zip(cache, tmp_path):
    sha = "4" + "0" * 63
    img = make_image_asset(b"image-bytes", "image/png")
    r = ConversionResult(
        markdown=f"![](figs/{img.name})",
        metadata={"x": 1},
        images=[img],
    )
    cache.write(sha, r, options={})
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
    cache.write(sha, r, options={})
    assert cache.build_bundle(sha) is None


def test_build_bundle_idempotent_does_not_rebuild(cache, tmp_path):
    sha = "6" + "0" * 63
    img = make_image_asset(b"x", "image/png")
    r = ConversionResult(markdown=f"![](figs/{img.name})", metadata={}, images=[img])
    cache.write(sha, r, options={})
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
    cache.write(sha, r, options={})
    bundle = cache.build_bundle(sha)
    with zipfile.ZipFile(bundle) as zf:
        info = zf.getinfo(f"figs/{img.name}")
        assert info.compress_type == zipfile.ZIP_STORED
