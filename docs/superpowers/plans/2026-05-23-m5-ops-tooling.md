# M5 — Ops Tooling Implementation Plan

> **For agentic workers:** Implement task-by-task with TDD (failing test → verify fail → implement → verify pass → ruff → commit). Steps use checkbox (`- [ ]`).

**Goal:** Add the four operational deliverables: a Typer CLI (`mdflow convert`/`serve`), in-process metrics surfaced on `/capabilities`, a CPU-only Dockerfile, and a `docs/test-matrix.md`. GPU/Marker parts are deferred with M2b.

**Architecture:** CLI reuses the shared composition (`build_registry`, `url_policy_from_settings`) for a synchronous one-shot convert; `serve` runs uvicorn on `create_app()`. Metrics are a tiny in-process `Metrics` counter on `app.state`; the `/convert` route wraps its SSE generator in a `_metered` wrapper that observes terminal `event: done`/`event: error` chunks and records once in a `finally` (no change to the inner stream logic). `/capabilities` adds a `metrics` key plus a derived `cache_hit_rate`. Dockerfile is CPU-only (LibreOffice + fonts-noto-cjk + `.[hwp]`). The test matrix is documentation.

**Tech Stack:** Python 3.12, `typer 0.25.1` (verified, `typer.testing.CliRunner`), existing `uvicorn[standard]`. SSE chunk format from `_sse()` is `event: <name>\ndata: ...\n\n` (verified at `api/convert.py:31`), so `chunk.startswith("event: done"|"event: error")` is a reliable terminal probe.

---

## File Structure

**Source (new):** `src/mdflow/cli.py`, `src/mdflow/core/metrics.py`, `Dockerfile`, `.dockerignore`, `docs/test-matrix.md`.
**Source (modified):** `src/mdflow/api/convert.py` (wrap with `_metered`), `src/mdflow/api/app.py` (`app.state.metrics`), `src/mdflow/api/admin.py` (`metrics` key), `pyproject.toml` (`typer` dep + `mdflow` script).
**Tests (new):** `tests/test_cli.py`, `tests/api/test_metrics.py`.

---

## Important findings from planning

- **`_sse` prefix probe**: terminal events are `event: done` / `event: error`. The cache-hit path emits `event: cached` then `event: done` → final outcome `done`. A client disconnect closes the generator with no terminal event → `_metered`'s default `outcome="error"` records it as a failure (conservative).
- **CLI is server-free**: builds its own `Settings`/`Registry`/`Cache`/`ConversionService` synchronously — no ConcurrencyPool, no Metrics. One-shot convert.
- **`serve` blocks**: test it by monkeypatching `uvicorn.run` (assert called with the app), never by actually serving. The `--help` path lists commands.
- **Metrics live on the HTTP `/convert` path only**: MCP (separate runtime) is out of scope (documented). `cache_hit_rate` is derived in the `/capabilities` route from `cache.stats()` hit/miss, not stored in `Metrics`.

---

## Task 0: typer dependency + `mdflow` script

**Files:** `pyproject.toml`.
- [ ] Add `"typer>=0.12"` to `[project] dependencies`. Add `mdflow = "mdflow.cli:app"` to `[project.scripts]` (keep `mdflow-mcp`).
- [ ] Verify: `.venv/bin/python -c "import typer; print(typer.__version__)"`; `tomllib` shows both scripts.
- [ ] Commit `build(m5): add typer dependency + mdflow CLI entrypoint`.

---

## Task 1: Metrics + /capabilities

**Files:** create `src/mdflow/core/metrics.py`, `tests/api/test_metrics.py`; modify `src/mdflow/api/convert.py`, `src/mdflow/api/app.py`, `src/mdflow/api/admin.py`.

- [ ] **Step 1 (RED):** `tests/api/test_metrics.py`:
```python
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
        f = {"file": ("a.txt", b"cacheme", "text/plain")}
        client.post("/convert", files=f)
        client.post("/convert", files={"file": ("a.txt", b"cacheme", "text/plain")})
        m = _caps(client)
    assert m["cache_hit_rate"] > 0.0
```
Run → FAIL (`KeyError: 'metrics'`).

- [ ] **Step 2 (GREEN):**
  - Create `core/metrics.py` with `Metrics` (spec §4.1).
  - `api/app.py` `_lifespan`: add `app.state.metrics = Metrics()` (import Metrics).
  - `api/convert.py`: add `import time`; add the `_metered` async wrapper (spec §4.2); change the route's return to `StreamingResponse(_metered(stream(), request.app.state.metrics), media_type="text/event-stream")`.
  - `api/admin.py` `/capabilities`: add `"metrics": {**state.metrics.snapshot(), "cache_hit_rate": _hit_rate(state.cache.stats())}` with a module `_hit_rate(stats)` helper (`hit/(hit+miss)`, 0-guard, rounded 4).
  Run → pass.

- [ ] **Step 3:** Full suite + ruff. Commit `feat(m5): in-process request metrics on /capabilities`.

---

## Task 2: CLI

**Files:** create `src/mdflow/cli.py`, `tests/test_cli.py`.

