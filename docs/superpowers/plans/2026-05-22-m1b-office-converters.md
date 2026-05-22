# M1b — Office Format Converters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four office-document converters (docx, pptx, xlsx, html) on top of the existing `/convert` SSE path, with golden-output regression tests.

**Architecture:** Each converter implements the existing `Converter` Protocol (`name`/`formats`/`requires_gpu`/`can_handle`/`convert`), calls a synchronous parsing library, and returns a `ConversionResult`. docx + html-fallback share a `_html_to_md` (markdownify) helper. Converters carry **no** internal try/except — library exceptions propagate and `ConversionService.run_conversion` wraps them as `CONVERSION_FAILED` (M1a contract). Format detection already recognizes all four formats (M0); we only register the converters.

**Tech Stack:** Python 3.11, mammoth (docx→HTML), markdownify + beautifulsoup4 (HTML→MD), python-pptx, openpyxl, trafilatura (HTML body extraction). Test golden files compared as normalized whole-file strings, regenerated via `MDFLOW_UPDATE_GOLDEN=1`.

---

## File Structure

**Source (new):**
- `src/mdflow/converters/_html_to_md.py` — `html_to_markdown(html, *, strip_images=False)` shared markdownify wrapper. Single responsibility: HTML string → Markdown string.
- `src/mdflow/converters/docx.py` — `DocxConverter` (`name="docx-mammoth"`, `formats=("docx",)`).
- `src/mdflow/converters/pptx.py` — `PptxConverter` (`name="pptx-python-pptx"`, `formats=("pptx",)`).
- `src/mdflow/converters/spreadsheet.py` — `XlsxConverter` (`name="xlsx-openpyxl"`, `formats=("xlsx",)`).
- `src/mdflow/converters/html.py` — `HtmlConverter` (`name="html-trafilatura"`, `formats=("html",)`).

**Source (modified):**
- `src/mdflow/api/app.py:56-57` — register the four converters in `_lifespan` after `TextConverter`.
- `pyproject.toml:12-21` — add 7 runtime dependencies.

**Tests (new):**
- `tests/golden.py` — `assert_golden(actual, golden_name)` helper + `normalize`. Plain importable module (not a test file), usable from both `tests/converters/` and `tests/api/`.
- `tests/converters/test_html_to_md.py`, `test_docx.py`, `test_pptx.py`, `test_spreadsheet.py`, `test_html.py`.
- `tests/golden/{docx,pptx,xlsx,html}/sample.md` — committed golden outputs.

**Tests (modified):**
- `tests/conftest.py` — add `sample_docx_bytes`, `sample_pptx_bytes`, `sample_xlsx_bytes`, `sample_html` fixtures (visible to all test packages).
- `tests/api/test_convert.py` — add 4 per-format SSE integration tests.

---

## Golden-test workflow (read before starting any converter task)

Pure TDD can't hand-author a 30-line Markdown golden. So each converter task uses a **hybrid**:

1. Write **structural assertions** (specific substrings that must appear/not appear). These give genuine fail-first behavior because the converter module doesn't exist yet.
2. Add a **golden assertion** `assert_golden(out.markdown, "<fmt>/sample.md")`.
3. After implementing, run **once** with `MDFLOW_UPDATE_GOLDEN=1` to generate the golden file, then **Read the generated file and verify** it matches the design's expected shape (headings, bullets, tables, notes). Fix the converter if the golden looks wrong, regenerate.
4. Run again **without** the env var — golden is now locked as regression.
5. Commit converter + golden together.

`assert_golden` normalizes trailing whitespace and final newlines before comparing, and emits a unified diff on mismatch.

---

## Task 0: Add dependencies

**Files:**
- Modify: `pyproject.toml:12-21`

- [ ] **Step 1: Add the 7 runtime dependencies**

Edit the `dependencies = [...]` list in `pyproject.toml` (the `[project]` table, currently lines 12-21) to append these entries after `"python-multipart>=0.0.9",`:

```toml
    "mammoth>=1.6",
    "python-docx>=1.1",
    "python-pptx>=0.6.23",
    "openpyxl>=3.1",
    "trafilatura>=1.8",
    "markdownify>=0.11",
    "beautifulsoup4>=4.12",
```

- [ ] **Step 2: Install into the project venv**

Run: `.venv/bin/pip install -e ".[dev]"`
Expected: installs mammoth, python-docx, python-pptx, openpyxl, trafilatura, markdownify, beautifulsoup4 (plus transitive deps like lxml). Ends with "Successfully installed ...".

- [ ] **Step 3: Verify all imports resolve**

Run:
```bash
.venv/bin/python -c "import mammoth, docx, pptx, openpyxl, trafilatura, markdownify, bs4; print('ok')"
```
Expected: prints `ok` with no ImportError.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "build(m1b): add office-converter runtime dependencies"
```

---

## Task 1: Golden harness + input fixtures

**Files:**
- Create: `tests/golden.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Write `tests/golden.py`**

