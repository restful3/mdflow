"""POST /convert SSE streaming."""

import asyncio
import contextlib
import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from mdflow.api.app import create_app
from tests.conftest import requires_gpu_runtime, requires_soffice
from tests.golden import assert_golden


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


def test_convert_converter_exception_streams_conversion_failed():
    class BoomConverter:
        name = "boom"
        formats = ("txt",)
        requires_gpu = False

        def can_handle(self, ctx):
            return ctx.format in self.formats

        def convert(self, ctx, progress):
            progress("half", 50)
            raise ValueError("boom")

    app = create_app()

    def _register(state_app):
        from mdflow.core.registry import Registry

        reg = Registry()
        reg.register(BoomConverter())
        state_app.state.registry = reg
        state_app.state.service.registry = reg

    with TestClient(app) as client:
        _register(app)
        r = client.post("/convert", files={"file": ("a.txt", b"anything", "text/plain")})
    assert r.status_code == 200
    events = _parse_sse(r.text)
    assert events[-1][0] == "error"
    assert events[-1][1]["code"] == "CONVERSION_FAILED"


def test_convert_file_over_size_cap_returns_413(monkeypatch):
    monkeypatch.setenv("MDFLOW_MAX_INPUT_MB", "1")
    monkeypatch.setenv("MDFLOW_MAX_URL_INPUT_MB", "1")  # validator: max_url <= max_input
    app = create_app()
    big = b"x" * (1024 * 1024 + 10)  # just over 1 MB
    with TestClient(app) as client:
        r = client.post("/convert", files={"file": ("big.txt", big, "text/plain")})
    assert r.status_code == 413


def test_convert_json_non_object_returns_400():
    app = create_app()
    with TestClient(app) as client:
        # a JSON list, not an object
        r = client.post(
            "/convert", content=b"[1, 2, 3]", headers={"content-type": "application/json"}
        )
    assert r.status_code == 400


def test_convert_json_non_string_url_returns_400():
    app = create_app()
    with TestClient(app) as client:
        r = client.post("/convert", json={"url": 123})
    assert r.status_code == 400


def test_convert_invalid_json_returns_400():
    app = create_app()
    with TestClient(app) as client:
        r = client.post(
            "/convert", content=b"{not json", headers={"content-type": "application/json"}
        )
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


def _run_convert(filename: str, data: bytes, mime: str):
    app = create_app()
    with TestClient(app) as client:
        r = client.post("/convert", files={"file": (filename, data, mime)})
    assert r.status_code == 200
    events = _parse_sse(r.text)
    return dict(events), [e[0] for e in events]


def test_convert_docx_streams_started_done(sample_docx_bytes):
    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    by_event, kinds = _run_convert("sample.docx", sample_docx_bytes, mime)
    assert kinds[0] == "started" and kinds[-1] == "done"
    assert by_event["started"]["converter"] == "docx-mammoth"
    assert_golden(by_event["done"]["markdown"], "docx/sample.md")


def test_convert_pptx_streams_started_done(sample_pptx_bytes):
    mime = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    by_event, kinds = _run_convert("sample.pptx", sample_pptx_bytes, mime)
    assert kinds[0] == "started" and kinds[-1] == "done"
    assert by_event["started"]["converter"] == "pptx-python-pptx"
    assert_golden(by_event["done"]["markdown"], "pptx/sample.md")


def test_convert_xlsx_streams_started_done(sample_xlsx_bytes):
    mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    by_event, kinds = _run_convert("sample.xlsx", sample_xlsx_bytes, mime)
    assert kinds[0] == "started" and kinds[-1] == "done"
    assert by_event["started"]["converter"] == "xlsx-openpyxl"
    assert_golden(by_event["done"]["markdown"], "xlsx/sample.md")


def test_convert_html_streams_started_done(sample_html):
    by_event, kinds = _run_convert("sample.html", sample_html.encode("utf-8"), "text/html")
    assert kinds[0] == "started" and kinds[-1] == "done"
    assert by_event["started"]["converter"] == "html-trafilatura"
    assert_golden(by_event["done"]["markdown"], "html/sample.md")


