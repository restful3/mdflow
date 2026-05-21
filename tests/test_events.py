"""Pydantic SSE event models — incremental: Started only."""

from mdflow.core.events import Started


def test_started_event_minimal():
    e = Started(converter="text-passthrough", gpu=False, sha256="a" * 64)
    assert e.converter == "text-passthrough"
    assert e.gpu is False
    assert e.sha256 == "a" * 64


def test_started_event_json_roundtrip():
    e = Started(converter="text", gpu=False, sha256="c" * 64)
    payload = e.model_dump_json()
    assert "text" in payload
    parsed = Started.model_validate_json(payload)
    assert parsed == e
