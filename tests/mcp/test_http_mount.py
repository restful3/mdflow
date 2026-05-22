from fastapi.testclient import TestClient

from mdflow.api.app import create_app


def test_mcp_mounted_and_existing_routes_intact():
    app = create_app()
    assert any(getattr(r, "path", "") == "/mcp" for r in app.routes)
    with TestClient(app) as client:
        # existing routes still work
        assert client.get("/healthz").json()["ok"] is True
        # MCP streamable endpoint is mounted: a bare request hits the MCP
        # handler (406 Not Acceptable: needs MCP Accept headers), NOT a 404.
        assert client.get("/mcp/").status_code != 404
