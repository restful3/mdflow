# M1a SSE Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `POST /convert` SSE streaming endpoint that runs the existing synchronous `ConversionService` in a thread pool while streaming progress, cached, done, and error events.

**Architecture:** An async FastAPI route builds an `asyncio.Queue`; a progress callback marshals thread-pool callbacks onto the loop via `loop.call_soon_threadsafe`. `ConversionService.convert()` is split into `lookup()` (detect + key + cache read + converter select) and `run_conversion()` (convert + enrich + cache write) so the handler can emit `started` (miss) vs `cached` (hit) before conversion. URL input has the handler call `fetch_url` in the executor, then reuse the common path.

**Tech Stack:** FastAPI `StreamingResponse`, `asyncio` (Queue, run_in_executor, call_soon_threadsafe), existing `mdflow.core` (events, service, cache, url_fetch), pytest + `fastapi.testclient`.

**Spec:** `docs/specs/2026-05-22-m1a-sse-infrastructure-design.md`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `src/mdflow/core/cache.py` | Modify | Add `cached_at(sha)` returning entry mtime as ISO-8601 (for the `cached` event) |
| `src/mdflow/core/service.py` | Modify | Split `convert()` into `lookup()` + `run_conversion()` + `LookupResult`; keep `convert()` as a thin wrapper |
| `src/mdflow/api/convert.py` | Create | `register_convert_route(app)`: parse input, event pump, SSE stream for file + url |
| `src/mdflow/api/app.py` | Modify | Call `register_convert_route(app)` in `create_app()` |
| `tests/test_cache.py` | Modify | Test `cached_at` |
| `tests/test_service.py` | Modify | Test `lookup` / `run_conversion`; existing tests must stay green |
| `tests/api/test_convert.py` | Create | SSE line-parsing tests (file miss/hit, url, error, validation) + event pump ordering |

---

## Task 0: Add `python-multipart` dependency (required for file upload)

FastAPI's `UploadFile` and `request.form()` require `python-multipart`, which is not currently a dependency. Without it, Task 3's file upload raises `RuntimeError: Form data requires "python-multipart" to be installed`.

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, add to the `dependencies` list (after `chardet>=5.2`):

```toml
    "python-multipart>=0.0.9",
```

- [ ] **Step 2: Install into the venv**

Run: `.venv/bin/pip install -e ".[dev]"`
Expected: installs `python-multipart`. Verify: `.venv/bin/python -c "import multipart; print(multipart.__version__)"` prints a version.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build(m1): add python-multipart for /convert file upload"
```

---

## Task 1: `Cache.cached_at(sha)` for the cached event

**Files:**
- Modify: `src/mdflow/core/cache.py`
- Test: `tests/test_cache.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cache.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cache.py::test_cache_cached_at_returns_iso_for_existing_entry -v`
Expected: FAIL with `AttributeError: 'Cache' object has no attribute 'cached_at'`.

- [ ] **Step 3: Implement `cached_at`**

In `src/mdflow/core/cache.py`, add the imports if missing at the top (`datetime` is not yet imported):

```python
import datetime as _dt
```

Add this method to the `Cache` class (after `read`):

```python
def cached_at(self, sha: str) -> str | None:
    """ISO-8601 (UTC) publish time of a cache entry, derived from the
    entry directory mtime (set by os.replace in write). None if absent.
    Used by the SSE `cached` event; the cache does not store a separate
    timestamp in meta.json.
    """
    entry = self._entry_dir(sha)
    if not entry.exists():
        return None
    ts = entry.stat().st_mtime
    return _dt.datetime.fromtimestamp(ts, tz=_dt.UTC).isoformat()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_cache.py -q`
Expected: PASS (all cache tests).

- [ ] **Step 5: Commit**

```bash
git add src/mdflow/core/cache.py tests/test_cache.py
git commit -m "feat(m1): Cache.cached_at() for the SSE cached event"
```

---

## Task 2: Split `ConversionService.convert` into `lookup` + `run_conversion`

**Files:**
- Modify: `src/mdflow/core/service.py`
- Test: `tests/test_service.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_service.py` (reuse existing fixtures/imports; `Registry`, `Cache`, `TextConverter`, `ConvertRequest` are already used there):

```python
def test_lookup_miss_selects_converter_and_returns_no_cache(tmp_cache_dir):
    registry = Registry()
    registry.register(TextConverter())
    service = ConversionService(registry=registry, cache=Cache(tmp_cache_dir))

    lr = service.lookup(ConvertRequest(data=b"hello", filename_hint="a.txt"))

    assert lr.cached is None
    assert lr.cached_at is None
    assert lr.detected_format == "txt"
    assert lr.converter is not None
    assert lr.converter.name == "text-passthrough"


