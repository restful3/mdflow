"""Disk cache: sha256(input_bytes || canonical_options_json).

PRD §9 + URL agreement §3.7 — cache key is bytes+options, URL provenance
is NOT in the key (handled at the response-metadata level by the service).
"""

import json
import tempfile
from pathlib import Path

import pytest

from mdflow.converters.base import ConversionResult
from mdflow.core.cache import Cache, compute_cache_key


def test_compute_cache_key_is_deterministic_under_dict_reordering():
    k1 = compute_cache_key(b"abc", {"a": 1, "b": 2}, detected_format="txt")
    k2 = compute_cache_key(b"abc", {"b": 2, "a": 1}, detected_format="txt")
    assert k1 == k2
    assert len(k1) == 64


def test_compute_cache_key_changes_with_options():
    a = compute_cache_key(b"abc", {"x": 1}, detected_format="txt")
    b = compute_cache_key(b"abc", {"x": 2}, detected_format="txt")
    assert a != b


def test_compute_cache_key_changes_with_bytes():
    a = compute_cache_key(b"abc", {}, detected_format="txt")
    b = compute_cache_key(b"abd", {}, detected_format="txt")
    assert a != b


def test_compute_cache_key_changes_with_detected_format():
    """Codex review blocker #1: detected_format must be part of the key."""
    a = compute_cache_key(b"abc", {}, detected_format="txt")
    b = compute_cache_key(b"abc", {}, detected_format="csv")
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


def test_cache_write_oserror_wrapped_as_cache_io_error(
    tmp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """Codex recommendation #5 (write slice, 2026-05-22): cache.write
    must surface OSError paths as `MdflowError(CACHE_IO_ERROR)`, not
    raw OSError. Forcing `Path.write_text` to fail simulates a disk-full
    or permission-denied scenario without OS-specific setup.
    """
    from mdflow.core.errors import ErrorCode, MdflowError

    cache = Cache(tmp_cache_dir)

    def boom(self, *_args, **_kwargs):  # noqa: ARG001
        raise OSError("simulated disk failure")

    monkeypatch.setattr(Path, "write_text", boom)
    with pytest.raises(MdflowError) as exc:
        cache.write("a" * 64, ConversionResult(markdown="x"), options={})
    assert exc.value.code is ErrorCode.CACHE_IO_ERROR


def test_cache_read_corrupt_meta_json_raises_cache_io_error(tmp_cache_dir: Path):
    """Codex recommendation #5 (2026-05-22): a corrupted `meta.json`
    must surface as `MdflowError(CACHE_IO_ERROR)` instead of leaking a
    raw `json.JSONDecodeError`. PRD §8.1 defines CACHE_IO_ERROR as the
    retryable cache failure code; today the enum exists but is unused.
    """
    from mdflow.core.errors import ErrorCode, MdflowError

    cache = Cache(tmp_cache_dir)
    sha = "a" * 64
    # Plant a half-corrupt entry: result.md exists, meta.json is invalid.
    entry = tmp_cache_dir / sha
    entry.mkdir(parents=True)
    (entry / "result.md").write_text("# x", encoding="utf-8")
    (entry / "meta.json").write_text("{not valid json", encoding="utf-8")

    with pytest.raises(MdflowError) as exc:
        cache.read(sha)
    assert exc.value.code is ErrorCode.CACHE_IO_ERROR


def test_cache_write_mkdtemp_oserror_wrapped_as_cache_io_error(
    tmp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """Codex finding #2 (2026-05-22 follow-up review): an `OSError` from
    `tempfile.mkdtemp` itself (cache root unwritable, permission flip,
    disk error before any payload is written) must also surface as
    `MdflowError(CACHE_IO_ERROR)` with `__cause__` preserved — the
    first slice only covered `Path.write_text` failures.
    """
    from mdflow.core.errors import ErrorCode, MdflowError

    cache = Cache(tmp_cache_dir)

    def boom(*_args, **_kwargs):
        raise OSError("simulated mkdtemp failure")

    monkeypatch.setattr("mdflow.core.cache.tempfile.mkdtemp", boom)
    with pytest.raises(MdflowError) as exc:
        cache.write("a" * 64, ConversionResult(markdown="x"), options={})
    assert exc.value.code is ErrorCode.CACHE_IO_ERROR
    assert isinstance(exc.value.__cause__, OSError)


def test_cache_write_uses_unique_tmp_dir_per_call(
    tmp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """Codex recommendation #6 (2026-05-22): two cache writes against
    the same sha must allocate unique tmp directories. The original
    fixed `.tmp-{sha}` path could be clobbered by a concurrent writer.
    `tempfile.mkdtemp(prefix=f".tmp-{sha}-", dir=root)` gives each call
    its own dir, eliminating mid-write tmp corruption. (Publish-step
    race on `os.replace` after a non-empty destination is a separate
    M1+ concern — see follow-up review finding #1.)
    """
    seen: list[str] = []
    real_mkdtemp = tempfile.mkdtemp

    def spy(*a, **kw):
        path = real_mkdtemp(*a, **kw)
        seen.append(path)
        return path

    monkeypatch.setattr("mdflow.core.cache.tempfile.mkdtemp", spy)
    cache = Cache(tmp_cache_dir)
    sha = "a" * 64
    cache.write(sha, ConversionResult(markdown="x"), options={})
    cache.write(sha, ConversionResult(markdown="y"), options={})
    assert len(seen) == 2
    assert seen[0] != seen[1]


def test_cache_purge_ignores_non_entry_files(tmp_cache_dir: Path):
    cache = Cache(tmp_cache_dir)
    cache.write("0" * 64, ConversionResult(markdown="x"), options={})
    (tmp_cache_dir / "junk.txt").write_text("ignore me", encoding="utf-8")
    assert cache.purge() == 1
    assert (tmp_cache_dir / "junk.txt").exists()  # purge only removes sha entries


def test_cache_cached_at_returns_iso_for_existing_entry(tmp_cache_dir: Path):
    cache = Cache(tmp_cache_dir)
    sha = "a" * 64
    cache.write(sha, ConversionResult(markdown="x"), options={})
    ts = cache.cached_at(sha)
    assert ts is not None
    # ISO-8601 with timezone; parseable and ends in +00:00 or Z
    from datetime import datetime

    parsed = datetime.fromisoformat(ts)
    assert parsed.tzinfo is not None


def test_cache_cached_at_returns_none_for_missing_entry(tmp_cache_dir: Path):
    cache = Cache(tmp_cache_dir)
    assert cache.cached_at("b" * 64) is None
