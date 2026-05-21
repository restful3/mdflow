"""Pydantic SSE event models — incremental: Started, Queued, Progress, Cached."""

import pytest
from pydantic import ValidationError

from mdflow.core.events import Cached, Progress, Queued, Started


def test_started_event_minimal():
    e = Started(converter="text-passthrough", gpu=False, sha256="a" * 64)
    assert e.converter == "text-passthrough"
    assert e.gpu is False
    assert e.sha256 == "a" * 64


def test_queued_event_requires_reason_and_position():
    e = Queued(reason="gpu_busy", position=2)
    assert e.reason == "gpu_busy"
    assert e.position == 2


def test_queued_event_json_roundtrip():
    e = Queued(reason="gpu_busy", position=1)
    payload = e.model_dump_json()
    parsed = Queued.model_validate_json(payload)
    assert parsed == e


def test_progress_event_clamps_pct_to_0_100():
    Progress(stage="parse", pct=0, detail="start")
    Progress(stage="parse", pct=42, detail="line 3")
    Progress(stage="parse", pct=100, detail="end")
    with pytest.raises(ValidationError):
        Progress(stage="parse", pct=-1, detail="bad")
    with pytest.raises(ValidationError):
        Progress(stage="parse", pct=101, detail="bad")


def test_progress_event_default_detail_is_empty():
    e = Progress(stage="parse", pct=10)
    assert e.detail == ""


def test_cached_event_records_sha_and_timestamp():
    e = Cached(sha256="b" * 64, cached_at="2026-05-21T10:00:00Z")
    assert e.sha256 == "b" * 64
    assert e.cached_at.endswith("Z")


def test_cached_event_json_roundtrip():
    e = Cached(sha256="d" * 64, cached_at="2026-05-21T10:00:00Z")
    parsed = Cached.model_validate_json(e.model_dump_json())
    assert parsed == e


def test_started_event_json_roundtrip():
    e = Started(converter="text", gpu=False, sha256="c" * 64)
    payload = e.model_dump_json()
    assert "text" in payload
    parsed = Started.model_validate_json(payload)
    assert parsed == e