def test_run_conversion_then_lookup_hit(tmp_cache_dir):
    registry = Registry()
    registry.register(TextConverter())
    service = ConversionService(registry=registry, cache=Cache(tmp_cache_dir))
    req = ConvertRequest(data=b"hello", filename_hint="a.txt")

    lr1 = service.lookup(req)
    resp = service.run_conversion(req, lr1)
    assert resp.cached is False
    assert resp.result.markdown == "hello"

    lr2 = service.lookup(req)
    assert lr2.cached is not None
    assert lr2.cached_at is not None
    assert lr2.cached.markdown == "hello"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_service.py::test_lookup_miss_selects_converter_and_returns_no_cache -v`
Expected: FAIL with `AttributeError: 'ConversionService' object has no attribute 'lookup'`.

- [ ] **Step 3: Implement the split**

In `src/mdflow/core/service.py`, add the import for the converter type and a `LookupResult` dataclass. At the top imports add:

```python
from mdflow.converters.base import ConversionContext, ConversionResult, Converter
```

(That line currently imports `ConversionContext, ConversionResult` — add `Converter`.)

Add after the `ConvertResponse` dataclass:

```python
@dataclass
class LookupResult:
    sha: str
    detected_format: str
    detection_source: str
    detection_warnings: list[str]
    cached: ConversionResult | None
    cached_at: str | None
    converter: Converter | None  # selected on miss; None on hit
```

Replace the existing `convert` method body with the split. The new methods:

```python
def lookup(self, req: ConvertRequest) -> LookupResult:
    detection = detect_format(
        req.data,
        req.filename_hint,
        content_type_hint=req.content_type_hint,
    )
    if detection.format is None:
        raise MdflowError(
            ErrorCode.FORMAT_DETECT_FAILED,
            "extension and magic-bytes both unknown",
        )
    sha = compute_cache_key(req.data, req.options, detected_format=detection.format)
    cached = self.cache.read(sha)
    if cached is not None:
        return LookupResult(
            sha=sha,
            detected_format=detection.format,
            detection_source=detection.source,
            detection_warnings=detection.warnings,
            cached=cached,
            cached_at=self.cache.cached_at(sha),
            converter=None,
        )
    ctx = ConversionContext(
        data=req.data,
        filename_hint=req.filename_hint,
        format=detection.format,
        options=req.options,
        metadata={"format": detection.format},
    )
    converter = self.registry.select(ctx)
    return LookupResult(
        sha=sha,
        detected_format=detection.format,
        detection_source=detection.source,
        detection_warnings=detection.warnings,
        cached=None,
        cached_at=None,
        converter=converter,
    )

def run_conversion(
    self,
    req: ConvertRequest,
    lookup: LookupResult,
    progress: ProgressCallback = _noop_progress,
) -> ConvertResponse:
    assert lookup.converter is not None  # caller guarantees a miss
    ctx = ConversionContext(
        data=req.data,
        filename_hint=req.filename_hint,
        format=lookup.detected_format,
        options=req.options,
        metadata={"format": lookup.detected_format},
    )
    result = lookup.converter.convert(ctx, progress)

    enriched_meta = dict(result.metadata)
    enriched_meta.setdefault("converter", lookup.converter.name)
    enriched_meta.setdefault("format", lookup.detected_format)
    enriched_meta.setdefault("detection_source", lookup.detection_source)
    if lookup.detection_warnings:
        enriched_meta.setdefault("detection_warnings", lookup.detection_warnings)
    result = ConversionResult(
        markdown=result.markdown,
        metadata=enriched_meta,
        assets=result.assets,
    )

    self.cache.write(lookup.sha, result, options=req.options)
    return ConvertResponse(
        result=result,
        sha256=lookup.sha,
        cached=False,
        detected_format=lookup.detected_format,
        converter_name=lookup.converter.name,
    )