```python
"""Whole-file golden comparison for converter outputs.

Plain module (not collected as a test) so both tests/converters/ and
tests/api/ can import it. Set MDFLOW_UPDATE_GOLDEN=1 to (re)write goldens.
"""

from __future__ import annotations

import difflib
import os
from pathlib import Path

GOLDEN_ROOT = Path(__file__).parent / "golden"


def normalize(text: str) -> str:
    """Strip trailing whitespace per line and collapse the file to a
    single trailing newline, so insignificant whitespace never trips
    the exact comparison."""
    body = "\n".join(line.rstrip() for line in text.splitlines())
    return body.rstrip("\n") + "\n"


def assert_golden(actual: str, golden_name: str) -> None:
    """Compare `actual` against tests/golden/<golden_name>.

    With MDFLOW_UPDATE_GOLDEN set, write the normalized actual and pass.
    Otherwise read the golden and assert exact (normalized) equality,
    raising a unified diff on mismatch.
    """
    path = GOLDEN_ROOT / golden_name
    norm = normalize(actual)
    if os.environ.get("MDFLOW_UPDATE_GOLDEN"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(norm, encoding="utf-8")
        return
    if not path.exists():
        raise AssertionError(
            f"golden missing: {path} (run with MDFLOW_UPDATE_GOLDEN=1 to create)"
        )
    expected = path.read_text(encoding="utf-8")
    if norm != expected:
        diff = "".join(
            difflib.unified_diff(
                expected.splitlines(keepends=True),
                norm.splitlines(keepends=True),
                fromfile=str(path),
                tofile="actual",
            )
        )
        raise AssertionError(f"golden mismatch for {golden_name}:\n{diff}")
```

- [ ] **Step 2: Add input fixtures to `tests/conftest.py`**

Append to `tests/conftest.py` (keep existing fixtures). These build deterministic *converted output* — input byte layout (timestamps etc.) does not matter because we compare Markdown, not bytes.

```python
import io


@pytest.fixture
def sample_docx_bytes() -> bytes:
    from docx import Document

    doc = Document()
    doc.add_heading("Document Title", level=1)
    doc.add_heading("Section", level=2)
    p = doc.add_paragraph("Normal text with ")
    p.add_run("bold").bold = True
    p.add_run(" tail.")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "H1"
    table.cell(0, 1).text = "H2"
    table.cell(1, 0).text = "a"
    table.cell(1, 1).text = "b"
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


@pytest.fixture
def sample_pptx_bytes() -> bytes:
    from pptx import Presentation

    prs = Presentation()
    layout = prs.slide_layouts[1]  # Title and Content

    s1 = prs.slides.add_slide(layout)
    s1.shapes.title.text = "First Slide"
    body = s1.placeholders[1].text_frame
    body.text = "Bullet one"
    sub = body.add_paragraph()
    sub.text = "Sub bullet"
    sub.level = 1
    two = body.add_paragraph()
    two.text = "Bullet two"
    s1.notes_slide.notes_text_frame.text = "Presenter note here"

    s2 = prs.slides.add_slide(layout)
    s2.shapes.title.text = "Second Slide"
    s2.placeholders[1].text_frame.text = "Only bullet"

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


@pytest.fixture
def sample_xlsx_bytes() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws1 = wb.active
    ws1.title = "Sheet1"
    ws1.append(["name", "score"])
    ws1.append(["alice", 1])
    ws1.append(["bob", 2])
    ws2 = wb.create_sheet("Second")
    ws2.append(["x", "y"])
    ws2.append([10, 20])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def sample_html() -> str:
    return (
        "<!doctype html><html><head><title>T</title></head>\n"
        "<body>\n"
        "<nav>Home About Contact</nav>\n"
        "<article>\n"
        "<h1>Main Heading</h1>\n"
        "<p>First paragraph of the article body with enough text to be detected "
        "as the main content by trafilatura, which needs a reasonable amount of "
        "words before it will treat a block as the article body.</p>\n"
        "<h2>Subsection</h2>\n"
        "<ul><li>Item one</li><li>Item two</li></ul>\n"
        "<table><tr><th>Col A</th><th>Col B</th></tr>"
        "<tr><td>1</td><td>2</td></tr></table>\n"
        "</article>\n"
        "<footer>Copyright 2026</footer>\n"
        "</body></html>"
    )
```

- [ ] **Step 3: Verify fixtures import and produce bytes**

Run:
```bash
.venv/bin/python -c "
import io
from docx import Document
from pptx import Presentation
from openpyxl import Workbook
print('fixtures deps ok')
"
```
Expected: prints `fixtures deps ok`.

- [ ] **Step 4: Verify the test suite still collects and passes**

Run: `.venv/bin/pytest -q`
Expected: same as M1a baseline (191 passed, 1 skipped) — no new tests yet, no collection errors from the new conftest fixtures.

- [ ] **Step 5: Commit**

```bash
git add tests/golden.py tests/conftest.py
git commit -m "test(m1b): add golden harness and office input fixtures"
```

---

## Task 2: `_html_to_md` helper + docx converter

