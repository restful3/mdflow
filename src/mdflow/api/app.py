"""FastAPI app factory + lifespan + /healthz.

Task 14 (M0.F). The lifespan is the composition root: it builds the
runtime singletons (Settings, Capabilities, Registry, Cache,
ConcurrencyPool, ConversionService) and stores them on app.state.

Plan risk R3 — ConcurrencyPool holds an asyncio.Semaphore that binds to
the running event loop. It is constructed here, inside the async
lifespan, so request coroutines share that loop.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI

from mdflow.api.admin import register_admin_routes
from mdflow.converters.text import TextConverter
from mdflow.core.cache import Cache
from mdflow.core.registry import Registry
from mdflow.core.service import ConversionService
from mdflow.core.url_fetch import UrlPolicy
from mdflow.runtime.capabilities import Capabilities, detect
from mdflow.runtime.concurrency import ConcurrencyPool
from mdflow.settings import Settings

logger = logging.getLogger(__name__)


def url_policy_from_settings(settings: Settings) -> UrlPolicy:
    """Map the 6 URL-related MDFLOW_* settings onto a UrlPolicy.

    Codex memo #10. max_url_input_mb is megabytes; UrlPolicy.max_bytes
    is bytes.
    """
    return UrlPolicy(
        allow_private_urls=settings.allow_private_urls,
        max_redirects=settings.url_max_redirects,
        max_bytes=settings.max_url_input_mb * 1024 * 1024,
        connect_timeout_s=settings.url_connect_timeout_s,
        read_timeout_s=settings.url_read_timeout_s,
        user_agent=settings.url_user_agent,
    )


@asynccontextmanager
async def _lifespan(app: FastAPI):
    settings = Settings()
    capabilities = detect()
    Capabilities.log_boot(capabilities)

    registry = Registry()
    registry.register(TextConverter())

    cache = Cache(settings.cache_dir)
    pool = ConcurrencyPool(cpu_workers=capabilities.cpu_workers)
    service = ConversionService(registry=registry, cache=cache)

    app.state.started_at = time.monotonic()
    app.state.settings = settings
    app.state.capabilities = capabilities
    app.state.registry = registry
    app.state.cache = cache
    app.state.pool = pool
    app.state.service = service
    app.state.url_policy = url_policy_from_settings(settings)
    try:
        yield
    finally:
        pool.shutdown()


def create_app() -> FastAPI:
    app = FastAPI(title="mdflow", lifespan=_lifespan)

    @app.get("/healthz")
    def healthz() -> dict:
        uptime = time.monotonic() - app.state.started_at
        return {"ok": True, "uptime_s": uptime}

    register_admin_routes(app)
    return app
