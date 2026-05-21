"""End-to-end smoke for the M0 chassis.

Exercises the assembled skeleton (not a single unit):
  - ConversionService direct call: text passthrough -> ConvertResponse
  - Cache hit on repeat (same bytes + options + detected_format)
  - URL fetch helper validates and rejects a non-http(s) target
  - FastAPI /healthz + /capabilities through TestClient

create_app() reads Settings from the env (cache_dir defaults to the real
~/.cache/mdflow); the autouse fixture redirects it to a tmp dir so the
smoke run never touches the user's real cache.
"""

import pytest
from fastapi.testclient import TestClient

from mdflow.api.app import create_app
from mdflow.core.errors import ErrorCode, MdflowError
from mdflow.core.service import ConvertRequest
from mdflow.core.url_fetch import validate_url

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _isolated_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MDFLOW_CACHE_DIR", str(tmp_path / "cache"))


def test_m0_service_text_passthrough_then_cache(monkeypatch):
    monkeypatch.setenv("MDFLOW_FORCE_CPU", "1")
    app = create_app()
    with TestClient(app) as client:
        service = app.state.service
        req = ConvertRequest(data=b"hello mdflow", filename_hint="a.txt")
        r1 = service.convert(req)
        r2 = service.convert(req)
        assert r1.cached is False
        assert r2.cached is True
        assert r1.result.markdown == "hello mdflow"
        assert r2.sha256 == r1.sha256

        body = client.get("/capabilities").json()
        assert body["cache"]["hit_count"] >= 1


def test_m0_url_fetch_validates_and_blocks_non_http():
    with pytest.raises(MdflowError) as exc:
        validate_url("file:///etc/passwd")
    assert exc.value.code is ErrorCode.URL_INVALID


def test_m0_healthz_basic():
    app = create_app()
    with TestClient(app) as client:
        body = client.get("/healthz").json()
    assert body["ok"] is True
