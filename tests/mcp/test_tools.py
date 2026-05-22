import base64

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from mdflow.mcp.server import build_mcp
from mdflow.settings import Settings


@pytest.fixture
def mcp():
    return build_mcp(Settings())


async def test_lists_four_tools(mcp):
    async with Client(mcp) as client:
        names = {t.name for t in await client.list_tools()}
    assert names == {"convert_file", "convert_url", "list_formats", "get_cached"}


async def test_list_formats(mcp):
    async with Client(mcp) as client:
        rows = (await client.call_tool("list_formats", {})).data
    names = {r["converter"] for r in rows}
    assert "hwp-pyhwp" in names and "text-passthrough" in names
    exts = {r["ext"] for r in rows}
    assert {"hwp", "doc", "ppt", "pdf", "docx"}.issubset(exts)


async def test_convert_file_base64(mcp):
    b64 = base64.b64encode(b"hello mcp").decode()
    async with Client(mcp) as client:
        r = (
            await client.call_tool("convert_file", {"filename": "a.txt", "content_base64": b64})
        ).data
    assert r["markdown"] == "hello mcp"
    assert len(r["sha256"]) == 64
    assert r["metadata"]["converter"] == "text-passthrough"


async def test_convert_file_path(mcp, tmp_path):
    p = tmp_path / "b.txt"
    p.write_bytes(b"from path")
    async with Client(mcp) as client:
        r = (await client.call_tool("convert_file", {"filename": "b.txt", "path": str(p)})).data
    assert r["markdown"] == "from path"


async def test_convert_file_requires_exactly_one_source(mcp):
    async with Client(mcp) as client:
        with pytest.raises(ToolError):
            await client.call_tool("convert_file", {"filename": "a.txt"})


async def test_convert_file_too_large(monkeypatch):
    monkeypatch.setenv("MDFLOW_MAX_INPUT_MB", "1")
    monkeypatch.setenv("MDFLOW_MAX_URL_INPUT_MB", "1")
    big = base64.b64encode(b"x" * (2 * 1024 * 1024)).decode()
    async with Client(build_mcp(Settings())) as client:
        with pytest.raises(ToolError):
            await client.call_tool("convert_file", {"filename": "a.txt", "content_base64": big})


async def test_convert_file_conversion_error_maps_to_toolerror(mcp, monkeypatch):
    # Force the selected converter to raise a non-MdflowError; run_conversion
    # wraps it as CONVERSION_FAILED, which _run maps to ToolError("[CODE]..").
    import mdflow.converters.text as text_mod

    def boom(self, ctx, progress):
        raise ValueError("kaboom")

    monkeypatch.setattr(text_mod.TextConverter, "convert", boom)
    async with Client(build_mcp(Settings())) as client:
        b64 = base64.b64encode(b"data").decode()
        with pytest.raises(ToolError) as exc:
            await client.call_tool("convert_file", {"filename": "a.txt", "content_base64": b64})
    assert "CONVERSION_FAILED" in str(exc.value)


async def test_convert_url_composes_fetch_metadata(mcp, monkeypatch):
    import mdflow.mcp.tools as tools
    from mdflow.converters.base import ConversionResult
    from mdflow.core.service import ConvertResponse
    from mdflow.core.url_pipeline import UrlConvertResponse

    def fake(url, **kw):
        resp = ConvertResponse(
            result=ConversionResult(markdown="URL MD", metadata={"converter": "text-passthrough"}),
            sha256="a" * 64,
            cached=False,
            detected_format="txt",
            converter_name="text-passthrough",
        )
        return UrlConvertResponse(response=resp, fetch={"source_url": url, "http_status": 200})

    monkeypatch.setattr(tools, "convert_from_url", fake)
    async with Client(mcp) as client:
        r = (await client.call_tool("convert_url", {"url": "https://x/y.txt"})).data
    assert r["markdown"] == "URL MD"
    assert r["metadata"]["fetch"]["source_url"] == "https://x/y.txt"
    assert r["metadata"]["input_kind"] == "url"
    assert r["sha256"] == "a" * 64


async def test_get_cached_hit_after_convert(mcp):
    b64 = base64.b64encode(b"cache me").decode()
    async with Client(mcp) as client:
        conv = (
            await client.call_tool("convert_file", {"filename": "a.txt", "content_base64": b64})
        ).data
        sha = conv["sha256"]
        hit = (await client.call_tool("get_cached", {"sha256": sha})).data
    assert hit["markdown"] == "cache me"


async def test_get_cached_miss_returns_none(mcp):
    async with Client(mcp) as client:
        r = (await client.call_tool("get_cached", {"sha256": "0" * 64})).data
    assert r is None


async def test_get_cached_bad_sha_raises(mcp):
    async with Client(mcp) as client:
        with pytest.raises(ToolError):
            await client.call_tool("get_cached", {"sha256": "nothex"})