**Files:**
- Create: `src/mdflow/converters/_html_to_md.py`
- Create: `src/mdflow/converters/docx.py`
- Create: `tests/converters/test_html_to_md.py`
- Create: `tests/converters/test_docx.py`
- Create (generated): `tests/golden/docx/sample.md`

- [ ] **Step 1: Write the failing `_html_to_md` test**

`tests/converters/test_html_to_md.py`:

```python
from mdflow.converters._html_to_md import html_to_markdown


def test_headings_use_atx_style():
    md = html_to_markdown("<h1>Title</h1><h2>Sub</h2>")
    assert "# Title" in md
    assert "## Sub" in md


def test_bold_and_lists():
    md = html_to_markdown("<p>a <strong>b</strong></p><ul><li>x</li></ul>")
    assert "**b**" in md
    assert "- x" in md or "* x" in md


def test_strip_images_drops_img_tags():
    md = html_to_markdown('<p>t</p><img src="x.png" alt="cat">', strip_images=True)
    assert "![" not in md
    assert "x.png" not in md


def test_keep_images_preserves_alt_by_default():
    md = html_to_markdown('<img src="x.png" alt="cat">')
    assert "cat" in md
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/converters/test_html_to_md.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mdflow.converters._html_to_md'`.

- [ ] **Step 3: Implement `_html_to_md.py`**

```python
"""Shared HTML -> Markdown conversion (markdownify).

Single responsibility: HTML string -> Markdown string. Used by the docx
converter (after mammoth) and the html converter's fallback path. Heading
style is ATX (`#`). Images are kept by default (alt text preserved,
best-effort); docx passes strip_images=True to drop them entirely.
"""

from __future__ import annotations

from markdownify import markdownify


def html_to_markdown(html: str, *, strip_images: bool = False) -> str:
    options: dict = {"heading_style": "ATX"}
    if strip_images:
        options["strip"] = ["img"]
    return markdownify(html, **options).strip()
```

- [ ] **Step 4: Run the helper test to verify it passes**

Run: `.venv/bin/pytest tests/converters/test_html_to_md.py -v`
Expected: 4 passed.

- [ ] **Step 5: Write the failing docx converter test**

`tests/converters/test_docx.py`:

```python
from mdflow.converters.base import ConversionContext
from mdflow.converters.docx import DocxConverter
from tests.golden import assert_golden


def _ctx(data: bytes) -> ConversionContext:
    return ConversionContext(data=data, filename_hint="sample.docx", format="docx")


def test_protocol_attrs():
    conv = DocxConverter()
    assert conv.name == "docx-mammoth"
    assert conv.formats == ("docx",)
    assert conv.requires_gpu is False
    assert conv.can_handle(_ctx(b"")) is True
    assert conv.can_handle(ConversionContext(data=b"", filename_hint=None, format="pdf")) is False


def test_docx_structure(sample_docx_bytes):
    out = DocxConverter().convert(_ctx(sample_docx_bytes), lambda s, p: None)
    assert "# Document Title" in out.markdown
    assert "## Section" in out.markdown
    assert "**bold**" in out.markdown


def test_docx_progress_ends_done(sample_docx_bytes):
    seen: list[tuple[str, int]] = []
    DocxConverter().convert(_ctx(sample_docx_bytes), lambda s, p: seen.append((s, p)))
    assert seen[-1] == ("done", 100)


def test_docx_golden(sample_docx_bytes):
    out = DocxConverter().convert(_ctx(sample_docx_bytes), lambda s, p: None)
    assert_golden(out.markdown, "docx/sample.md")
```

- [ ] **Step 6: Run to verify it fails**

Run: `.venv/bin/pytest tests/converters/test_docx.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mdflow.converters.docx'`.

- [ ] **Step 7: Implement `docx.py`**

```python
"""docx -> Markdown via mammoth (semantic HTML) + markdownify.

