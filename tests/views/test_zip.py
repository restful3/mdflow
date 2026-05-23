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
