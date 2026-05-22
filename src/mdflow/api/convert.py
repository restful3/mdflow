"""POST /convert — SSE streaming conversion.

The async route runs the synchronous ConversionService in the CPU thread
pool while streaming progress. A progress callback marshals thread-pool
callbacks onto the event loop via call_soon_threadsafe and pushes them to
an asyncio.Queue that the SSE generator drains.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, Request, UploadFile
from fastapi.responses import StreamingResponse

from mdflow.core.errors import MdflowError
from mdflow.core.events import Done, Error, Progress, Started
from mdflow.core.service import ConvertRequest


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
        except TimeoutError:
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
                yield _sse(
                    "error", Error(code=e.code.value, message=e.message, retryable=e.retryable)
                )
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
            yield _sse(
                "done",
                Done(
                    markdown=resp.result.markdown,
                    metadata=resp.result.metadata,
                    assets=resp.result.assets,
                ),
            )

        return StreamingResponse(stream(), media_type="text/event-stream")
