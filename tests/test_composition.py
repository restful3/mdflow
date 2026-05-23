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
