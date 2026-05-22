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
from mdflow.api.convert import register_convert_route
from mdflow.core.cache import Cache
from mdflow.core.service import ConversionService
from mdflow.mcp.server import build_mcp
from mdflow.runtime.capabilities import Capabilities, detect
from mdflow.runtime.composition import build_registry, url_policy_from_settings
from mdflow.runtime.concurrency import ConcurrencyPool
from mdflow.settings import Settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    settings = Settings()
    capabilities = detect()
    Capabilities.log_boot(capabilities)

    registry = build_registry(settings)

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
    # The MCP streamable-HTTP sub-app has its own lifespan (session manager);
    # the FastAPI lifespan must enter both _lifespan (mdflow runtime on
    # app.state) and the MCP app's lifespan. The MCP server builds its own
    # runtime singletons but shares the disk cache_dir, so get_cached sees
    # entries written by /convert.
    # allow_path=False: the HTTP-mounted MCP must not expose convert_file(path=)
    # arbitrary server-local file reads (Codex M4 blocking). stdio (mdflow-mcp)
    # keeps path for local-client convenience.
    mcp_app = build_mcp(allow_path=False).http_app(path="/")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with _lifespan(app), mcp_app.lifespan(app):
            yield

    app = FastAPI(title="mdflow", lifespan=lifespan)

    @app.get("/healthz")
    def healthz() -> dict:
        uptime = time.monotonic() - app.state.started_at
        return {"ok": True, "uptime_s": uptime}

    register_admin_routes(app)
    register_convert_route(app)
    app.mount("/mcp", mcp_app)
    return app
