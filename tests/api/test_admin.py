"""Admin endpoints: /capabilities, /cache/{sha256} GET/DELETE, /cache/purge."""

from fastapi.testclient import TestClient

from mdflow.api.app import create_app
from mdflow.converters.base import ConversionResult


def test_capabilities_reports_gpu_and_formats(monkeypatch):
    monkeypatch.setenv("MDFLOW_FORCE_CPU", "1")
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/capabilities")
    assert r.status_code == 200
    body = r.json()
    assert body["gpu"] is False
    assert body["cpu_workers"] >= 1
    assert any(f["ext"] == "txt" for f in body["formats"])
    assert "cache" in body
    assert body["cache"]["entries"] >= 0


def test_cache_get_unknown_returns_404():
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/cache/" + "a" * 64)
    assert r.status_code == 404
    assert r.json()["detail"] == "cache miss"


def test_cache_get_corrupt_meta_returns_503():
    """Codex M0-api review #1: Cache.read() raises MdflowError(CACHE_IO_ERROR)
    on a corrupt meta.json; the admin route must map it to a structured 503
    (retryable) instead of leaking a raw 500.
    """
    app = create_app()
    with TestClient(app) as client:
        sha = "d" * 64
        entry = app.state.cache.root / sha
        entry.mkdir(parents=True)
        (entry / "result.md").write_text("# x", encoding="utf-8")
        (entry / "meta.json").write_text("{not valid json", encoding="utf-8")
        r = client.get(f"/cache/{sha}")
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert detail["code"] == "CACHE_IO_ERROR"
    assert detail["retryable"] is True


def test_cache_get_invalid_sha_returns_400():
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/cache/notasha")
    assert r.status_code == 400


def test_cache_write_then_get_returns_payload():
    app = create_app()
    with TestClient(app) as client:
        sha = "f" * 64
        app.state.cache.write(
            sha,
            ConversionResult(markdown="# hi", metadata={"converter": "text"}),
            options={},
        )
        r = client.get(f"/cache/{sha}")
    assert r.status_code == 200
    body = r.json()
    assert body["markdown"] == "# hi"
    assert body["metadata"]["converter"] == "text"


def test_cache_delete_then_get_returns_404():
    app = create_app()
    with TestClient(app) as client:
        sha = "b" * 64
        app.state.cache.write(sha, ConversionResult(markdown="x"), options={})
        r1 = client.delete(f"/cache/{sha}")
        assert r1.status_code == 200
        assert r1.json() == {"ok": True}
        r2 = client.get(f"/cache/{sha}")
        assert r2.status_code == 404


def test_cache_delete_unknown_returns_404():
    app = create_app()
    with TestClient(app) as client:
        r = client.delete("/cache/" + "c" * 64)
    assert r.status_code == 404
    assert r.json()["detail"] == "cache miss"


def test_cache_purge_clears_all():
    app = create_app()
    with TestClient(app) as client:
        app.state.cache.write("1" * 64, ConversionResult(markdown="a"), options={})
        app.state.cache.write("2" * 64, ConversionResult(markdown="b"), options={})
        r = client.post("/cache/purge")
    assert r.status_code == 200
    body = r.json()
    assert body["removed"] >= 2