mammoth maps Word styles to semantic HTML (headings, lists, tables,
bold/italic). Images are dropped: the image handler returns no attributes
so no base64 data URI is emitted, and markdownify strips any residual
<img>. No internal try/except — library errors propagate to
ConversionService.run_conversion (wrapped as CONVERSION_FAILED).
"""

from __future__ import annotations

import io

import mammoth

from mdflow.converters._html_to_md import html_to_markdown
from mdflow.converters.base import (
    ConversionContext,
    ConversionResult,
    ProgressCallback,
)


class DocxConverter:
    name = "docx-mammoth"
    formats: tuple[str, ...] = ("docx",)
    requires_gpu = False

    def can_handle(self, ctx: ConversionContext) -> bool:
        return ctx.format in self.formats

    def convert(self, ctx: ConversionContext, progress: ProgressCallback) -> ConversionResult:
        progress("parse", 10)
        result = mammoth.convert_to_html(
            io.BytesIO(ctx.data),
            convert_image=mammoth.images.img_element(lambda image: {}),
        )
        progress("render", 60)
        markdown = html_to_markdown(result.value, strip_images=True)
        metadata: dict = {}
        warnings = [m.message for m in result.messages]
        if warnings:
            metadata["warnings"] = warnings
        progress("done", 100)
        return ConversionResult(markdown=markdown, metadata=metadata)
```

- [ ] **Step 8: Run non-golden docx tests to verify they pass**

Run: `.venv/bin/pytest tests/converters/test_docx.py -v -k "not golden"`
Expected: `test_protocol_attrs`, `test_docx_structure`, `test_docx_progress_ends_done` pass.

- [ ] **Step 9: Generate and review the docx golden**

Run: `MDFLOW_UPDATE_GOLDEN=1 .venv/bin/pytest tests/converters/test_docx.py::test_docx_golden -v`
Then **Read `tests/golden/docx/sample.md`** and confirm it contains: `# Document Title`, `## Section`, a paragraph with `**bold**`, and a 2x2 Markdown table (`| H1 | H2 |` header). If anything is malformed (e.g. stray `![]()` image artifacts, missing table), fix `docx.py` and regenerate before proceeding.

- [ ] **Step 10: Run the full docx test file (compare mode) to verify it passes**

Run: `.venv/bin/pytest tests/converters/test_docx.py tests/converters/test_html_to_md.py -v`
Expected: all pass, including `test_docx_golden`.

- [ ] **Step 11: Commit**

```bash
git add src/mdflow/converters/_html_to_md.py src/mdflow/converters/docx.py \
        tests/converters/test_html_to_md.py tests/converters/test_docx.py \
        tests/golden/docx/sample.md
git commit -m "feat(m1b): docx converter (mammoth) + shared html_to_md helper"
```

---

## Task 3: pptx converter

**Files:**
- Create: `src/mdflow/converters/pptx.py`
- Create: `tests/converters/test_pptx.py`
- Create (generated): `tests/golden/pptx/sample.md`

- [ ] **Step 1: Write the failing pptx test**

`tests/converters/test_pptx.py`:

```python
from mdflow.converters.base import ConversionContext
from mdflow.converters.pptx import PptxConverter
from tests.golden import assert_golden


def _ctx(data: bytes) -> ConversionContext:
    return ConversionContext(data=data, filename_hint="sample.pptx", format="pptx")


def test_protocol_attrs():
    conv = PptxConverter()
    assert conv.name == "pptx-python-pptx"
    assert conv.formats == ("pptx",)
    assert conv.requires_gpu is False
    assert conv.can_handle(_ctx(b"")) is True


def test_pptx_structure(sample_pptx_bytes):
    out = PptxConverter().convert(_ctx(sample_pptx_bytes), lambda s, p: None)
    md = out.markdown
    assert "## First Slide" in md
    assert "- Bullet one" in md
    assert "  - Sub bullet" in md  # level 1 -> 2-space indent
    assert "## Second Slide" in md
    assert "> Notes:" in md
    assert "Presenter note here" in md


def test_pptx_progress_ends_done(sample_pptx_bytes):
    seen: list[tuple[str, int]] = []
    PptxConverter().convert(_ctx(sample_pptx_bytes), lambda s, p: seen.append((s, p)))
    assert seen[-1] == ("done", 100)


def test_pptx_golden(sample_pptx_bytes):
    out = PptxConverter().convert(_ctx(sample_pptx_bytes), lambda s, p: None)
    assert_golden(out.markdown, "pptx/sample.md")
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/converters/test_pptx.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mdflow.converters.pptx'`.

- [ ] **Step 3: Implement `pptx.py`**

```python
"""pptx -> Markdown via python-pptx.

