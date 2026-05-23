"""POST /convert — SSE streaming conversion.

The async route runs the synchronous ConversionService in the CPU thread
pool while streaming progress. A progress callback marshals thread-pool
callbacks onto the event loop via call_soon_threadsafe and pushes them to
an asyncio.Queue that the SSE generator drains.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.datastructures import UploadFile

from mdflow.core.errors import ErrorCode, MdflowError
from mdflow.core.events import Cached, Done, Error, Progress, Queued, Started
from mdflow.core.service import ConvertRequest
from mdflow.core.url_fetch import FetchResult, fetch_url

logger = logging.getLogger(__name__)

_PCT_DONE = 100


def _sse(event: str, payload: Any) -> str:
    return f"event: {event}\ndata: {payload.model_dump_json()}\n\n"


def _done_event(result: Any, fetch_meta: dict[str, Any] | None) -> Done:
    metadata = dict(result.metadata)
    if fetch_meta is not None:
        metadata = {**metadata, "fetch": fetch_meta, "input_kind": "url"}
    return Done(markdown=result.markdown, metadata=metadata, assets=[])


async def _drain_until_done(q: asyncio.Queue, task: asyncio.Future) -> AsyncIterator[Progress]:
    """Yield queued Progress events until the conversion task finishes and
    the queue is empty. Polls with a short timeout so a finished task is
    not blocked behind an empty queue.
    """
    while not (task.done() and q.empty()):
        try:
            ev = await asyncio.wait_for(q.get(), timeout=0.05)
        except TimeoutError:
            continue
        yield ev


async def _run_conversion_stream(
    lr: Any,
    task: asyncio.Future,
    q: asyncio.Queue,
    fetch_meta: dict[str, Any] | None,
) -> AsyncIterator[str]:
    """Emit started -> progress* -> done|error for an already-scheduled
    conversion `task`. The caller owns task creation and (for GPU) the
    semaphore lifecycle, so a client disconnect that closes this generator
    cannot release the GPU slot while the executor thread is still running."""
    yield _sse(
        "started",
        Started(converter=lr.converter.name, gpu=lr.converter.requires_gpu, sha256=lr.sha),
    )
    async for ev in _drain_until_done(q, task):
        yield _sse("progress", ev)
    try:
        resp = task.result()
    except MdflowError as e:
        yield _sse("error", Error(code=e.code.value, message=e.message, retryable=e.retryable))
        return
    except Exception:
        logger.exception("unexpected error in /convert stream (run_conversion)")
        yield _sse(
            "error",
            Error(
                code=ErrorCode.INTERNAL.value,
                message="internal error",
                retryable=ErrorCode.INTERNAL.retryable,
            ),
        )
        return
    yield _sse("done", _done_event(resp.result, fetch_meta))


async def _metered(gen: AsyncIterator[str], metrics: Any) -> AsyncIterator[str]:
    """Wrap the SSE stream to record one metrics sample per request.

    Observes the terminal event chunk (event: done | event: error) and
    records success/latency once in finally. A client disconnect closes the
    generator with no terminal event, recorded conservatively as a failure.
    The inner stream logic is untouched (single record point).
    """
    t0 = time.monotonic()
    outcome = "error"
    try:
        async for chunk in gen:
            if chunk.startswith("event: done"):
                outcome = "done"
            elif chunk.startswith("event: error"):
                outcome = "error"
            yield chunk
    finally:
        metrics.record(success=(outcome == "done"), latency_s=time.monotonic() - t0)


def register_convert_route(app: FastAPI) -> None:
    @app.post("/convert")
    async def convert(request: Request) -> StreamingResponse:
        content_type = request.headers.get("content-type", "")
        service = request.app.state.service
        pool = request.app.state.pool
        url_policy = request.app.state.url_policy
        settings = request.app.state.settings
        loop = asyncio.get_running_loop()
        max_bytes = settings.max_input_mb * 1024 * 1024

        file_bytes: bytes | None = None
        filename: str | None = None
        url: str | None = None

        if content_type.startswith("multipart/form-data"):
            async with request.form() as form:
                upload = form.get("file")
                if isinstance(upload, UploadFile):
                    file_bytes = await upload.read(max_bytes + 1)
                    filename = upload.filename
        elif content_type.startswith("application/json"):
            try:
                body = await request.json()
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=400, detail="invalid JSON body") from exc
            if not isinstance(body, dict):
                raise HTTPException(status_code=400, detail="JSON body must be an object")
            url = body.get("url")
            if url is not None and not (isinstance(url, str) and url):
                raise HTTPException(status_code=400, detail="'url' must be a non-empty string")

        has_file = file_bytes is not None
        has_url = bool(url)
        if has_file == has_url:  # neither, or both
            raise HTTPException(
                status_code=400,
                detail="provide exactly one of: multipart 'file' or JSON 'url'",
            )

        if has_file and len(file_bytes) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"file exceeds MDFLOW_MAX_INPUT_MB ({settings.max_input_mb} MB)",
            )

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
                yield _sse(
                    "error", Error(code=e.code.value, message=e.message, retryable=e.retryable)
                )
                return
            except Exception:
                logger.exception("unexpected error in /convert stream (fetch)")
                yield _sse(
                    "error",
                    Error(
                        code=ErrorCode.INTERNAL.value,
                        message="internal error",
                        retryable=ErrorCode.INTERNAL.retryable,
                    ),
                )
                return

            try:
                lr = await loop.run_in_executor(pool.cpu_executor, service.lookup, req)
            except MdflowError as e:
                yield _sse(
                    "error", Error(code=e.code.value, message=e.message, retryable=e.retryable)
                )
                return
            except Exception:
                logger.exception("unexpected error in /convert stream (lookup)")
                yield _sse(
                    "error",
                    Error(
                        code=ErrorCode.INTERNAL.value,
                        message="internal error",
                        retryable=ErrorCode.INTERNAL.retryable,
                    ),
                )
                return

            if lr.cached is not None:
                yield _sse("cached", Cached(sha256=lr.sha, cached_at=lr.cached_at or ""))
                yield _sse("done", _done_event(lr.cached, fetch_meta))
                return

            def _start() -> asyncio.Future:
                return asyncio.ensure_future(
                    loop.run_in_executor(
                        pool.cpu_executor, service.run_conversion, req, lr, on_progress
                    )
                )

            if lr.converter.requires_gpu:
                if pool.gpu_semaphore.locked():
                    yield _sse("queued", Queued(reason="gpu_busy", position=1))
                # Hold the GPU slot for the WHOLE compute. Acquire here and
                # release via the task's done-callback (NOT this generator's
                # scope): a client disconnect closes the generator while the
                # executor thread keeps running and cannot be cancelled, so a
                # scope-bound release would free the slot mid-compute and let a
                # second GPU conversion run concurrently — breaking VRAM
                # serialization (Codex M2a blocker).
                await pool.gpu_semaphore.acquire()
                task = _start()
                task.add_done_callback(lambda _: pool.gpu_semaphore.release())
                async for chunk in _run_conversion_stream(lr, task, q, fetch_meta):
                    yield chunk
            else:
                task = _start()
                async for chunk in _run_conversion_stream(lr, task, q, fetch_meta):
                    yield chunk

        return StreamingResponse(
            _metered(stream(), request.app.state.metrics),
            media_type="text/event-stream",
        )
