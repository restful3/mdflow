from fastapi.testclient import TestClient

from mdflow.api.app import create_app


def _caps(client):
    return client.get("/capabilities").json()["metrics"]


def test_metrics_start_at_zero():
    with TestClient(create_app()) as client:
        m = _caps(client)
    assert m["requests"] == 0 and m["failures"] == 0 and m["failure_rate"] == 0.0


def test_metrics_record_success_and_failure():
    with TestClient(create_app()) as client:
        client.post("/convert", files={"file": ("a.txt", b"hello", "text/plain")})
        client.post(
            "/convert",
            files={"file": ("blob", b"\x00\x01\x02\x03", "application/octet-stream")},
        )  # FORMAT_DETECT_FAILED -> error
        m = _caps(client)
    assert m["requests"] == 2
    assert m["failures"] == 1
    assert m["failure_rate"] == 0.5
    assert m["avg_latency_ms"] >= 0.0


def test_metrics_cache_hit_rate():
    with TestClient(create_app()) as client:
        client.post("/convert", files={"file": ("a.txt", b"cacheme", "text/plain")})
        client.post("/convert", files={"file": ("a.txt", b"cacheme", "text/plain")})
        m = _caps(client)
    assert m["cache_hit_rate"] > 0.0
