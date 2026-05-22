# M3a — LibreOffice Converter (doc + ppt) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `LibreOfficeConverter` that converts legacy binary `doc`/`ppt` to Markdown by running `soffice --headless --convert-to pdf` and then composing the existing `PdfConverter` (pymupdf4llm) on the produced PDF.

**Architecture:** Approach A (single converter, internal PDF→MD composition), CPU-only. The converter writes the input bytes to a temp dir, runs LibreOffice headless with a per-call `UserInstallation` profile (so concurrent conversions don't collide on the shared profile lock), reads the produced PDF, and hands those bytes to a held `PdfConverter` instance with a remapped progress callback. Missing soffice → `LIBREOFFICE_UNAVAILABLE`; timeout → `TIMEOUT`; nonzero exit / missing output → `CONVERSION_FAILED`. No new Python dependency (system `soffice` + existing core `pymupdf4llm`). Registration follows the M2 "capability gating + registration order" model — no separate chain executor.

**Tech Stack:** Python 3.11, system LibreOffice (`soffice`, verified 24.2.7.2 on this host), `subprocess` (argv list, no shell), `pymupdf4llm`/`fitz` (reused via `PdfConverter`), FastAPI SSE, pytest with a `requires_soffice` skip marker.

---

## File Structure

**Source (new):**
- `src/mdflow/converters/office.py` — `LibreOfficeConverter` (`name="office-libreoffice"`, `formats=("doc","ppt")`, `requires_gpu=False`). doc/ppt bytes → soffice PDF → `PdfConverter` composition → Markdown.

**Source (modified):**
- `src/mdflow/settings.py` — add `soffice_timeout_s: float = Field(default=120.0, gt=0)`.
- `src/mdflow/api/app.py` — register `LibreOfficeConverter(timeout_s=settings.soffice_timeout_s)` in `_lifespan` after `PdfConverter`.

**Tests (new/modified):**
- `tests/conftest.py` — add a `requires_soffice` skip marker, a `_soffice_to(...)` build helper, and session-scoped `sample_doc_bytes` / `sample_ppt_bytes` fixtures.
- `tests/converters/test_office.py` — converter unit tests: structural (real soffice, marked) + error paths (deterministic, monkeypatched, no soffice needed).
- `tests/api/test_convert.py` — doc/ppt SSE integration tests (real soffice, marked).
- `tests/test_settings.py` — assert the new `soffice_timeout_s` default + env override.

---

## Important findings from planning (read before Task 3)

- **soffice "recovers" garbage input.** Feeding arbitrary bytes named `broken.doc` does NOT fail — soffice loads it as a Writer text document and emits a valid PDF (returncode 0). So a "corrupted doc → CONVERSION_FAILED" test using **real** soffice is unreliable. The plan therefore tests the `CONVERSION_FAILED` branch **deterministically by monkeypatching `subprocess.run`** (nonzero returncode and missing-output cases), not with real corrupted input. This is a deliberate refinement of design §7 (which listed corrupted-doc as integration); the architecture is unchanged.
- **`pymupdf4llm` prints an onnxruntime/GPU-probe warning to stderr** (`Failed to detect devices under /sys/class/drm/card0`). Harmless — it does not affect the Markdown output or return codes. Ignore it in test output.
- **`fitz` import:** `PdfConverter` already imports `fitz` successfully on this host. If a future PyMuPDF drops the `fitz` alias, that is a PdfConverter/M2 concern, not this plan's.

---

## Task 0: Add the soffice timeout setting

**Files:**
- Modify: `src/mdflow/settings.py`
- Modify: `tests/test_settings.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_settings.py`, add `"MDFLOW_SOFFICE_TIMEOUT_S"` to the `_ENV_VARS` list, then add the default assertion to `test_settings_defaults` and a new env-override test.

Add to `_ENV_VARS` (after `"MDFLOW_URL_USER_AGENT",`):
```python
    "MDFLOW_SOFFICE_TIMEOUT_S",
```

Add to `test_settings_defaults` (after the `url_user_agent` assertion):
```python
    assert s.soffice_timeout_s == 120.0
```

Append a new test:
```python
def test_soffice_timeout_env_override(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("MDFLOW_SOFFICE_TIMEOUT_S", "45")
    s = Settings()
    assert s.soffice_timeout_s == 45.0


def test_soffice_timeout_must_be_positive(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("MDFLOW_SOFFICE_TIMEOUT_S", "0")
    with pytest.raises(ValueError):
        Settings()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_settings.py -v`
Expected: FAIL — `test_settings_defaults` and the two new tests fail with `AttributeError`/validation because `soffice_timeout_s` does not exist yet.

- [ ] **Step 3: Add the setting**

In `src/mdflow/settings.py`, add this field after `url_user_agent` (before the `@model_validator`):
```python
    soffice_timeout_s: float = Field(default=120.0, gt=0)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_settings.py -v`
Expected: all pass (the 4 existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add src/mdflow/settings.py tests/test_settings.py
git commit -m "feat(m3): add MDFLOW_SOFFICE_TIMEOUT_S setting"
```

---

## Task 1: doc/ppt fixtures + soffice skip marker

**Files:**
- Modify: `tests/conftest.py`

- [ ] **Step 1: Add the marker, build helper, and fixtures**

At the top of `tests/conftest.py`, the existing imports are `import io`, `from pathlib import Path`, `import pytest`. Add `shutil`, `subprocess`, and `tempfile`:

```python
import io
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
```

Then append at the end of the file:

```python
requires_soffice = pytest.mark.skipif(
    shutil.which("soffice") is None,
    reason="LibreOffice (soffice) not installed",
)


def _soffice_to(src_bytes: bytes, src_ext: str, dst_ext: str) -> bytes:
    """Convert src_bytes (a src_ext document) to dst_ext via soffice headless.

    Used to build legacy binary doc/ppt fixtures from code-generated
    docx/pptx, since there is no pure-Python writer for the legacy
    formats. Caller must be guarded by @requires_soffice.
    """
    soffice = shutil.which("soffice")
    assert soffice is not None, "guarded by @requires_soffice"
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"in.{src_ext}"
        src.write_bytes(src_bytes)
        subprocess.run(
            [
                soffice,
                "--headless",
                "--convert-to",
                dst_ext,
                "--outdir",
                tmp,
                f"-env:UserInstallation=file://{Path(tmp) / 'profile'}",
                str(src),
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
        return (Path(tmp) / f"in.{dst_ext}").read_bytes()


@pytest.fixture(scope="session")
def sample_doc_bytes() -> bytes:
    from docx import Document

    d = Document()
    d.add_heading("Document Title", level=1)
    d.add_heading("Section One", level=2)
    d.add_paragraph("First paragraph of body text for the doc.")
    buf = io.BytesIO()
    d.save(buf)
    return _soffice_to(buf.getvalue(), "docx", "doc")


@pytest.fixture(scope="session")
def sample_ppt_bytes() -> bytes:
    from pptx import Presentation

    prs = Presentation()
    layout = prs.slide_layouts[1]  # Title and Content
    s = prs.slides.add_slide(layout)
    s.shapes.title.text = "First Slide"
    s.placeholders[1].text_frame.text = "Bullet one"
    buf = io.BytesIO()
    prs.save(buf)
    return _soffice_to(buf.getvalue(), "pptx", "ppt")
```

- [ ] **Step 2: Verify the fixtures build real binary office files**

Run:
```bash
.venv/bin/python -c "
import io, shutil, subprocess, tempfile
from pathlib import Path
from docx import Document
d=Document(); d.add_heading('Document Title',1); d.add_paragraph('body')
buf=io.BytesIO(); d.save(buf)
so=shutil.which('soffice')
with tempfile.TemporaryDirectory() as t:
    p=Path(t)/'in.docx'; p.write_bytes(buf.getvalue())
    subprocess.run([so,'--headless','--convert-to','doc','--outdir',t,f'-env:UserInstallation=file://{Path(t)/\"profile\"}',str(p)],check=True,capture_output=True,timeout=120)
    out=(Path(t)/'in.doc').read_bytes()
    print('doc bytes:', len(out), out[:8])
"
```
Expected: prints a positive byte count and the OLE compound signature `b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'`.

- [ ] **Step 3: Verify the suite still collects and passes**

Run: `.venv/bin/pytest -q`
Expected: 240 passed / 1 skipped (current baseline; new fixtures add no tests yet, no collection errors).

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py
git commit -m "test(m3): doc/ppt fixtures built via soffice + requires_soffice marker"
```

---

## Task 2: LibreOfficeConverter (soffice → PDF → PdfConverter)

**Files:**
- Create: `src/mdflow/converters/office.py`
- Create: `tests/converters/test_office.py`

- [ ] **Step 1: Write the failing structural tests**

`tests/converters/test_office.py`:

```python
from mdflow.converters.base import ConversionContext
from mdflow.converters.office import LibreOfficeConverter
from tests.conftest import requires_soffice


def _ctx(data: bytes, fmt: str) -> ConversionContext:
    return ConversionContext(data=data, filename_hint=f"sample.{fmt}", format=fmt)


def test_protocol_attrs():
    conv = LibreOfficeConverter(timeout_s=120.0)
    assert conv.name == "office-libreoffice"
    assert conv.formats == ("doc", "ppt")
    assert conv.requires_gpu is False
    assert conv.can_handle(_ctx(b"", "doc")) is True
    assert conv.can_handle(_ctx(b"", "ppt")) is True
    assert conv.can_handle(_ctx(b"", "pdf")) is False


@requires_soffice
def test_doc_structure(sample_doc_bytes):
    out = LibreOfficeConverter(timeout_s=120.0).convert(
        _ctx(sample_doc_bytes, "doc"), lambda s, p: None
    )
    assert "Document Title" in out.markdown
    assert "Section One" in out.markdown
    assert "First paragraph of body text" in out.markdown
    assert out.metadata["source_format"] == "doc"
    assert out.metadata["engine"] == "libreoffice+pymupdf4llm"
    assert out.metadata["pages"] == 1


@requires_soffice
def test_ppt_structure(sample_ppt_bytes):
    out = LibreOfficeConverter(timeout_s=120.0).convert(
        _ctx(sample_ppt_bytes, "ppt"), lambda s, p: None
    )
    assert "First Slide" in out.markdown
    assert "Bullet one" in out.markdown
    assert out.metadata["source_format"] == "ppt"


@requires_soffice
def test_progress_is_monotonic_nondecreasing(sample_doc_bytes):
    seen: list[tuple[str, int]] = []
    LibreOfficeConverter(timeout_s=120.0).convert(
        _ctx(sample_doc_bytes, "doc"), lambda s, p: seen.append((s, p))
    )
    pcts = [p for _, p in seen]
    assert pcts == sorted(pcts)  # never goes backwards
    assert seen[-1][1] == 100
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/converters/test_office.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mdflow.converters.office'`.

- [ ] **Step 3: Implement `office.py`**

```python
"""doc/ppt -> Markdown via LibreOffice headless -> PDF -> pymupdf4llm.

soffice converts the legacy binary office format to PDF in a temp dir
(per-call UserInstallation profile so concurrent conversions don't
collide on LibreOffice's shared profile lock); the produced PDF is then
handed to the existing PdfConverter via composition with a remapped
progress callback. No internal try/except that swallows errors: a
missing soffice raises LIBREOFFICE_UNAVAILABLE, a timeout raises TIMEOUT,
a nonzero exit / missing output raises CONVERSION_FAILED; PDF-stage
library errors propagate to ConversionService.run_conversion.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from mdflow.converters.base import (
    ConversionContext,
    ConversionResult,
    ProgressCallback,
)
from mdflow.converters.pdf import PdfConverter
from mdflow.core.errors import ErrorCode, MdflowError


class LibreOfficeConverter:
    name = "office-libreoffice"
    formats: tuple[str, ...] = ("doc", "ppt")
    requires_gpu = False

    def __init__(self, timeout_s: float, pdf: PdfConverter | None = None) -> None:
        self._soffice = shutil.which("soffice")
        self._timeout_s = timeout_s
        self._pdf = pdf or PdfConverter()

    def can_handle(self, ctx: ConversionContext) -> bool:
        return ctx.format in self.formats

    def convert(self, ctx: ConversionContext, progress: ProgressCallback) -> ConversionResult:
        if self._soffice is None:
            raise MdflowError(
                ErrorCode.LIBREOFFICE_UNAVAILABLE,
                "soffice (LibreOffice) not found on PATH",
            )
        progress("convert", 5)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / f"input.{ctx.format}"
            src.write_bytes(ctx.data)
            profile = f"-env:UserInstallation=file://{tmp_path / 'lo_profile'}"
            try:
                proc = subprocess.run(
                    [
                        self._soffice,
                        "--headless",
                        "--convert-to",
                        "pdf",
                        "--outdir",
                        str(tmp_path),
                        profile,
                        str(src),
                    ],
                    capture_output=True,
                    timeout=self._timeout_s,
                    check=False,
                )
            except subprocess.TimeoutExpired as e:
                raise MdflowError(
                    ErrorCode.TIMEOUT,
                    f"soffice timed out after {self._timeout_s}s",
                ) from e
            pdf_path = tmp_path / "input.pdf"
            if proc.returncode != 0 or not pdf_path.exists():
                stderr = proc.stderr.decode("utf-8", "replace").strip()
                raise MdflowError(
                    ErrorCode.CONVERSION_FAILED,
                    f"soffice failed (rc={proc.returncode}): {stderr[:500]}",
                )
            pdf_bytes = pdf_path.read_bytes()
        progress("convert", 50)
        pdf_ctx = ConversionContext(
            data=pdf_bytes,
            filename_hint="input.pdf",
            format="pdf",
            options=ctx.options,
            metadata={"format": "pdf"},
        )
        pdf_result = self._pdf.convert(pdf_ctx, lambda s, p: progress(s, 50 + p // 2))
        return ConversionResult(
            markdown=pdf_result.markdown,
            metadata={
                "source_format": ctx.format,
                "engine": "libreoffice+pymupdf4llm",
                "pages": pdf_result.metadata.get("pages"),
            },
        )
```

- [ ] **Step 4: Run the converter tests**

Run: `.venv/bin/pytest tests/converters/test_office.py -v`
Expected: all 4 pass on this host (soffice present). `test_protocol_attrs` always runs; the 3 `@requires_soffice` tests run here and skip on hosts without LibreOffice. Each soffice call takes ~1-2s; the onnxruntime stderr warning is harmless.

- [ ] **Step 5: Commit**

```bash
git add src/mdflow/converters/office.py tests/converters/test_office.py
git commit -m "feat(m3): LibreOfficeConverter (doc/ppt -> soffice PDF -> pymupdf4llm)"
```

---

## Task 3: Error-path unit tests (deterministic, no real soffice)

**Files:**
- Modify: `tests/converters/test_office.py`

These exercise the three error branches without depending on soffice behavior (see "Important findings" above — real soffice recovers garbage input, so failures are simulated by monkeypatching `subprocess.run`).

- [ ] **Step 1: Write the failing error tests**

Append to `tests/converters/test_office.py` (add `import subprocess` and `pytest` at the top of the file alongside the existing imports):

```python
import subprocess

import pytest

from mdflow.core.errors import ErrorCode, MdflowError
```

Then append the tests:

```python
def test_missing_soffice_raises_libreoffice_unavailable():
    conv = LibreOfficeConverter(timeout_s=120.0)
    conv._soffice = None  # simulate a host without LibreOffice
    with pytest.raises(MdflowError) as exc:
        conv.convert(_ctx(b"anything", "doc"), lambda s, p: None)
    assert exc.value.code is ErrorCode.LIBREOFFICE_UNAVAILABLE


def test_soffice_timeout_raises_timeout(monkeypatch):
    conv = LibreOfficeConverter(timeout_s=1.0)
    conv._soffice = "/usr/bin/soffice"  # pretend it exists; run() is patched

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="soffice", timeout=1.0)

    monkeypatch.setattr("mdflow.converters.office.subprocess.run", fake_run)
    with pytest.raises(MdflowError) as exc:
        conv.convert(_ctx(b"anything", "doc"), lambda s, p: None)
    assert exc.value.code is ErrorCode.TIMEOUT
    assert exc.value.retryable is True


def test_soffice_nonzero_exit_raises_conversion_failed(monkeypatch):
    conv = LibreOfficeConverter(timeout_s=120.0)
    conv._soffice = "/usr/bin/soffice"

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0], returncode=1, stdout=b"", stderr=b"boom"
        )

    monkeypatch.setattr("mdflow.converters.office.subprocess.run", fake_run)
    with pytest.raises(MdflowError) as exc:
        conv.convert(_ctx(b"anything", "doc"), lambda s, p: None)
    assert exc.value.code is ErrorCode.CONVERSION_FAILED


def test_soffice_missing_output_raises_conversion_failed(monkeypatch):
    conv = LibreOfficeConverter(timeout_s=120.0)
    conv._soffice = "/usr/bin/soffice"

    # returncode 0 but no input.pdf is ever written into the temp dir.
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0], returncode=0, stdout=b"", stderr=b""
        )

    monkeypatch.setattr("mdflow.converters.office.subprocess.run", fake_run)
    with pytest.raises(MdflowError) as exc:
        conv.convert(_ctx(b"anything", "doc"), lambda s, p: None)
    assert exc.value.code is ErrorCode.CONVERSION_FAILED
```

- [ ] **Step 2: Run to verify behavior**

Run: `.venv/bin/pytest tests/converters/test_office.py -v -k "missing_soffice or timeout or nonzero or missing_output"`
Expected: all 4 pass. They are deterministic and do not invoke real soffice (they patch `subprocess.run` or null out `_soffice`), so they pass on any host.

- [ ] **Step 3: Run the full office test file**

Run: `.venv/bin/pytest tests/converters/test_office.py -v`
Expected: 8 tests — 4 structural (3 soffice-gated) + 4 error. All pass on this host.

- [ ] **Step 4: Commit**

```bash
git add tests/converters/test_office.py
git commit -m "test(m3): deterministic error-path tests for LibreOfficeConverter"
```

---

## Task 4: Register converter + doc/ppt SSE integration

**Files:**
- Modify: `src/mdflow/api/app.py`
- Modify: `tests/api/test_convert.py`

- [ ] **Step 1: Write the failing integration tests**

Append to `tests/api/test_convert.py`. First add the marker import near the top (the file already imports `_run_convert`/`_parse_sse` locally and `assert_golden` from `tests.golden`):

```python
from tests.conftest import requires_soffice
```

Then append the tests (`_run_convert` already exists in this file):

```python
@requires_soffice
def test_convert_doc_streams_started_done(sample_doc_bytes):
    by_event, kinds = _run_convert("sample.doc", sample_doc_bytes, "application/msword")
    assert kinds[0] == "started" and kinds[-1] == "done"
    assert by_event["started"]["converter"] == "office-libreoffice"
    assert by_event["started"]["gpu"] is False
    assert "Document Title" in by_event["done"]["markdown"]


@requires_soffice
def test_convert_ppt_streams_started_done(sample_ppt_bytes):
    by_event, kinds = _run_convert(
        "sample.ppt", sample_ppt_bytes, "application/vnd.ms-powerpoint"
    )
    assert kinds[0] == "started" and kinds[-1] == "done"
    assert by_event["started"]["converter"] == "office-libreoffice"
    assert "First Slide" in by_event["done"]["markdown"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/api/test_convert.py -v -k "doc_streams or ppt_streams"`
Expected: FAIL — `doc`/`ppt` are detected by extension but no converter is registered, so the stream ends in `error`/`UNSUPPORTED_FORMAT`; the `started.converter == "office-libreoffice"` and `kinds[-1] == "done"` assertions fail.

- [ ] **Step 3: Register the converter in the lifespan**

In `src/mdflow/api/app.py`, add the import next to the other converter imports:
```python
from mdflow.converters.office import LibreOfficeConverter
```
Then in `_lifespan`, after `registry.register(PdfConverter())`, add:
```python
    registry.register(LibreOfficeConverter(timeout_s=settings.soffice_timeout_s))
```

- [ ] **Step 4: Run the integration tests**

Run: `.venv/bin/pytest tests/api/test_convert.py -v -k "doc_streams or ppt_streams"`
Expected: both pass on this host — `started` (converter `office-libreoffice`, gpu False) then `done` containing the expected text.

- [ ] **Step 5: Full suite + lint**

Run:
```bash
.venv/bin/pytest -q
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
```
Expected: all pass — report exact counts (baseline 240 + Task 0's 2 + Task 2's 4 + Task 3's 4 + this task's 2 ≈ 252 passed / 1 skipped on this host; on a host without soffice the 5 `@requires_soffice` tests skip instead). ruff clean. If `ruff format --check` fails, run `.venv/bin/ruff format src tests` and re-stage.

- [ ] **Step 6: Commit**

```bash
git add src/mdflow/api/app.py tests/api/test_convert.py
git commit -m "feat(m3): register LibreOfficeConverter + doc/ppt SSE integration"
```

---

## Task 5: State update + Codex milestone review (non-code wrap-up)

**Files:**
- Modify: `PROCESS_STATE.md`

- [ ] **Step 1: Update `PROCESS_STATE.md`**

Update §2 "한눈에 보기" and §9 (M3): mark M3a done (LibreOffice doc/ppt converter via soffice→PDF→pymupdf4llm composition). Record the new test/lint baseline (run `.venv/bin/pytest` and copy the passed/skipped counts; note that 5 tests are `@requires_soffice` and skip on hosts without LibreOffice). Note hwp remains M3b. Set next action to "M3a Codex 묶음 리뷰".

- [ ] **Step 2: Commit the state update**

```bash
git add PROCESS_STATE.md
git commit -m "docs(state): M3a LibreOffice doc/ppt converter implemented"
```

- [ ] **Step 3: Codex milestone bundle review**

Per CLAUDE.md §3 + milestone cadence, send the full M3a diff (`git diff 8b03dd9 HEAD`) for independent review via the `codex-peer-reviewer` skill. Focus the reviewer on: (a) the §6 error contract — soffice failures are signaled via explicit returncode checks (not swallowed), and missing-soffice/timeout/nonzero map to the right codes (`LIBREOFFICE_UNAVAILABLE`/`TIMEOUT`/`CONVERSION_FAILED`); (b) subprocess safety — argv list (no shell), per-call `UserInstallation` profile for concurrency, `TemporaryDirectory` cleanup on every path including exceptions; (c) the progress remap stays monotonic and the PDF-stage composition doesn't double-handle errors. Save to `docs/reviews/2026-05-22-m3a-libreoffice-codex.md`. Address blocking findings, then mark M3a adopted.

---

## Self-Review (completed by plan author)

**Spec coverage** (design §§1-9):
- §1.2 `office-libreoffice` converter (doc/ppt, requires_gpu=False) → Task 2. ✓
- §1.2 soffice→PDF→PdfConverter composition (approach A) → Task 2 Step 3. ✓
- §1.2 `MDFLOW_SOFFICE_TIMEOUT_S` setting → Task 0. ✓
- §3 converter behavior (which soffice cache, can_handle always-true, temp dir + per-call profile, returncode/missing-output checks, progress remap 50+p//2, metadata source_format/engine/pages, TimeoutExpired→TIMEOUT) → Task 2 Step 3. ✓
- §4 can_handle not gated on soffice (LIBREOFFICE_UNAVAILABLE raised in convert) → Task 2 (impl) + Task 3 (test). ✓
- §5 error mapping table (LIBREOFFICE_UNAVAILABLE / TIMEOUT / CONVERSION_FAILED) → Task 3 deterministic tests. ✓ (Refinement: corrupted-doc moved from real-soffice integration to monkeypatched unit tests because soffice recovers garbage input — documented in "Important findings".)
- §6 no new Python dep; system soffice + core pymupdf4llm → no pyproject change; verified. ✓
- §7 tests: skipif marker, build-time soffice fixtures, structural assertions (not exact golden), error paths, SSE integration → Tasks 1-4. ✓
- §8 Task table 0-5 → Tasks 0-5. ✓

**Placeholder scan:** No TBD/TODO/"handle edge cases". Every code step shows complete code; every test step shows assertions and exact run commands with expected outcomes (de-risked by running the real soffice pipeline during planning).

**Type consistency:** `LibreOfficeConverter` attributes match the `Converter` Protocol (`name`/`formats`/`requires_gpu`/`can_handle`/`convert`). `__init__(timeout_s, pdf=None)` matches the lifespan call `LibreOfficeConverter(timeout_s=settings.soffice_timeout_s)` (Task 4) and the test constructions `LibreOfficeConverter(timeout_s=120.0)` (Tasks 2-3). The monkeypatch target `mdflow.converters.office.subprocess.run` matches the `import subprocess` in `office.py`. `ConversionContext(data, filename_hint, format, options, metadata)` matches `base.py`. `_run_convert`/`_parse_sse` reused from existing `tests/api/test_convert.py`; `requires_soffice` defined in Task 1 and imported in Tasks 2/4. `pdf_result.metadata.get("pages")` matches `PdfConverter`'s `metadata={"pages": ..., "engine": ...}`.

**Known refinement flagged in-plan:** design §7's "corrupted doc (integration)" is implemented as deterministic monkeypatched unit tests (Task 3) because real soffice recovers arbitrary bytes into a valid PDF; the architecture and error codes are unchanged.
