"""Isolate API tests from the real cache dir.

create_app() builds Settings() from the environment, whose cache_dir
defaults to ~/.cache/mdflow. Admin tests write entries and call
/cache/purge, which would otherwise mutate (and purge!) the user's real
cache. Redirect MDFLOW_CACHE_DIR to a per-test tmp dir for every test in
this package.
"""

import pytest


@pytest.fixture(autouse=True)
def _isolated_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MDFLOW_CACHE_DIR", str(tmp_path / "cache"))
