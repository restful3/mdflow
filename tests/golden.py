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
        raise AssertionError(f"golden missing: {path} (run with MDFLOW_UPDATE_GOLDEN=1 to create)")
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
