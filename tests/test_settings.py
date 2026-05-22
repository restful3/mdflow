"""Pydantic-Settings env vars (MDFLOW_*)."""

import pytest

from mdflow.settings import Settings

_ENV_VARS = [
    "MDFLOW_FORCE_CPU",
    "MDFLOW_CACHE_DIR",
    "MDFLOW_MAX_INPUT_MB",
    "MDFLOW_MAX_URL_INPUT_MB",
    "MDFLOW_ALLOW_PRIVATE_URLS",
    "MDFLOW_URL_MAX_REDIRECTS",
    "MDFLOW_URL_CONNECT_TIMEOUT_S",
    "MDFLOW_URL_READ_TIMEOUT_S",
    "MDFLOW_URL_USER_AGENT",
    "MDFLOW_SOFFICE_TIMEOUT_S",
]


def _clean_env(monkeypatch):
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_settings_defaults(monkeypatch):
    _clean_env(monkeypatch)
    s = Settings()
    assert s.force_cpu is False
    assert s.max_input_mb == 200
    assert s.max_url_input_mb == 200
    assert s.allow_private_urls is False
    assert s.url_max_redirects == 5
    assert s.url_connect_timeout_s == 10.0
    assert s.url_read_timeout_s == 30.0
    assert s.url_user_agent.startswith("mdflow/")
    assert s.soffice_timeout_s == 120.0


def test_settings_env_override(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("MDFLOW_FORCE_CPU", "1")
    monkeypatch.setenv("MDFLOW_MAX_URL_INPUT_MB", "50")
    monkeypatch.setenv("MDFLOW_ALLOW_PRIVATE_URLS", "true")
    monkeypatch.setenv("MDFLOW_URL_MAX_REDIRECTS", "3")
    s = Settings()
    assert s.force_cpu is True
    assert s.max_url_input_mb == 50
    assert s.allow_private_urls is True
    assert s.url_max_redirects == 3


def test_max_url_input_must_not_exceed_max_input(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("MDFLOW_MAX_INPUT_MB", "100")
    monkeypatch.setenv("MDFLOW_MAX_URL_INPUT_MB", "200")
    with pytest.raises(ValueError):
        Settings()


def test_zero_or_negative_size_rejected(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("MDFLOW_MAX_INPUT_MB", "0")
    with pytest.raises(ValueError):
        Settings()


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