@pytest.mark.parametrize(
    ("filename", "mime"),
    [
        ("broken.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        (
            "broken.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ),
        ("broken.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ],
)
def test_convert_corrupted_ooxml_streams_conversion_failed(filename, mime):
    # Garbage bytes detected (by extension) as an OOXML format must reach
    # the converter, raise inside the library, and surface as a terminal
    # CONVERSION_FAILED error event — proving the converter does not swallow
    # the library exception (design §6).
    by_event, kinds = _run_convert(filename, b"this is not a real office document", mime)
    assert kinds[-1] == "error"
    assert by_event["error"]["code"] == "CONVERSION_FAILED"


class _FakeGpuConverter:
    name = "fake-gpu"
    formats = ("txt",)
    requires_gpu = True

    def can_handle(self, ctx):
        return ctx.format in self.formats

    def convert(self, ctx, progress):
        from mdflow.converters.base import ConversionResult

        progress("infer", 50)
        return ConversionResult(markdown="gpu-output", metadata={})


def _swap_registry(app, converter):
    from mdflow.core.registry import Registry

    reg = Registry()
    reg.register(converter)
    app.state.registry = reg
    app.state.service.registry = reg


def test_gpu_converter_runs_under_gpu_lock_and_reports_gpu_true():
    app = create_app()
    with TestClient(app) as client:
        _swap_registry(app, _FakeGpuConverter())
        r = client.post("/convert", files={"file": ("a.txt", b"hi", "text/plain")})
    assert r.status_code == 200
    events = _parse_sse(r.text)
    by_event = dict(events)
    kinds = [e[0] for e in events]
    assert kinds[0] == "started" and kinds[-1] == "done"
    assert by_event["started"]["gpu"] is True
    assert by_event["done"]["markdown"] == "gpu-output"
    assert "queued" not in kinds


async def test_gpu_converter_emits_queued_when_semaphore_busy():
    app = create_app()
    async with app.router.lifespan_context(app):
        _swap_registry(app, _FakeGpuConverter())
        sem = app.state.pool.gpu_semaphore
        await sem.acquire()  # hold the GPU -> next request must queue

        async def _release_soon():
            await asyncio.sleep(0.2)
            sem.release()

        releaser = asyncio.create_task(_release_soon())
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.post("/convert", files={"file": ("a.txt", b"hi", "text/plain")})
        await releaser

    events = _parse_sse(r.text)
    kinds = [e[0] for e in events]
    assert "queued" in kinds
    assert kinds.index("queued") < kinds.index("started")
    assert kinds[-1] == "done"
    assert dict(events)["queued"]["reason"] == "gpu_busy"


def test_convert_pdf_streams_started_done(sample_pdf_bytes):
    by_event, kinds = _run_convert("sample.pdf", sample_pdf_bytes, "application/pdf")
    assert kinds[0] == "started" and kinds[-1] == "done"
    assert by_event["started"]["converter"] == "pdf-pymupdf4llm"
    assert by_event["started"]["gpu"] is False
    assert_golden(by_event["done"]["markdown"], "pdf/sample.md")


def test_convert_corrupted_pdf_streams_conversion_failed():
    by_event, kinds = _run_convert("broken.pdf", b"not a real pdf at all", "application/pdf")
    assert kinds[-1] == "error"
    assert by_event["error"]["code"] == "CONVERSION_FAILED"


@pytest.mark.gpu
@requires_gpu_runtime
def test_convert_sse_routes_pdf_through_marker_when_gpu_enabled(monkeypatch, sample_pdf_bytes):
    """End-to-end SSE: when MDFLOW_FORCE_CPU is unset, /convert selects
    pdf-marker (first-wins ahead of pdf-pymupdf4llm) and the GPU branch
    streams started.gpu=True via gpu_semaphore (Codex M2b rec 4)."""
    monkeypatch.delenv("MDFLOW_FORCE_CPU", raising=False)
    app = create_app()
    with TestClient(app) as client:
        r = client.post(
            "/convert",
            files={"file": ("a.pdf", sample_pdf_bytes, "application/pdf")},
        )
    events = _parse_sse(r.text)
    by_event = dict(events)
    kinds = [e[0] for e in events]
    assert by_event["started"]["converter"] == "pdf-marker"
    assert by_event["started"]["gpu"] is True
    assert kinds[-1] == "done"


class _BoomGpuConverter:
    name = "boom-gpu"
    formats = ("txt",)
    requires_gpu = True

    def can_handle(self, ctx):
        return ctx.format in self.formats

    def convert(self, ctx, progress):
        raise ValueError("gpu boom")


def test_gpu_converter_error_releases_lock_and_streams_conversion_failed():
    app = create_app()
    with TestClient(app) as client:
        _swap_registry(app, _BoomGpuConverter())
        r = client.post("/convert", files={"file": ("a.txt", b"hi", "text/plain")})
        # The GPU semaphore must be released even when the converter raises.
        assert app.state.pool.gpu_semaphore.locked() is False
    events = _parse_sse(r.text)
    assert events[-1][0] == "error"
    assert dict(events)["error"]["code"] == "CONVERSION_FAILED"


async def test_gpu_disconnect_keeps_semaphore_until_task_completes():
    """Client disconnect mid-conversion must NOT free the GPU semaphore while
    the executor thread is still running (it can't be cancelled) — otherwise a
    second GPU conversion could run concurrently and break VRAM serialization.
    The semaphore is released only when the conversion task actually finishes.

    Driven via raw ASGI (httpx ASGITransport buffers the whole response, so it
    can't observe mid-flight state). We feed the body, let the response stream
    its first chunk, send http.disconnect, and watch the semaphore.
    """
    import threading

    in_convert = threading.Event()
    release = threading.Event()

    class _BlockingGpuConverter:
        name = "blocking-gpu"
        formats = ("txt",)
        requires_gpu = True

        def can_handle(self, ctx):
            return ctx.format in self.formats

        def convert(self, ctx, progress):
            from mdflow.converters.base import ConversionResult

            in_convert.set()
            release.wait(timeout=5)
            return ConversionResult(markdown="gpu", metadata={})

    boundary = "BNDRY"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="a.txt"\r\n'
        "Content-Type: text/plain\r\n\r\n"
        "hi\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "path": "/convert",
        "raw_path": b"/convert",
        "query_string": b"",
        "root_path": "",
        "scheme": "http",
        "headers": [
            (b"host", b"t"),
            (b"content-type", f"multipart/form-data; boundary={boundary}".encode()),
            (b"content-length", str(len(body)).encode()),
        ],
        "server": ("t", 80),
        "client": ("t", 1234),
    }

    do_disconnect = asyncio.Event()
    first_chunk = asyncio.Event()
    body_sent = False

    async def receive():
        nonlocal body_sent
        if not body_sent:
            body_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await do_disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body" and message.get("body"):
            first_chunk.set()

    app = create_app()
    async with app.router.lifespan_context(app):
        _swap_registry(app, _BlockingGpuConverter())
        sem = app.state.pool.gpu_semaphore

        app_task = asyncio.ensure_future(app(scope, receive, send))
        # Wait until the response has emitted its first body chunk (the GPU
        # branch has acquired the semaphore and the converter is running).
        await asyncio.wait_for(first_chunk.wait(), timeout=5)
        await asyncio.to_thread(in_convert.wait, 5)
        assert sem.locked() is True  # held while converting

        do_disconnect.set()  # client disconnects mid-conversion
        await asyncio.sleep(0.3)
        assert sem.locked() is True, "semaphore freed on disconnect while task still running"

        release.set()  # let the executor task finish -> done-callback releases
        for _ in range(50):
            if not sem.locked():
                break
            await asyncio.sleep(0.1)
        assert sem.locked() is False

        app_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await app_task


async def test_gpu_cached_hit_skips_gpu_branch_even_when_semaphore_busy():
    """A cache hit returns cached->done BEFORE the GPU branch, so it must not
    emit queued/started or touch the GPU semaphore even when it is held."""
    app = create_app()
    async with app.router.lifespan_context(app):
        _swap_registry(app, _FakeGpuConverter())
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            r1 = await client.post("/convert", files={"file": ("a.txt", b"cacheme", "text/plain")})
            assert [k for k, _ in _parse_sse(r1.text)][-1] == "done"  # cache populated
            await app.state.pool.gpu_semaphore.acquire()  # GPU busy
            try:
                r2 = await client.post(
                    "/convert", files={"file": ("a.txt", b"cacheme", "text/plain")}
                )
            finally:
                app.state.pool.gpu_semaphore.release()
    kinds = [k for k, _ in _parse_sse(r2.text)]
    assert kinds == ["cached", "done"]


def test_convert_doc_libreoffice_unavailable_streams_error(monkeypatch):
    # Force soffice-absent at converter construction so the office path
    # raises LIBREOFFICE_UNAVAILABLE, and assert it surfaces as an SSE error.
    monkeypatch.setattr("mdflow.converters.office.shutil.which", lambda _name: None)
    by_event, kinds = _run_convert("sample.doc", b"placeholder doc bytes", "application/msword")
    assert kinds[-1] == "error"
    assert by_event["error"]["code"] == "LIBREOFFICE_UNAVAILABLE"
    assert by_event["error"]["retryable"] is False


@requires_soffice
def test_convert_doc_streams_started_done(sample_doc_bytes):
    by_event, kinds = _run_convert("sample.doc", sample_doc_bytes, "application/msword")
    assert kinds[0] == "started" and kinds[-1] == "done"
    assert by_event["started"]["converter"] == "office-libreoffice"
    assert by_event["started"]["gpu"] is False
    assert "Document Title" in by_event["done"]["markdown"]


@requires_soffice
def test_convert_ppt_streams_started_done(sample_ppt_bytes):
    by_event, kinds = _run_convert("sample.ppt", sample_ppt_bytes, "application/vnd.ms-powerpoint")
    assert kinds[0] == "started" and kinds[-1] == "done"
    assert by_event["started"]["converter"] == "office-libreoffice"
    assert by_event["started"]["gpu"] is False
    assert "First Slide" in by_event["done"]["markdown"]


_HWP_FIXTURE = Path(__file__).parent.parent / "fixtures" / "hwp" / "sample.hwp"


def _pyhwp_available() -> bool:
    try:
        import hwp5.hwp5html  # noqa: F401
        import hwp5.xmlmodel  # noqa: F401

        return True
    except ImportError:
        return False


def test_convert_hwp_streams_started_done(monkeypatch):
    from mdflow.converters.hwp import HwpConverter

    xhtml = b"<html><body><h1>HWP Heading</h1><p>body text</p></body></html>"
    monkeypatch.setattr(HwpConverter, "_hwp_to_xhtml", lambda self, src_path: xhtml)
    by_event, kinds = _run_convert("sample.hwp", b"fake-hwp", "application/x-hwp")
    assert kinds[0] == "started" and kinds[-1] == "done"
    assert by_event["started"]["converter"] == "hwp-pyhwp"
    assert by_event["started"]["gpu"] is False
    assert "HWP Heading" in by_event["done"]["markdown"]


def test_convert_hwp_library_error_streams_conversion_failed(monkeypatch):
    from mdflow.converters.hwp import HwpConverter

    def boom(self, src_path):
        raise ValueError("lxml.etree.XMLSyntaxError simulated")

    monkeypatch.setattr(HwpConverter, "_hwp_to_xhtml", boom)
    by_event, kinds = _run_convert("sample.hwp", b"fake-hwp", "application/x-hwp")
    assert kinds[-1] == "error"
    assert by_event["error"]["code"] == "CONVERSION_FAILED"


def test_convert_hwp_missing_pyhwp_streams_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "hwp5.xmlmodel", None)
    monkeypatch.setitem(sys.modules, "hwp5.hwp5html", None)
    by_event, kinds = _run_convert("sample.hwp", b"fake-hwp", "application/x-hwp")
    assert kinds[-1] == "error"
    assert by_event["error"]["code"] == "HWP_UNAVAILABLE"
    assert by_event["error"]["retryable"] is False


@pytest.mark.skipif(
    not (_HWP_FIXTURE.exists() and _pyhwp_available()),
    reason="needs pyhwp installed and tests/fixtures/hwp/sample.hwp present",
)
def test_convert_hwp_real_fixture():
    data = _HWP_FIXTURE.read_bytes()
    by_event, kinds = _run_convert("sample.hwp", data, "application/x-hwp")
    assert kinds[-1] == "done"
    assert by_event["started"]["converter"] == "hwp-pyhwp"
    assert len(by_event["done"]["markdown"]) > 0