def convert(
    self,
    req: ConvertRequest,
    progress: ProgressCallback = _noop_progress,
) -> ConvertResponse:
    lr = self.lookup(req)
    if lr.cached is not None:
        return ConvertResponse(
            result=lr.cached,
            sha256=lr.sha,
            cached=True,
            detected_format=lr.detected_format,
            converter_name=lr.cached.metadata.get("converter", ""),
        )
    return self.run_conversion(req, lr, progress)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_service.py -q`
Expected: PASS — the two new tests AND all pre-existing service tests (regression: `convert()` behavior is unchanged).

- [ ] **Step 5: Commit**

```bash
git add src/mdflow/core/service.py tests/test_service.py
git commit -m "refactor(m1): split ConversionService into lookup + run_conversion"
```

---

## Task 3: SSE helpers + `/convert` file path (miss: started -> progress -> done)

**Files:**
- Create: `src/mdflow/api/convert.py`
- Modify: `src/mdflow/api/app.py`
- Test: `tests/api/test_convert.py`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_convert.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/api/test_convert.py::test_convert_file_miss_streams_started_then_done -v`
Expected: FAIL with 404 (route not registered) — `assert r.status_code == 200` fails.

- [ ] **Step 3: Create `src/mdflow/api/convert.py`**

```python
"""POST /convert — SSE streaming conversion.

The async route runs the synchronous ConversionService in the CPU thread
pool while streaming progress. A progress callback marshals thread-pool
callbacks onto the event loop via call_soon_threadsafe and pushes them to
an asyncio.Queue that the SSE generator drains.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, Request, UploadFile
from fastapi.responses import StreamingResponse

from mdflow.core.errors import MdflowError
from mdflow.core.events import Done, Error, Progress, Started
from mdflow.core.service import ConvertRequest

_PCT_DONE = 100


def _sse(event: str, payload: Any) -> str:
    return f"event: {event}\ndata: {payload.model_dump_json()}\n\n"


async def _drain_until_done(q: asyncio.Queue, task: asyncio.Future) -> AsyncIterator[Progress]:
    """Yield queued Progress events until the conversion task finishes and
    the queue is empty. Polls with a short timeout so a finished task is
    not blocked behind an empty queue.
    """
    while not (task.done() and q.empty()):
        try:
            ev = await asyncio.wait_for(q.get(), timeout=0.05)
        except asyncio.TimeoutError:
            continue
        yield ev


def register_convert_route(app: FastAPI) -> None:
    @app.post("/convert")
    async def convert(request: Request, file: UploadFile) -> StreamingResponse:
        data = await file.read()
        req = ConvertRequest(data=data, filename_hint=file.filename)
        service = request.app.state.service
        pool = request.app.state.pool
        loop = asyncio.get_running_loop()

        async def stream() -> AsyncIterator[str]:
            q: asyncio.Queue = asyncio.Queue()

            def on_progress(stage: str, pct: int) -> None:
                loop.call_soon_threadsafe(q.put_nowait, Progress(stage=stage, pct=pct))

            try:
                lr = await loop.run_in_executor(pool.cpu_executor, service.lookup, req)
            except MdflowError as e:
                yield _sse("error", Error(code=e.code.value, message=e.message, retryable=e.retryable))
                return

            yield _sse(
                "started",
                Started(converter=lr.converter.name, gpu=lr.converter.requires_gpu, sha256=lr.sha),
            )
            task = asyncio.ensure_future(
                loop.run_in_executor(pool.cpu_executor, service.run_conversion, req, lr, on_progress)
            )
            async for ev in _drain_until_done(q, task):
                yield _sse("progress", ev)
            try:
                resp = task.result()
            except MdflowError as e:
                yield _sse("error", Error(code=e.code.value, message=e.message, retryable=e.retryable))
                return
            yield _sse(
                "done",
                Done(markdown=resp.result.markdown, metadata=resp.result.metadata, assets=resp.result.assets),
            )

        return StreamingResponse(stream(), media_type="text/event-stream")
```

Note: `json` is imported for symmetry with future payloads; if ruff flags it as unused, remove it.

- [ ] **Step 4: Register the route in `app.py`**

In `src/mdflow/api/app.py`, add the import next to the admin import:

```python
from mdflow.api.convert import register_convert_route
```

In `create_app()`, after `register_admin_routes(app)`:

```python
    register_convert_route(app)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/api/test_convert.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/mdflow/api/convert.py src/mdflow/api/app.py tests/api/test_convert.py
git commit -m "feat(m1): POST /convert SSE file path (started -> progress -> done)"
```

---

## Task 4: `/convert` cache-hit path (cached -> done)

