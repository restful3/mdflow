"""FastAPI app boot: factory, lifespan state wiring, /healthz.

Task 14 (M0.F). Also covers Codex memo #10: the Settings -> UrlPolicy
helper that the URL convert path (M1) consumes, built once at boot.
"""

from fastapi.testclient import TestClient

from mdflow.api.app import create_app, url_policy_from_settings
from mdflow.settings import Settings


def test_healthz_returns_ok():
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "uptime_s" in body
    assert isinstance(body["uptime_s"], (int, float))
    assert body["uptime_s"] >= 0


def test_app_lifespan_initializes_state():
    app = create_app()
    with TestClient(app):
        assert hasattr(app.state, "settings")
        assert hasattr(app.state, "capabilities")
        assert hasattr(app.state, "service")
        assert hasattr(app.state, "url_policy")


def test_url_policy_from_settings_maps_fields():
    """Codex memo #10: map the 6 URL-related MDFLOW_* settings onto a
    UrlPolicy. max_url_input_mb is MB; UrlPolicy.max_bytes is bytes.
    """
    settings = Settings(
        allow_private_urls=True,
        url_max_redirects=2,
        max_url_input_mb=7,
        url_connect_timeout_s=3.0,
        url_read_timeout_s=8.0,
        url_user_agent="test-agent/1.0",
    )
    policy = url_policy_from_settings(settings)
    assert policy.allow_private_urls is True
    assert policy.max_redirects == 2
    assert policy.max_bytes == 7 * 1024 * 1024
    assert policy.connect_timeout_s == 3.0
    assert policy.read_timeout_s == 8.0
    assert policy.user_agent == "test-agent/1.0"
