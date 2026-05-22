"""Tests for the golden comparison harness itself."""

import pytest

from tests.golden import assert_golden, normalize


def test_normalize_strips_trailing_ws_and_collapses_final_newline():
    assert normalize("a  \nb\n\n\n") == "a\nb\n"


def test_update_mode_refuses_to_write_under_ci(monkeypatch):
    # A leaked MDFLOW_UPDATE_GOLDEN in CI would make every golden test
    # rewrite-and-pass. The harness must hard-fail instead of silently
    # passing. Use a nonexistent golden so a regression (no guard) would
    # otherwise write a file.
    monkeypatch.setenv("MDFLOW_UPDATE_GOLDEN", "1")
    monkeypatch.setenv("CI", "true")
    with pytest.raises(AssertionError, match="CI"):
        assert_golden("anything", "does-not-exist/sample.md")