**Files:**
- Modify: `src/mdflow/api/convert.py`
- Test: `tests/api/test_convert.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/api/test_convert.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/api/test_convert.py::test_convert_file_hit_streams_cached_then_done -v`
Expected: FAIL — on a hit the current code calls `lr.converter.name` where `converter` is None → `AttributeError`, surfacing as a 500/stream error, so `kinds == ["cached", "done"]` fails.

- [ ] **Step 3: Add the cache-hit branch**

In `src/mdflow/api/convert.py`, add the `Cached` import:

```python
from mdflow.core.events import Cached, Done, Error, Progress, Started
```

In `stream()`, immediately after the `lookup` succeeds and before the `started` event, insert:

```python
            if lr.cached is not None:
                yield _sse("cached", Cached(sha256=lr.sha, cached_at=lr.cached_at or ""))
                yield _sse(
                    "done",
                    Done(markdown=lr.cached.markdown, metadata=lr.cached.metadata, assets=lr.cached.assets),
                )
                return
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/api/test_convert.py -v`
Expected: PASS (both file tests).

- [ ] **Step 5: Commit**

```bash
git add src/mdflow/api/convert.py tests/api/test_convert.py
git commit -m "feat(m1): POST /convert cache-hit path (cached -> done)"
```

---

## Task 5: `/convert` error path (unsupported / undetectable format)

