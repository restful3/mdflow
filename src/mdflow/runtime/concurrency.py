"""Shared concurrency primitives — GPU semaphore + CPU thread pool.

PRD §3.2 — the v1 runtime keeps a single process with:
  * an asyncio.Semaphore(1) guarding GPU-bound converters, so VRAM is
    released between calls (matches PaperFlow's del-model + empty_cache
    pattern at one-model-per-process)
  * a ThreadPoolExecutor for offloading synchronous converter libraries
    (mammoth, python-pptx, marker, ...) without blocking the event loop.

Plan risk R3 — asyncio.Semaphore is event-loop-bound on first await.
Create the pool inside the FastAPI lifespan (async context) so the
semaphore and the request coroutines share a loop. Constructing the
pool synchronously is fine on Python ≥ 3.10 because the loop is bound
lazily on the first acquire.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager


class ConcurrencyPool:
    """Holds a single GPU semaphore and a CPU thread pool for the process."""

    def __init__(self, cpu_workers: int) -> None:
        self.gpu_semaphore: asyncio.Semaphore = asyncio.Semaphore(1)
        self.cpu_executor: ThreadPoolExecutor = ThreadPoolExecutor(
            max_workers=cpu_workers, thread_name_prefix="mdflow-cpu"
        )
        self._closed = False

    @asynccontextmanager
    async def gpu_lock(self) -> AsyncIterator[None]:
        await self.gpu_semaphore.acquire()
        try:
            yield
        finally:
            self.gpu_semaphore.release()

    def shutdown(self) -> None:
        if self._closed:
            return
        self.cpu_executor.shutdown(wait=False, cancel_futures=True)
        self._closed = True
