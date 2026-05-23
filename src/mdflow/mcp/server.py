"""mdflow MCP server (FastMCP).

build_mcp is the composition root: it builds the runtime singletons
(Settings, Registry via build_registry, Cache, ConversionService,
UrlPolicy) — the same set the HTTP lifespan builds — and registers the
4 tools. main() is the `mdflow-mcp` stdio entrypoint.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastmcp import FastMCP

from mdflow.core.cache import Cache
from mdflow.core.registry import Registry
from mdflow.core.service import ConversionService
from mdflow.core.url_fetch import UrlPolicy
from mdflow.mcp.tools import register_tools
from mdflow.runtime.composition import build_registry, url_policy_from_settings
from mdflow.settings import Settings


@dataclass
class Runtime:
    settings: Settings
    registry: Registry
    cache: Cache
    service: ConversionService
    url_policy: UrlPolicy
    # convert_file(path=...) reads the mdflow process filesystem. Safe for the
    # stdio entrypoint (local client) but a server-local file-read surface on
    # the HTTP mount, so create_app builds with allow_path=False.
    allow_path: bool = True


def build_mcp(
    settings: Settings | None = None,
    *,
    allow_path: bool = True,
    allow_gpu: bool = True,
) -> FastMCP:
    """Build the MCP server (stdio or HTTP-mountable).

    `allow_gpu=False` excludes GPU-requiring converters (currently
    MarkerConverter) from the runtime registry. The HTTP-mount in
    create_app() passes allow_gpu=False so the mounted /mcp cannot run
    Marker concurrently with /convert in the same FastAPI process —
    the SSE path's `gpu_semaphore` would otherwise be bypassed
    (Codex M2b blocking).
    """
    settings = settings or Settings()
    registry = build_registry(settings, allow_gpu=allow_gpu)
    cache = Cache(settings.cache_dir)
    runtime = Runtime(
        settings=settings,
        registry=registry,
        cache=cache,
        service=ConversionService(registry=registry, cache=cache),
        url_policy=url_policy_from_settings(settings),
        allow_path=allow_path,
    )
    mcp: FastMCP = FastMCP("mdflow")
    register_tools(mcp, runtime)
    return mcp


def main() -> None:
    build_mcp().run()
