"""mdflow CLI (Typer).

`mdflow convert <file|--url>` does a synchronous one-shot conversion reusing
the shared composition (build_registry/url_policy_from_settings); `mdflow serve`
runs the FastAPI app under uvicorn. The MCP stdio server is the separate
`mdflow-mcp` entrypoint.
"""

from __future__ import annotations

from pathlib import Path

import typer
import uvicorn

from mdflow.api.app import create_app
from mdflow.core.cache import Cache
from mdflow.core.errors import MdflowError
from mdflow.core.service import ConversionService, ConvertRequest
from mdflow.core.url_pipeline import convert_from_url
from mdflow.runtime.composition import build_registry, url_policy_from_settings
from mdflow.settings import Settings

app = typer.Typer(help="mdflow - document to Markdown gateway", add_completion=False)


@app.command()
def convert(
    file: Path | None = typer.Argument(None, help="input file path"),
    url: str | None = typer.Option(None, "--url", help="fetch and convert a URL"),
    output: Path | None = typer.Option(
        None, "-o", "--output", help="write markdown here (default: stdout)"
    ),
) -> None:
    """Convert a local file or a URL to Markdown."""
    if (file is None) == (url is None):
        typer.secho("provide exactly one of: FILE or --url", err=True, fg=typer.colors.RED)
        raise typer.Exit(2)

    settings = Settings()
    registry = build_registry(settings)
    cache = Cache(settings.cache_dir)
    service = ConversionService(registry=registry, cache=cache)

    try:
        if url is not None:
            out = convert_from_url(url, policy=url_policy_from_settings(settings), service=service)
            markdown = out.response.result.markdown
        else:
            data = file.read_bytes()
            resp = service.convert(ConvertRequest(data=data, filename_hint=file.name))
            markdown = resp.result.markdown
    except MdflowError as e:
        typer.secho(f"[{e.code.value}] {e.message}", err=True, fg=typer.colors.RED)
        raise typer.Exit(1) from e
    except OSError as e:
        typer.secho(f"cannot read input: {e}", err=True, fg=typer.colors.RED)
        raise typer.Exit(1) from e

    if output is not None:
        output.write_text(markdown, encoding="utf-8")
    else:
        typer.echo(markdown)


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the mdflow HTTP API (FastAPI/uvicorn)."""
    uvicorn.run(create_app(), host=host, port=port)
