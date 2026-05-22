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
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.datastructures import UploadFile

from mdflow.core.errors import ErrorCode, MdflowError
from mdflow.core.events import Cached, Done, Error, Progress, Started
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
    return Done(markdown=result.markdown, metadata=metadata, assets=result.assets)


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
            form = await request.form()
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

            yield _sse(
                "started",
                Started(converter=lr.converter.name, gpu=lr.converter.requires_gpu, sha256=lr.sha),
            )
            task = asyncio.ensure_future(
                loop.run_in_executor(
                    pool.cpu_executor, service.run_conversion, req, lr, on_progress
                )
            )
            async for ev in _drain_until_done(q, task):
                yield _sse("progress", ev)
            try:
                resp = task.result()
            except MdflowError as e:
                yield _sse(
                    "error", Error(code=e.code.value, message=e.message, retryable=e.retryable)
                )
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

        return StreamingResponse(stream(), media_type="text/event-stream")
