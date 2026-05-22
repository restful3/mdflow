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


def test_convert_url_streams_fetch_progress_then_done(monkeypatch):
    from mdflow.core.url_fetch import FetchResult

    def fake_fetch(url, policy, *, transport=None):
        return FetchResult(
            data=b"hello from url",
            source_url=url,
            effective_url=url,
            http_status=200,
            content_type="text/plain",
            content_length=14,
            content_disposition=None,
            filename_hint="page.txt",
            fetched_at="2026-05-22T00:00:00Z",
            redirect_count=0,
        )

    monkeypatch.setattr("mdflow.api.convert.fetch_url", fake_fetch)

    app = create_app()
    with TestClient(app) as client:
        r = client.post("/convert", json={"url": "https://example.com/page.txt"})
    assert r.status_code == 200
    events = _parse_sse(r.text)
    kinds = [e[0] for e in events]
    assert "started" in kinds
    assert kinds[-1] == "done"
    assert any(k == "progress" and d.get("stage") == "fetch" for k, d in events)
    done = dict(events)["done"]
    assert done["markdown"] == "hello from url"
    assert done["metadata"]["fetch"]["source_url"] == "https://example.com/page.txt"


def test_convert_no_input_returns_400():
    app = create_app()
    with TestClient(app) as client:
        r = client.post("/convert", json={})
    assert r.status_code == 400


def test_convert_empty_multipart_returns_400():
    app = create_app()
    with TestClient(app) as client:
        r = client.post("/convert", data={"notfile": "x"})
    assert r.status_code == 400


def test_convert_streams_progress_events_in_order(monkeypatch):
    """A converter that reports progress must surface ordered progress
    events between started and done.
    """
    from mdflow.converters.base import ConversionResult

    class ProgressyConverter:
        name = "progressy"
        formats = ("txt",)
        requires_gpu = False

        def can_handle(self, ctx):
            return ctx.format in self.formats

        def convert(self, ctx, progress):
            progress("parse", 25)
            progress("render", 75)
            return ConversionResult(markdown="done-body")

    app = create_app()

    def _register(state_app):
        from mdflow.core.registry import Registry

        reg = Registry()
        reg.register(ProgressyConverter())
        state_app.state.registry = reg
        state_app.state.service.registry = reg

    with TestClient(app) as client:
        _register(app)
        r = client.post("/convert", files={"file": ("a.txt", b"anything", "text/plain")})
    events = _parse_sse(r.text)
    kinds = [e[0] for e in events]
    assert kinds[0] == "started"
    assert kinds[-1] == "done"
    progress_stages = [d["stage"] for k, d in events if k == "progress"]
    assert progress_stages == ["parse", "render"]
