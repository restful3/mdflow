"""Shared pytest fixtures for mdflow tests."""

import io
from pathlib import Path

import pytest


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_cache_dir(tmp_path: Path) -> Path:
    cache = tmp_path / "mdflow_cache"
    cache.mkdir()
    return cache


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
