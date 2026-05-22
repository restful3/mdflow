"""POST /convert SSE streaming."""

import json

from fastapi.testclient import TestClient

from mdflow.api.app import create_app


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    """Parse an SSE body into a list of (event, data-dict)."""
    events = []
    block: dict[str, str] = {}
    for line in text.splitlines():
        if line == "":
            if block:
                events.append((block["event"], json.loads(block["data"])))
                block = {}
            continue
        key, _, value = line.partition(": ")
        block[key] = value
    if block:
        events.append((block["event"], json.loads(block["data"])))
    return events


def test_convert_file_miss_streams_started_then_done():
    app = create_app()
    with TestClient(app) as client:
        r = client.post("/convert", files={"file": ("a.txt", b"hello mdflow", "text/plain")})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(r.text)
    kinds = [e[0] for e in events]
    assert kinds[0] == "started"
    assert kinds[-1] == "done"
    started = dict(events)["started"]
    assert started["converter"] == "text-passthrough"
    assert started["gpu"] is False
    done = dict(events)["done"]
    assert done["markdown"] == "hello mdflow"


def test_convert_file_hit_streams_cached_then_done():
    app = create_app()
    with TestClient(app) as client:
        files = {"file": ("a.txt", b"hello mdflow", "text/plain")}
        client.post("/convert", files=files)  # populate cache
        r = client.post("/convert", files={"file": ("a.txt", b"hello mdflow", "text/plain")})
    events = _parse_sse(r.text)
    kinds = [e[0] for e in events]
    assert kinds == ["cached", "done"]
    cached = dict(events)["cached"]
    assert "cached_at" in cached
    assert dict(events)["done"]["markdown"] == "hello mdflow"


def test_convert_unknown_format_streams_error():
    app = create_app()
    with TestClient(app) as client:
        # No extension, binary bytes with no magic match -> FORMAT_DETECT_FAILED
        r = client.post(
            "/convert", files={"file": ("blob", b"\x00\x01\x02\x03", "application/octet-stream")}
        )
    assert r.status_code == 200
    events = _parse_sse(r.text)
    assert events[-1][0] == "error"
    assert events[-1][1]["code"] == "FORMAT_DETECT_FAILED"
    assert events[-1][1]["retryable"] is False
