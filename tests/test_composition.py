from mdflow.runtime.composition import build_registry
from mdflow.settings import Settings


def test_build_registry_has_all_converters():
    names = {row["converter"] for row in build_registry(Settings()).list_formats()}
    assert names == {
        "text-passthrough",
        "docx-mammoth",
        "pptx-python-pptx",
        "xlsx-openpyxl",
        "html-trafilatura",
        "pdf-marker",
        "pdf-pymupdf4llm",
        "office-libreoffice",
        "hwp-pyhwp",
    }


def test_marker_registered_before_pymupdf():
    """first-wins gating: Marker(GPU) precedes PyMuPDF(CPU) for `pdf`."""
    rows = [row for row in build_registry(Settings()).list_formats() if row["ext"] == "pdf"]
    assert [r["converter"] for r in rows] == ["pdf-marker", "pdf-pymupdf4llm"]


def test_build_registry_allow_gpu_false_omits_marker():
    """allow_gpu=False excludes requires_gpu=True converters so the
    HTTP-mounted MCP cannot bypass the SSE path's gpu_semaphore."""
    rows = build_registry(Settings(), allow_gpu=False).list_formats()
    names = {r["converter"] for r in rows}
    assert "pdf-marker" not in names
    assert "pdf-pymupdf4llm" in names
    # And no requires_gpu=True converter slipped through.
    assert all(r["requires_gpu"] is False for r in rows)