Per slide: title as `## <title>` (or `## Slide N`), body text-frame
paragraphs as a bullet list (2-space indent per paragraph.level), tables
as Markdown tables, and presenter notes as a `> Notes:` blockquote. Shapes
with no text/table (images, graphics) are dropped. No internal try/except.
"""

from __future__ import annotations

import io

from pptx import Presentation

from mdflow.converters.base import (
    ConversionContext,
    ConversionResult,
    ProgressCallback,
)


class PptxConverter:
    name = "pptx-python-pptx"
    formats: tuple[str, ...] = ("pptx",)
    requires_gpu = False

    def can_handle(self, ctx: ConversionContext) -> bool:
        return ctx.format in self.formats

    def convert(self, ctx: ConversionContext, progress: ProgressCallback) -> ConversionResult:
        progress("parse", 10)
        prs = Presentation(io.BytesIO(ctx.data))
        slides = list(prs.slides)
        total = max(len(slides), 1)
        blocks: list[str] = []
        for i, slide in enumerate(slides, start=1):
            blocks.append(_render_slide(slide, i))
            progress("render", 10 + int(80 * i / total))
        markdown = "\n\n".join(blocks).strip()
        progress("done", 100)
        return ConversionResult(markdown=markdown, metadata={"slides": len(slides)})


def _render_slide(slide, index: int) -> str:
    title_shape = slide.shapes.title
    title = title_shape.text.strip() if title_shape is not None else ""
    parts: list[str] = [f"## {title}" if title else f"## Slide {index}"]

    for shape in slide.shapes:
        if shape is title_shape:
            continue
        if shape.has_table:
            parts.append(_table_to_md(shape.table))
        elif shape.has_text_frame:
            bullets = _bullets(shape.text_frame)
            if bullets:
                parts.append(bullets)

    if slide.has_notes_slide:
        notes = slide.notes_slide.notes_text_frame.text.strip()
        if notes:
            quoted = "\n".join(f"> {line}" for line in notes.splitlines())
            parts.append(f"> Notes:\n{quoted}")

    return "\n\n".join(parts)


def _bullets(text_frame) -> str:
    lines: list[str] = []
    for para in text_frame.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        indent = "  " * (para.level or 0)
        lines.append(f"{indent}- {text}")
    return "\n".join(lines)


def _table_to_md(table) -> str:
    rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
    if not rows:
        return ""
    header, *body = rows
    out = ["| " + " | ".join(header) + " |"]
    out.append("| " + " | ".join("---" for _ in header) + " |")
    for row in body:
        out.append("| " + " | ".join(row) + " |")
    return "\n".join(out)
```

- [ ] **Step 4: Run non-golden pptx tests to verify they pass**

Run: `.venv/bin/pytest tests/converters/test_pptx.py -v -k "not golden"`
Expected: `test_protocol_attrs`, `test_pptx_structure`, `test_pptx_progress_ends_done` pass.

- [ ] **Step 5: Generate and review the pptx golden**

Run: `MDFLOW_UPDATE_GOLDEN=1 .venv/bin/pytest tests/converters/test_pptx.py::test_pptx_golden -v`
Then **Read `tests/golden/pptx/sample.md`** and confirm: `## First Slide`, `- Bullet one`, `  - Sub bullet`, `- Bullet two`, a `> Notes:` block with `> Presenter note here`, then `## Second Slide` with `- Only bullet` and no notes block. Fix `pptx.py` and regenerate if wrong.

- [ ] **Step 6: Run the full pptx test file (compare mode) to verify it passes**

Run: `.venv/bin/pytest tests/converters/test_pptx.py -v`
Expected: all 4 pass.

- [ ] **Step 7: Commit**

```bash
git add src/mdflow/converters/pptx.py tests/converters/test_pptx.py tests/golden/pptx/sample.md
git commit -m "feat(m1b): pptx converter (python-pptx) with bullets, tables, notes"
```

---

## Task 4: xlsx converter

**Files:**
- Create: `src/mdflow/converters/spreadsheet.py`
- Create: `tests/converters/test_spreadsheet.py`
- Create (generated): `tests/golden/xlsx/sample.md`

- [ ] **Step 1: Write the failing xlsx test**

`tests/converters/test_spreadsheet.py`:

```python
from mdflow.converters.base import ConversionContext
from mdflow.converters.spreadsheet import XlsxConverter
from tests.golden import assert_golden


def _ctx(data: bytes) -> ConversionContext:
    return ConversionContext(data=data, filename_hint="sample.xlsx", format="xlsx")


def test_protocol_attrs():
    conv = XlsxConverter()
    assert conv.name == "xlsx-openpyxl"
    assert conv.formats == ("xlsx",)
    assert conv.requires_gpu is False
    assert conv.can_handle(_ctx(b"")) is True


def test_xlsx_structure(sample_xlsx_bytes):
    out = XlsxConverter().convert(_ctx(sample_xlsx_bytes), lambda s, p: None)
    md = out.markdown
    assert "## Sheet1" in md
    assert "| name | score |" in md
    assert "| alice | 1 |" in md
    assert "## Second" in md
    assert "| x | y |" in md
    assert out.metadata["formula_values"] == "cached"


def test_xlsx_progress_ends_done(sample_xlsx_bytes):
    seen: list[tuple[str, int]] = []
    XlsxConverter().convert(_ctx(sample_xlsx_bytes), lambda s, p: seen.append((s, p)))
    assert seen[-1] == ("done", 100)


def test_xlsx_golden(sample_xlsx_bytes):
    out = XlsxConverter().convert(_ctx(sample_xlsx_bytes), lambda s, p: None)
    assert_golden(out.markdown, "xlsx/sample.md")
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/converters/test_spreadsheet.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mdflow.converters.spreadsheet'`.

- [ ] **Step 3: Implement `spreadsheet.py`**

```python
"""xlsx -> Markdown via openpyxl.

