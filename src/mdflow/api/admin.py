"""Admin endpoints: /capabilities, /cache/{sha256} GET/DELETE, /cache/purge.

Task 15 (M0.F). Thin routes over app.state.{capabilities,registry,cache}.
An invalid sha (cache._validate_sha raises ValueError) becomes 400; a
well-formed but absent sha becomes 404.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request

from mdflow.core.errors import MdflowError


def _mdflow_http_error(e: MdflowError) -> HTTPException:
    # Surface a normalized MdflowError as a structured 503 (these codes are
    # retryable, e.g. CACHE_IO_ERROR) instead of leaking a raw 500.
    return HTTPException(
        status_code=503,
        detail={"code": e.code.value, "message": e.message, "retryable": e.retryable},
    )


def _hit_rate(stats: dict) -> float:
    total = stats.get("hit_count", 0) + stats.get("miss_count", 0)
    return round(stats.get("hit_count", 0) / total, 4) if total else 0.0


def register_admin_routes(app: FastAPI) -> None:
    @app.get("/capabilities")
    def capabilities(request: Request) -> dict:
        state = request.app.state
        cache_stats = state.cache.stats()
        return {
            "gpu": state.capabilities.gpu,
            "cuda_version": state.capabilities.cuda_version,
            "cpu_workers": state.capabilities.cpu_workers,
            "formats": state.registry.list_formats(),
            "cache": cache_stats,
            "metrics": {**state.metrics.snapshot(), "cache_hit_rate": _hit_rate(cache_stats)},
        }

    @app.get("/cache/{sha256}")
    def cache_get(sha256: str, request: Request) -> dict:
        try:
            entry = request.app.state.cache.read(sha256)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except MdflowError as e:
            raise _mdflow_http_error(e) from e
        if entry is None:
            raise HTTPException(status_code=404, detail="cache miss")
        return {
            "markdown": entry.markdown,
            "metadata": entry.metadata,
            "assets": entry.assets,
        }

    @app.delete("/cache/{sha256}")
    def cache_delete(sha256: str, request: Request) -> dict:
        try:
            removed = request.app.state.cache.delete(sha256)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        if not removed:
            raise HTTPException(status_code=404, detail="cache miss")
        return {"ok": True}

    @app.post("/cache/purge")
    def cache_purge(request: Request) -> dict:
        removed = request.app.state.cache.purge()
        return {"removed": removed}
