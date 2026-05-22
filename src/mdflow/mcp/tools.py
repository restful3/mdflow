"""The 4 MCP tools wrapping ConversionService over FastMCP.

Async tools offload the synchronous ConversionService to a thread
(loop.run_in_executor) so the event loop is not blocked. The converter's
synchronous progress(stage, pct) callback is marshalled to
ctx.report_progress via asyncio.run_coroutine_threadsafe — the SSE
handler's call_soon_threadsafe analogue (thread -> loop safe,
fire-and-forget; report_progress no-ops without a client progressToken).

MdflowError (CONVERSION_FAILED, HWP_UNAVAILABLE, URL_*, ...) is mapped to
ToolError("[CODE] message"); ConversionService.run_conversion already
wraps non-MdflowError converter exceptions as CONVERSION_FAILED.

GPU serialization is intentionally not applied here: no requires_gpu
converter is registered (M2b deferred), so service.convert (lookup+run)
is called directly. M2b will revisit SSE and MCP GPU gating together.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError

from mdflow.core.errors import MdflowError
from mdflow.core.service import ConvertRequest
from mdflow.core.url_pipeline import convert_from_url

if TYPE_CHECKING:
    from mdflow.mcp.server import Runtime


def register_tools(mcp: FastMCP, runtime: Runtime) -> None:
    async def _run(ctx: Context | None, call: Callable[[Callable[[str, int], None]], Any]) -> Any:
        loop = asyncio.get_running_loop()

        def on_progress(stage: str, pct: int) -> None:
            if ctx is not None:
                asyncio.run_coroutine_threadsafe(ctx.report_progress(pct, 100, stage), loop)

        try:
            return await loop.run_in_executor(None, lambda: call(on_progress))
        except MdflowError as e:
            raise ToolError(f"[{e.code.value}] {e.message}") from e

    @mcp.tool
    async def convert_file(
        filename: str,
        content_base64: str | None = None,
        path: str | None = None,
        options: dict | None = None,
        ctx: Context = None,
    ) -> dict:
        if (content_base64 is None) == (path is None):
            raise ToolError("provide exactly one of: content_base64 or path")
        if content_base64 is not None:
            try:
                data = base64.b64decode(content_base64, validate=True)
            except (ValueError, binascii.Error) as e:
                raise ToolError(f"invalid base64 content: {e}") from e
        else:
            try:
                data = Path(path).read_bytes()
            except OSError as e:
                raise ToolError(f"cannot read path: {e}") from e
        max_bytes = runtime.settings.max_input_mb * 1024 * 1024
        if len(data) > max_bytes:
            raise ToolError(
                f"input exceeds MDFLOW_MAX_INPUT_MB ({runtime.settings.max_input_mb} MB)"
            )
        req = ConvertRequest(data=data, filename_hint=filename, options=options or {})
        resp = await _run(ctx, lambda p: runtime.service.convert(req, p))
        return {
            "markdown": resp.result.markdown,
            "metadata": resp.result.metadata,
            "sha256": resp.sha256,
        }

    @mcp.tool
    async def convert_url(url: str, options: dict | None = None, ctx: Context = None) -> dict:
        out = await _run(
            ctx,
            lambda p: convert_from_url(
                url,
                policy=runtime.url_policy,
                service=runtime.service,
                options=options or {},
                progress=p,
            ),
        )
        resp = out.response
        meta = {**resp.result.metadata, "fetch": out.fetch, "input_kind": "url"}
        return {"markdown": resp.result.markdown, "metadata": meta, "sha256": resp.sha256}

    @mcp.tool
    async def list_formats() -> list[dict]:
        return runtime.registry.list_formats()

    @mcp.tool
    async def get_cached(sha256: str) -> dict | None:
        try:
            cached = runtime.cache.read(sha256)
        except ValueError as e:
            raise ToolError(str(e)) from e
        except MdflowError as e:
            raise ToolError(f"[{e.code.value}] {e.message}") from e
        if cached is None:
            return None
        return {"markdown": cached.markdown, "metadata": cached.metadata}
