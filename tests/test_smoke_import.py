"""Smoke test: package importable, version exposed."""

import mdflow


def test_package_imports():
    assert hasattr(mdflow, "__version__")
    assert isinstance(mdflow.__version__, str)
    assert mdflow.__version__.count(".") >= 1