Loaded read_only + data_only (memory-safe; formula cells yield their last
cached value). Each sheet renders as `## <SheetName>` plus a Markdown
table over the used range, first row as header. Empty sheets render the
heading plus `(empty sheet)`. No internal try/except.
"""

from __future__ import annotations

import io

from openpyxl import load_workbook

from mdflow.converters.base import (
    ConversionContext,
    ConversionResult,
    ProgressCallback,
)


class XlsxConverter:
    name = "xlsx-openpyxl"
    formats: tuple[str, ...] = ("xlsx",)
    requires_gpu = False

    def can_handle(self, ctx: ConversionContext) -> bool:
        return ctx.format in self.formats

    def convert(self, ctx: ConversionContext, progress: ProgressCallback) -> ConversionResult:
        progress("parse", 10)
        wb = load_workbook(io.BytesIO(ctx.data), data_only=True, read_only=True)
        try:
            names = wb.sheetnames
            total = max(len(names), 1)
            blocks: list[str] = []
            for i, name in enumerate(names, start=1):
                blocks.append(_sheet_to_md(name, wb[name]))
                progress("render", 10 + int(80 * i / total))
        finally:
            wb.close()
        markdown = "\n\n".join(blocks).strip()
        progress("done", 100)
        return ConversionResult(markdown=markdown, metadata={"formula_values": "cached"})


def _cell(value) -> str:
    return "" if value is None else str(value)


def _sheet_to_md(name: str, ws) -> str:
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    while rows and all(c is None for c in rows[-1]):
        rows.pop()
    if not rows:
        return f"## {name}\n\n(empty sheet)"

    width = max(len(r) for r in rows)
    norm = [[_cell(v) for v in r] + [""] * (width - len(r)) for r in rows]
    header, *body = norm
    table = ["| " + " | ".join(header) + " |"]
    table.append("| " + " | ".join("---" for _ in header) + " |")
    for r in body:
        table.append("| " + " | ".join(r) + " |")
    return f"## {name}\n\n" + "\n".join(table)
```

- [ ] **Step 4: Run non-golden xlsx tests to verify they pass**

Run: `.venv/bin/pytest tests/converters/test_spreadsheet.py -v -k "not golden"`
Expected: `test_protocol_attrs`, `test_xlsx_structure`, `test_xlsx_progress_ends_done` pass.

- [ ] **Step 5: Generate and review the xlsx golden**

Run: `MDFLOW_UPDATE_GOLDEN=1 .venv/bin/pytest tests/converters/test_spreadsheet.py::test_xlsx_golden -v`
Then **Read `tests/golden/xlsx/sample.md`** and confirm: `## Sheet1` with header `| name | score |`, rows `| alice | 1 |` and `| bob | 2 |`, then `## Second` with `| x | y |` and `| 10 | 20 |`. Fix and regenerate if wrong.

- [ ] **Step 6: Run the full xlsx test file (compare mode) to verify it passes**

Run: `.venv/bin/pytest tests/converters/test_spreadsheet.py -v`
Expected: all 4 pass.

- [ ] **Step 7: Commit**

```bash
git add src/mdflow/converters/spreadsheet.py tests/converters/test_spreadsheet.py tests/golden/xlsx/sample.md
git commit -m "feat(m1b): xlsx converter (openpyxl) with per-sheet tables"
```

---

## Task 5: html converter (+ fallback)

**Files:**
- Create: `src/mdflow/converters/html.py`
- Create: `tests/converters/test_html.py`
- Create (generated): `tests/golden/html/sample.md`

- [ ] **Step 1: Write the failing html test**

`tests/converters/test_html.py`:

```python
from mdflow.converters.base import ConversionContext
from mdflow.converters.html import HtmlConverter
from tests.golden import assert_golden


def _ctx(html: str) -> ConversionContext:
    return ConversionContext(
        data=html.encode("utf-8"), filename_hint="sample.html", format="html"
    )


def test_protocol_attrs():
    conv = HtmlConverter()
    assert conv.name == "html-trafilatura"
    assert conv.formats == ("html",)
    assert conv.requires_gpu is False
    assert conv.can_handle(_ctx("")) is True


def test_html_extracts_body_and_drops_boilerplate(sample_html):
    out = HtmlConverter().convert(_ctx(sample_html), lambda s, p: None)
    md = out.markdown
    assert "Main Heading" in md
    assert "Item one" in md
    assert "Home About Contact" not in md  # nav boilerplate removed
    assert "Copyright 2026" not in md  # footer boilerplate removed
    assert out.metadata["extractor"] == "trafilatura"


def test_html_fallback_when_no_article(sample_html):
    # A bare fragment with no article-like body: trafilatura returns None,
    # so the markdownify fallback runs.
    out = HtmlConverter().convert(_ctx("<div><p>hi</p></div>"), lambda s, p: None)
    assert "hi" in out.markdown
    assert out.metadata["extractor"] == "markdownify-fallback"


def test_html_progress_ends_done(sample_html):
    seen: list[tuple[str, int]] = []
    HtmlConverter().convert(_ctx(sample_html), lambda s, p: seen.append((s, p)))
    assert seen[-1] == ("done", 100)


def test_html_golden(sample_html):
    out = HtmlConverter().convert(_ctx(sample_html), lambda s, p: None)
    assert_golden(out.markdown, "html/sample.md")
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/converters/test_html.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mdflow.converters.html'`.

- [ ] **Step 3: Implement `html.py`**

```python
"""html -> Markdown via trafilatura (boilerplate removal), with a
markdownify fallback when no article body is detected.