- [ ] **Step 1 (RED):** `tests/test_cli.py`:
```python
from typer.testing import CliRunner
from mdflow.cli import app

runner = CliRunner()


def test_convert_file_to_stdout(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("hello cli")
    r = runner.invoke(app, ["convert", str(p)])
    assert r.exit_code == 0
    assert "hello cli" in r.stdout


def test_convert_file_to_output(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("write me")
    out = tmp_path / "out.md"
    r = runner.invoke(app, ["convert", str(p), "-o", str(out)])
    assert r.exit_code == 0
    assert out.read_text() == "write me"


def test_convert_requires_exactly_one_input(tmp_path):
    assert runner.invoke(app, ["convert"]).exit_code != 0
    p = tmp_path / "a.txt"
    p.write_text("x")
    assert runner.invoke(app, ["convert", str(p), "--url", "https://x/y"]).exit_code != 0


def test_convert_missing_file():
    assert runner.invoke(app, ["convert", "/no/such/file.txt"]).exit_code != 0


def test_serve_invokes_uvicorn(monkeypatch):
    calls = {}
    import mdflow.cli as cli

    def fake_run(app_obj, host, port):
        calls["host"] = host
        calls["port"] = port

    monkeypatch.setattr(cli.uvicorn, "run", fake_run)
    r = runner.invoke(app, ["serve", "--host", "0.0.0.0", "--port", "9000"])
    assert r.exit_code == 0
    assert calls == {"host": "0.0.0.0", "port": 9000}


def test_help_lists_commands():
    out = runner.invoke(app, ["--help"]).stdout
    assert "convert" in out and "serve" in out
```
(Use a per-test `MDFLOW_CACHE_DIR` — add an autouse fixture in `tests/conftest.py` scope or set env in the test. Simplest: an autouse fixture in `tests/test_cli.py` setting `MDFLOW_CACHE_DIR` to tmp.) Run → FAIL (no `mdflow.cli`).

- [ ] **Step 2 (GREEN):** Implement `cli.py` (spec §3). `import uvicorn` at module top (so `cli.uvicorn.run` is monkeypatchable). `serve` calls `uvicorn.run(create_app(), host=host, port=port)`. `convert` validates exactly-one (file xor url), maps `MdflowError`/`OSError` to `typer.Exit(1)`, exactly-one violation to `typer.Exit(2)` (or `typer.BadParameter`). Run → pass.

- [ ] **Step 3:** Full suite + ruff. Commit `feat(m5): mdflow CLI (convert, serve)`.

---

## Task 3: Dockerfile (CPU) + .dockerignore

**Files:** create `Dockerfile`, `.dockerignore`.
- [ ] Write `Dockerfile` per spec §5. Write `.dockerignore` (`.venv`, `.git`, `__pycache__`, `*.pyc`, `tests`, `archive`, `docs`, `.pytest_cache`, `.ruff_cache`).
- [ ] Sanity: `grep` the Dockerfile builds the expected layers; do NOT run `docker build` (heavy, GPU-less, may be unavailable). Note build verification deferred.
- [ ] Commit `build(m5): CPU-only Dockerfile + .dockerignore`.

---

## Task 4: Test matrix doc

**Files:** create `docs/test-matrix.md`.
- [ ] Table: rows = formats (txt/md/csv, docx, pptx, xlsx, html, pdf, doc, ppt, hwp, url-input) ; columns = converter name, test file/location, OS/optional dep, pytest marker / skip condition. Add a deferred row for `pdf-marker` (GPU, M2b). Note the suite baseline count and the 2 expected skips (hwp fixture, url redirect). Cross-check converter set against `build_registry`/`tests/test_composition.py`.
- [ ] Commit `docs(m5): integration test matrix`.

---

## Task 5: State update + Codex review + tag

- [ ] Update `PROCESS_STATE.md` §2/§4/§11: M5 implemented (CLI, metrics, Dockerfile CPU, matrix). New test/lint baseline. GPU Docker + MCP metrics deferred notes.
- [ ] Commit `docs(state): M5 ops tooling implemented`.
- [ ] Codex milestone review (`git diff v0.5.0-m4..HEAD`) via `codex-peer-reviewer`. Focus: (a) `_metered` terminal detection + disconnect-as-failure correctness, single-record-point, no double counting vs the inner stream; (b) metrics thread/loop safety + 0-division guards + cache_hit_rate derivation; (c) CLI exactly-one validation + error→exit-code mapping + `serve` monkeypatchability + composition reuse; (d) Dockerfile correctness (LibreOffice pkgs, `.[hwp]`, no GPU, fonts) and `.dockerignore`; (e) matrix doc matches the registry. Save `docs/reviews/2026-05-23-m5-ops-tooling-codex.md`. Address blocking, then adopt + tag `v0.6.0-m5`.

---

## Self-Review (plan author)

**Spec coverage:** CLI → Task 2; metrics (`Metrics`+`_metered`+capabilities) → Task 1; Dockerfile → Task 3; matrix → Task 4; typer dep → Task 0. ✓
**Placeholder scan:** All code steps show complete code or precise edits; test steps show assertions + run expectations. Dockerfile build is explicitly not run (documented limitation).
**Type consistency:** `Metrics.record(*, success: bool, latency_s: float)`, `Metrics.snapshot() -> dict`; `_metered(gen, metrics)` async-gen wrapping `stream()`; `_hit_rate(stats: dict) -> float` in admin. CLI `app = typer.Typer()`, `mdflow = "mdflow.cli:app"`. `_metered` reads `request.app.state.metrics` set in `_lifespan`. SSE prefixes verified.
**De-risked:** typer 0.25.1 + CliRunner imported OK; `_sse` format confirmed; uvicorn already a dep; `cache.stats()` exposes hit_count/miss_count.