**Files:**
- Test: `tests/api/test_convert.py` (behavior already implemented in Task 3's MdflowError handling)

- [ ] **Step 1: Write the failing test**

Add to `tests/api/test_convert.py`:

```python
def test_convert_unknown_format_streams_error():
    app = create_app()
    with TestClient(app) as client:
        # No extension, binary bytes with no magic match -> FORMAT_DETECT_FAILED
        r = client.post("/convert", files={"file": ("blob", b"\x00\x01\x02\x03", "application/octet-stream")})
    assert r.status_code == 200
    events = _parse_sse(r.text)
    assert events[-1][0] == "error"
    assert events[-1][1]["code"] == "FORMAT_DETECT_FAILED"
    assert events[-1][1]["retryable"] is False
```

- [ ] **Step 2: Run test to verify it passes (or fails meaningfully)**

Run: `.venv/bin/python -m pytest tests/api/test_convert.py::test_convert_unknown_format_streams_error -v`
Expected: PASS — Task 3 already maps `MdflowError` from `lookup` to an `error` event. If it FAILS because the bytes happen to be detected as a known format, change the payload to one that `detect_format` cannot classify (e.g. a single NUL byte `b"\x00"` with filename `"blob"`).

- [ ] **Step 3: Commit**

```bash
git add tests/api/test_convert.py
git commit -m "test(m1): POST /convert error path (FORMAT_DETECT_FAILED)"
```

---

## Task 6: `/convert` url path (fetch in executor -> common path)

**Files:**
- Modify: `src/mdflow/api/convert.py`
- Test: `tests/api/test_convert.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/api/test_convert.py` (monkeypatch the module-level `fetch_url` so no real network is used):

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/api/test_convert.py::test_convert_url_streams_fetch_progress_then_done -v`
Expected: FAIL — the route signature requires a `file` UploadFile, so a JSON body returns 422.

- [ ] **Step 3: Support both file and url input**

Rewrite the route in `src/mdflow/api/convert.py` to branch on content type. Add imports:

```python
from mdflow.core.url_fetch import FetchResult, fetch_url
```

Replace the route definition (the `@app.post("/convert")` function) with a version that reads either a multipart file or a JSON `{url}`:

```python
    @app.post("/convert")
    async def convert(request: Request) -> StreamingResponse:
        content_type = request.headers.get("content-type", "")
        service = request.app.state.service
        pool = request.app.state.pool
        url_policy = request.app.state.url_policy
        loop = asyncio.get_running_loop()

        file_bytes: bytes | None = None
        filename: str | None = None
        url: str | None = None

        if content_type.startswith("multipart/form-data"):
            form = await request.form()
            upload = form.get("file")
            if isinstance(upload, UploadFile):
                file_bytes = await upload.read()
                filename = upload.filename
        elif content_type.startswith("application/json"):
            body = await request.json()
            url = body.get("url")

        async def stream() -> AsyncIterator[str]:
            q: asyncio.Queue = asyncio.Queue()

            def on_progress(stage: str, pct: int) -> None:
                loop.call_soon_threadsafe(q.put_nowait, Progress(stage=stage, pct=pct))

            # Resolve input -> ConvertRequest (+ optional fetch metadata).
            fetch_meta: dict[str, Any] | None = None
            try:
                if url is not None:
                    fetched: FetchResult = await loop.run_in_executor(
                        pool.cpu_executor, fetch_url, url, url_policy
                    )
                    req = ConvertRequest(
                        data=fetched.data,
                        filename_hint=fetched.filename_hint,
                        content_type_hint=fetched.content_type,
                    )
                    fetch_meta = {
                        "source_url": fetched.source_url,
                        "effective_url": fetched.effective_url,
                        "http_status": fetched.http_status,
                        "content_type": fetched.content_type,
                        "content_length": fetched.content_length,
                        "content_disposition": fetched.content_disposition,
                        "filename_hint": fetched.filename_hint,
                        "fetched_at": fetched.fetched_at,
                        "redirect_count": fetched.redirect_count,
                        "fetch_warnings": fetched.fetch_warnings,
                    }
                    yield _sse("progress", Progress(stage="fetch", pct=_PCT_DONE, detail=url))
                else:
                    req = ConvertRequest(data=file_bytes, filename_hint=filename)
            except MdflowError as e:
                yield _sse("error", Error(code=e.code.value, message=e.message, retryable=e.retryable))
                return

            try:
                lr = await loop.run_in_executor(pool.cpu_executor, service.lookup, req)
            except MdflowError as e:
                yield _sse("error", Error(code=e.code.value, message=e.message, retryable=e.retryable))
                return

            if lr.cached is not None:
                yield _sse("cached", Cached(sha256=lr.sha, cached_at=lr.cached_at or ""))
                yield _sse("done", _done_event(lr.cached, fetch_meta))
                return

            yield _sse(
                "started",
                Started(converter=lr.converter.name, gpu=lr.converter.requires_gpu, sha256=lr.sha),
            )
            task = asyncio.ensure_future(
                loop.run_in_executor(pool.cpu_executor, service.run_conversion, req, lr, on_progress)
            )
            async for ev in _drain_until_done(q, task):
                yield _sse("progress", ev)
            try:
                resp = task.result()
            except MdflowError as e:
                yield _sse("error", Error(code=e.code.value, message=e.message, retryable=e.retryable))
                return
            yield _sse("done", _done_event(resp.result, fetch_meta))

        return StreamingResponse(stream(), media_type="text/event-stream")
```

Add this helper near `_sse` (it composes the `done` payload, folding fetch metadata under `metadata.fetch` per PRD §5.1):

```python
def _done_event(result, fetch_meta: dict[str, Any] | None) -> Done:
    metadata = dict(result.metadata)
    if fetch_meta is not None:
        metadata = {**metadata, "fetch": fetch_meta, "input_kind": "url"}
    return Done(markdown=result.markdown, metadata=metadata, assets=result.assets)
```

The `UploadFile` import is still required for the `isinstance` check.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/api/test_convert.py -v`
Expected: PASS (file miss, file hit, error, url).

- [ ] **Step 5: Commit**

```bash
git add src/mdflow/api/convert.py tests/api/test_convert.py
git commit -m "feat(m1): POST /convert url path (fetch in executor -> common flow)"
```

---

## Task 7: `/convert` input validation (neither / both inputs)

**Files:**
- Modify: `src/mdflow/api/convert.py`
- Test: `tests/api/test_convert.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/api/test_convert.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/api/test_convert.py::test_convert_no_input_returns_400 -v`
Expected: FAIL — currently `file_bytes` and `url` are both None, so `ConvertRequest(data=None, ...)` is built and the stream errors instead of returning 400.

- [ ] **Step 3: Validate before streaming**

In `src/mdflow/api/convert.py`, add the `HTTPException` import:

```python
from fastapi import FastAPI, HTTPException, Request, UploadFile
```

After the input-parsing block (where `file_bytes`, `filename`, `url` are resolved) and BEFORE defining `stream()`, add:

```python
        has_file = file_bytes is not None
        has_url = bool(url)
        if has_file == has_url:  # neither, or both
            raise HTTPException(
                status_code=400,
                detail="provide exactly one of: multipart 'file' or JSON 'url'",
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/api/test_convert.py -v`
Expected: PASS (all convert tests).

- [ ] **Step 5: Commit**

```bash
git add src/mdflow/api/convert.py tests/api/test_convert.py
git commit -m "feat(m1): POST /convert input validation (exactly one of file/url)"
```

---

## Task 8: Event-pump ordering unit test + full verification

**Files:**
- Test: `tests/api/test_convert.py`

- [ ] **Step 1: Write a progress-ordering test**

This verifies the thread-callback -> queue -> SSE ordering using a converter that reports progress. Add to `tests/api/test_convert.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/api/test_convert.py::test_convert_streams_progress_events_in_order -v`
Expected: PASS. If progress events arrive out of order or are missing, the event pump (`call_soon_threadsafe` + queue drain) is wrong — fix `_drain_until_done`.

- [ ] **Step 3: Full suite + lint**

Run:
```bash
.venv/bin/python -m pytest
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
```
Expected: all pass, no regressions, ruff + format clean.

- [ ] **Step 4: Commit**

```bash
git add tests/api/test_convert.py
git commit -m "test(m1): POST /convert progress-ordering through the event pump"
```

---

## Task 9: Update PROCESS_STATE + M1a Codex review checkpoint

**Files:**
- Modify: `PROCESS_STATE.md`

- [ ] **Step 1: Update PROCESS_STATE**

Mark M1a complete in `PROCESS_STATE.md`: phase → M1a done, test count, next action (M1b plan). Record that recommendation #3 (pool wiring) from the M0 API review is now resolved (the `/convert` handler runs conversion through `pool.cpu_executor`).

- [ ] **Step 2: Commit**

```bash
git add PROCESS_STATE.md
git commit -m "docs(state): M1a SSE infrastructure complete"
```

- [ ] **Step 3: Codex review checkpoint**

Per project rule (CLAUDE.md §3) and the agreed cadence ([[feedback-codex-review-cadence]]), send the M1a bundle for Codex review before starting M1b. Bundle: `src/mdflow/api/convert.py`, `src/mdflow/core/service.py` (split), `src/mdflow/core/cache.py` (cached_at), `tests/api/test_convert.py`, `tests/test_service.py`, `tests/test_cache.py` deltas.

---

## Self-Review

**Spec coverage (vs `docs/specs/2026-05-22-m1a-sse-infrastructure-design.md`):**

- §2.1 `POST /convert` SSE handler → Tasks 3-7
- §2.1 async↔sync orchestration (event pump) → Task 3 (`_drain_until_done`, `call_soon_threadsafe`), Task 8 (ordering test)
- §2.1 `ConcurrencyPool.cpu_executor` wiring → Task 3 (run_in_executor on `pool.cpu_executor`)
- §2.1 url input via `fetch_url` in executor → Task 6
- §2.1 validated over TextConverter → Tasks 3-8 use txt
- §4 service split `lookup`/`run_conversion` + `convert` wrapper → Task 2
- §5 data flow (file miss/hit, url, error) → Tasks 3,4,5,6
- §5 `cached_at` for cached event → Task 1
- §5 `done.metadata.fetch` synthesis (incl. cache hit) → Task 6 (`_done_event`); cache-hit+url synthesis covered because `_done_event(lr.cached, fetch_meta)` runs on the hit branch
- §6 error handling (400 vs in-stream error) → Task 7 (400), Tasks 3/5/6 (in-stream error, HTTP 200)
- §7 testing (SSE parse, pump unit, regression) → Tasks 3-8
- Out-of-scope items (GPU/queued, shutdown drain, content_base64) → correctly absent

**Placeholder scan:** No TBD/TODO. Every code step has complete code. Task 9 Step 1 describes a doc edit (prose state update) rather than code — acceptable, it is not a code step.

**Type consistency:** `LookupResult` fields (`sha`, `detected_format`, `detection_source`, `detection_warnings`, `cached`, `cached_at`, `converter`) defined in Task 2 and consumed consistently in Tasks 3/4/6. `ConvertRequest(data, filename_hint, content_type_hint)` matches the existing dataclass. Event models (`Started.converter/gpu/sha256`, `Progress.stage/pct/detail`, `Cached.sha256/cached_at`, `Done.markdown/metadata/assets`, `Error.code/message/retryable`) match `core/events.py`. `fetch_url(url, policy, *, transport=None)` and `FetchResult` fields match `core/url_fetch.py`. `_done_event` and `_sse` helper names are consistent across tasks.

**Note for executor:** Tasks 3 and 6 both edit the `@app.post("/convert")` function; Task 6 rewrites it wholesale (file+url). When executing, Task 6's version supersedes Task 3's. This is intentional incremental construction, not duplication.
