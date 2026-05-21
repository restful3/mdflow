"""Disk cache: sha256(input_bytes || canonical_options_json).

PRD §9 + URL agreement §3.7 — cache key is bytes+options, URL provenance
is NOT in the key (handled at the response-metadata level by the service).
"""

import json
from pathlib import Path

import pytest

from mdflow.converters.base import ConversionResult
from mdflow.core.cache import Cache, compute_cache_key


def test_compute_cache_key_is_deterministic_under_dict_reordering():
    k1 = compute_cache_key(b"abc", {"a": 1, "b": 2})
    k2 = compute_cache_key(b"abc", {"b": 2, "a": 1})
    assert k1 == k2
    assert len(k1) == 64


def test_compute_cache_key_changes_with_options():
    a = compute_cache_key(b"abc", {"x": 1})
    b = compute_cache_key(b"abc", {"x": 2})
    assert a != b


def test_compute_cache_key_changes_with_bytes():
    a = compute_cache_key(b"abc", {})
    b = compute_cache_key(b"abd", {})
    assert a != b


def test_cache_write_then_read(tmp_cache_dir: Path):
    cache = Cache(tmp_cache_dir)
    sha = "a" * 64
    res = ConversionResult(markdown="# x", metadata={"converter": "text"}, assets=["asset1.png"])
    cache.write(sha, res, options={"k": 1})

    got = cache.read(sha)
    assert got is not None
    assert got.markdown == "# x"
    assert got.metadata["converter"] == "text"
    assert got.assets == ["asset1.png"]


def test_cache_read_miss_returns_none(tmp_cache_dir: Path):
    assert Cache(tmp_cache_dir).read("f" * 64) is None


def test_cache_write_persists_meta_json(tmp_cache_dir: Path):
    cache = Cache(tmp_cache_dir)
    sha = "b" * 64
    cache.write(sha, ConversionResult(markdown="x"), options={"opt": "val"})
    entry = tmp_cache_dir / sha
    assert (entry / "result.md").read_text(encoding="utf-8") == "x"
    meta = json.loads((entry / "meta.json").read_text(encoding="utf-8"))
    assert meta["sha256"] == sha
    assert meta["options"] == {"opt": "val"}


def test_cache_stats_counts(tmp_cache_dir: Path):
    cache = Cache(tmp_cache_dir)
    sha = "c" * 64
    cache.write(sha, ConversionResult(markdown="y"), options={})
    cache.read(sha)  # hit
    cache.read("d" * 64)  # miss
    stats = cache.stats()
    assert stats["entries"] == 1
    assert stats["hit_count"] == 1
    assert stats["miss_count"] == 1
    assert "size_mb" in stats


def test_cache_delete_removes_entry(tmp_cache_dir: Path):
    cache = Cache(tmp_cache_dir)
    sha = "e" * 64
    cache.write(sha, ConversionResult(markdown="z"), options={})
    assert cache.read(sha) is not None
    assert cache.delete(sha) is True
    assert cache.read(sha) is None
    assert cache.delete(sha) is False  # idempotent second delete


def test_cache_purge_clears_all(tmp_cache_dir: Path):
    cache = Cache(tmp_cache_dir)
    cache.write("1" * 64, ConversionResult(markdown="a"), options={})
    cache.write("2" * 64, ConversionResult(markdown="b"), options={})
    assert cache.purge() == 2
    assert cache.stats()["entries"] == 0


def test_cache_invalid_sha_format_rejected(tmp_cache_dir: Path):
    cache = Cache(tmp_cache_dir)
    with pytest.raises(ValueError):
        cache.read("../etc/passwd")
    with pytest.raises(ValueError):
        cache.read("g" * 64)  # 'g' not hex
    with pytest.raises(ValueError):
        cache.read("a" * 63)  # too short


def test_cache_write_overwrites_existing(tmp_cache_dir: Path):
    cache = Cache(tmp_cache_dir)
    sha = "f" * 64
    cache.write(sha, ConversionResult(markdown="first"), options={})
    cache.write(sha, ConversionResult(markdown="second"), options={})
    got = cache.read(sha)
    assert got is not None
    assert got.markdown == "second"


def test_cache_purge_ignores_non_entry_files(tmp_cache_dir: Path):
    cache = Cache(tmp_cache_dir)
    cache.write("0" * 64, ConversionResult(markdown="x"), options={})
    (tmp_cache_dir / "junk.txt").write_text("ignore me", encoding="utf-8")
    assert cache.purge() == 1
    assert (tmp_cache_dir / "junk.txt").exists()  # purge only removes sha entries