trafilatura.extract removes nav/footer/ad boilerplate and emits Markdown.
When it returns None (no article-like content), fall back to parsing the
<body> (or whole doc) with BeautifulSoup and converting via the shared
html_to_markdown helper. Images are excluded from the trafilatura path.
Input bytes are decoded with the TextConverter decode logic. No internal
try/except.
"""

from __future__ import annotations

import trafilatura
from bs4 import BeautifulSoup

from mdflow.converters._html_to_md import html_to_markdown
from mdflow.converters.base import (
    ConversionContext,
    ConversionResult,
    ProgressCallback,
)
from mdflow.converters.text import _decode


class HtmlConverter:
    name = "html-trafilatura"
    formats: tuple[str, ...] = ("html",)
    requires_gpu = False

    def can_handle(self, ctx: ConversionContext) -> bool:
        return ctx.format in self.formats

    def convert(self, ctx: ConversionContext, progress: ProgressCallback) -> ConversionResult:
        progress("parse", 10)
        html_str, _ = _decode(ctx.data)
        extracted = trafilatura.extract(
            html_str,
            output_format="markdown",
            include_tables=True,
            include_images=False,
        )
        progress("render", 60)
        if extracted:
            markdown = extracted.strip()
            extractor = "trafilatura"
        else:
            soup = BeautifulSoup(html_str, "html.parser")
            root = soup.body or soup
            markdown = html_to_markdown(str(root))
            extractor = "markdownify-fallback"
        progress("done", 100)
        return ConversionResult(markdown=markdown, metadata={"extractor": extractor})
```

- [ ] **Step 4: Run non-golden html tests to verify they pass**

Run: `.venv/bin/pytest tests/converters/test_html.py -v -k "not golden"`
Expected: the 4 non-golden tests pass. If `test_html_extracts_body_and_drops_boilerplate` fails because trafilatura did not detect the article, lengthen the `<p>` text in the `sample_html` fixture (Task 1) until extraction succeeds, then re-run.

- [ ] **Step 5: Generate and review the html golden**

Run: `MDFLOW_UPDATE_GOLDEN=1 .venv/bin/pytest tests/converters/test_html.py::test_html_golden -v`
Then **Read `tests/golden/html/sample.md`** and confirm it contains the heading `Main Heading`, the subsection, the `Item one`/`Item two` list, and the Col A/Col B table, with **no** `Home About Contact` nav or `Copyright 2026` footer. Fix and regenerate if wrong.

- [ ] **Step 6: Run the full html test file (compare mode) to verify it passes**

Run: `.venv/bin/pytest tests/converters/test_html.py -v`
Expected: all 5 pass.

- [ ] **Step 7: Commit**

```bash
git add src/mdflow/converters/html.py tests/converters/test_html.py tests/golden/html/sample.md
git commit -m "feat(m1b): html converter (trafilatura + markdownify fallback)"
```

---

## Task 6: Register converters + per-format SSE integration tests

**Files:**
- Modify: `src/mdflow/api/app.py:22` (imports) and `:56-57` (registration)
- Modify: `tests/api/test_convert.py`

- [ ] **Step 1: Write the failing integration tests**

Append to `tests/api/test_convert.py` (the file already defines `_parse_sse`):

```python
from tests.golden import assert_golden


def _run_convert(filename: str, data: bytes, mime: str):
    app = create_app()
    with TestClient(app) as client:
        r = client.post("/convert", files={"file": (filename, data, mime)})
    assert r.status_code == 200
    events = _parse_sse(r.text)
    return dict(events), [e[0] for e in events]


def test_convert_docx_streams_started_done(sample_docx_bytes):
    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    by_event, kinds = _run_convert("sample.docx", sample_docx_bytes, mime)
    assert kinds[0] == "started" and kinds[-1] == "done"
    assert by_event["started"]["converter"] == "docx-mammoth"
    assert_golden(by_event["done"]["markdown"], "docx/sample.md")


def test_convert_pptx_streams_started_done(sample_pptx_bytes):
    mime = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    by_event, kinds = _run_convert("sample.pptx", sample_pptx_bytes, mime)
    assert kinds[0] == "started" and kinds[-1] == "done"
    assert by_event["started"]["converter"] == "pptx-python-pptx"
    assert_golden(by_event["done"]["markdown"], "pptx/sample.md")


def test_convert_xlsx_streams_started_done(sample_xlsx_bytes):
    mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    by_event, kinds = _run_convert("sample.xlsx", sample_xlsx_bytes, mime)
    assert kinds[0] == "started" and kinds[-1] == "done"
    assert by_event["started"]["converter"] == "xlsx-openpyxl"
    assert_golden(by_event["done"]["markdown"], "xlsx/sample.md")


def test_convert_html_streams_started_done(sample_html):
    by_event, kinds = _run_convert("sample.html", sample_html.encode("utf-8"), "text/html")
    assert kinds[0] == "started" and kinds[-1] == "done"
    assert by_event["started"]["converter"] == "html-trafilatura"
    assert_golden(by_event["done"]["markdown"], "html/sample.md")
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/api/test_convert.py -v -k "docx or pptx or xlsx or html"`
Expected: FAIL — the four new tests end in an `error` event (`UNSUPPORTED_FORMAT`) because no converter is registered, so `kinds[-1] == "done"` fails.

- [ ] **Step 3: Register the four converters in the lifespan**

In `src/mdflow/api/app.py`, add imports next to the existing `from mdflow.converters.text import TextConverter` (line 22):

```python
from mdflow.converters.docx import DocxConverter
from mdflow.converters.html import HtmlConverter
from mdflow.converters.pptx import PptxConverter
from mdflow.converters.spreadsheet import XlsxConverter
from mdflow.converters.text import TextConverter
```

Then in `_lifespan`, after `registry.register(TextConverter())` (line 57), add:

```python
    registry.register(DocxConverter())
    registry.register(PptxConverter())
    registry.register(XlsxConverter())
    registry.register(HtmlConverter())
```

- [ ] **Step 4: Run the integration tests to verify they pass**

Run: `.venv/bin/pytest tests/api/test_convert.py -v -k "docx or pptx or xlsx or html"`
Expected: the 4 new tests pass (each streams `started` with the right converter name and a `done` whose markdown matches the golden).

- [ ] **Step 5: Run the full suite + lint**

Run:
```bash
.venv/bin/pytest -q && .venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests
```
Expected: all tests pass (191 baseline + ~25 new), ruff check reports "All checks passed!", format check reports no changes needed. If `ruff format --check` fails, run `.venv/bin/ruff format src tests` and re-stage.

- [ ] **Step 6: Commit**

```bash
git add src/mdflow/api/app.py tests/api/test_convert.py
git commit -m "feat(m1b): register office converters + per-format SSE integration tests"
```

---

## Task 7: State update + Codex milestone review (non-code wrap-up)

**Files:**
- Modify: `PROCESS_STATE.md`

- [ ] **Step 1: Update `PROCESS_STATE.md`**

Per CLAUDE.md §4, update §2 "한눈에 보기" and §7 (M1): mark M1b converters implemented, note the new converter modules + golden infra, record the new test/lint baseline (run `.venv/bin/pytest -q` and copy the passed/skipped counts), and set the next action to "M1b Codex 묶음 리뷰".

- [ ] **Step 2: Commit the state update**

```bash
git add PROCESS_STATE.md
git commit -m "docs(m1b): update PROCESS_STATE after office converters"
```

- [ ] **Step 3: Codex milestone bundle review**

Per CLAUDE.md §3 + memory (Codex review is milestone-cadence, not per-task), send the full M1b diff for independent review via the `codex-peer-reviewer` skill. M1a's lesson: Codex caught a design-§6 violation (non-`MdflowError` stream truncation) that per-task and final reviews both missed — specifically verify here that **no converter swallows library exceptions** (they must propagate to `run_conversion`'s `CONVERSION_FAILED` wrap). Save the review to `docs/reviews/2026-05-22-m1b-office-converters-codex.md`. Address blocking findings, then mark the milestone adopted.

---

## Self-Review (completed by plan author)

**Spec coverage** (design §§1-9):
- §2 module layout (`_html_to_md`, docx, pptx, spreadsheet, html) → Tasks 2-5. ✓
- §3.1 docx mammoth→html→markdownify, image drop, warnings metadata → Task 2. ✓
- §3.2 pptx title/`## Slide N`, bullet levels (2-space indent), tables, `> Notes:` → Task 3. ✓
- §3.3 xlsx data_only+read_only, per-sheet table, empty-sheet handling, `formula_values="cached"` → Task 4. ✓
- §3.4 html trafilatura(include_images=False, include_tables=True) + bs4/markdownify fallback + `_decode` reuse → Task 5. ✓
- §4 golden infra (`assert_golden`, `MDFLOW_UPDATE_GOLDEN`, code-generated fixtures), §4.3 per-format SSE integration → Tasks 1, 6. ✓
- §5 7 dependencies → Task 0. ✓
- §6 no internal try/except (propagate to CONVERSION_FAILED) → enforced in every converter (Tasks 2-5) + Codex check (Task 7). ✓
- §7 test strategy (golden-first, full pytest + ruff clean) → Task 6 Step 5. ✓
- §8 Task table 0-7 → Tasks 0-7. ✓

**Placeholder scan:** No TBD/TODO/"handle edge cases"; every code step shows complete code; every test step shows the assertions; golden files are generated+reviewed, not hand-waved.

**Type consistency:** `html_to_markdown(html, *, strip_images=False)` defined in Task 2, called with `strip_images=True` (docx) and default (html fallback) — consistent. Converter attribute names (`name`/`formats`/`requires_gpu`/`can_handle`/`convert`) match the Protocol in `base.py`. `assert_golden(actual, golden_name)` signature consistent across Tasks 2-6. `_decode` import path (`mdflow.converters.text`) matches the existing function.

**Known runtime risk flagged in-plan:** trafilatura article detection can be finicky on tiny fixtures — Task 5 Step 4 tells the implementer to lengthen the fixture `<p>` if extraction returns None. Markdownify list bullet style (`-` vs `*`) is asserted permissively in the helper test and locked exactly by the golden.
