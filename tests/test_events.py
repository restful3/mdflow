"""Pydantic SSE event models — incremental: Started, Queued."""

from mdflow.core.events import Queued, Started


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


def test_started_event_json_roundtrip():
    e = Started(converter="text", gpu=False, sha256="c" * 64)
    payload = e.model_dump_json()
    assert "text" in payload
    parsed = Started.model_validate_json(payload)
    assert parsed == e
