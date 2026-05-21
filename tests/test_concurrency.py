"""ConcurrencyPool — GPU semaphore (capacity=1) + CPU thread pool.

Plan risk R3 — asyncio.Semaphore binds to the running event loop on
first await; for clean lifespan behavior every test that exercises
gpu_lock instantiates the pool inside asyncio.run() so the semaphore
and the awaiting coroutines share a loop.
"""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

from mdflow.runtime.concurrency import ConcurrencyPool


def test_pool_has_gpu_semaphore_and_cpu_executor():
    pool = ConcurrencyPool(cpu_workers=4)
    try:
        assert pool.gpu_semaphore is not None
        assert isinstance(pool.cpu_executor, ThreadPoolExecutor)
    finally:
        pool.shutdown()


def test_gpu_lock_serializes_concurrent_acquirers():
    """Three coroutines holding gpu_lock for 50 ms each must run sequentially,
    so entry timestamps are at least ~50 ms apart."""

    async def run() -> list[float]:
        pool = ConcurrencyPool(cpu_workers=2)
        try:
            timestamps: list[float] = []

            async def task() -> None:
                async with pool.gpu_lock():
                    timestamps.append(time.monotonic())
                    await asyncio.sleep(0.05)

            await asyncio.gather(task(), task(), task())
            return timestamps
        finally:
            pool.shutdown()

    times = asyncio.run(run())
    gaps = [times[i + 1] - times[i] for i in range(len(times) - 1)]
    assert len(gaps) == 2
    assert all(g >= 0.04 for g in gaps), f"gaps too small: {gaps}"


def test_gpu_lock_releases_on_exception():
    """If a task inside gpu_lock raises, the semaphore must still be released
    so a follow-up acquirer succeeds without hanging."""

    async def run() -> bool:
        pool = ConcurrencyPool(cpu_workers=2)
        try:
            try:
                async with pool.gpu_lock():
                    raise RuntimeError("boom")
            except RuntimeError:
                pass

            # If gpu_lock leaked the semaphore, this would block forever.
            async with asyncio.timeout(1.0):
                async with pool.gpu_lock():
                    pass
            return True
        finally:
            pool.shutdown()

    assert asyncio.run(run()) is True


def test_cpu_executor_runs_submitted_callable():
    pool = ConcurrencyPool(cpu_workers=2)
    try:
        fut = pool.cpu_executor.submit(lambda: 1 + 1)
        assert fut.result(timeout=1.0) == 2
    finally:
        pool.shutdown()


def test_shutdown_is_idempotent():
    pool = ConcurrencyPool(cpu_workers=2)
    pool.shutdown()
    pool.shutdown()  # second call must not raise
