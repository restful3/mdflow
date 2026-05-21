"""Runtime capabilities: GPU detection + env override + boot-log line."""

import logging

from mdflow.runtime.capabilities import Capabilities, detect


def test_capabilities_dataclass_fields():
    caps = Capabilities(gpu=False, cuda_version=None, cpu_workers=4)
    assert caps.gpu is False
    assert caps.cuda_version is None
    assert caps.cpu_workers == 4


def test_detect_force_cpu_overrides(monkeypatch):
    monkeypatch.setenv("MDFLOW_FORCE_CPU", "1")
    caps = detect()
    assert caps.gpu is False
    assert caps.cuda_version is None
    assert caps.cpu_workers >= 1


def test_detect_force_cpu_accepts_truthy_aliases(monkeypatch):
    for value in ["1", "true", "TRUE", "yes", "Yes"]:
        monkeypatch.setenv("MDFLOW_FORCE_CPU", value)
        assert detect().gpu is False


def test_detect_without_torch_returns_no_gpu(monkeypatch):
    """When torch is unavailable, gpu must be False without raising."""
    monkeypatch.delenv("MDFLOW_FORCE_CPU", raising=False)
    monkeypatch.setattr(
        "mdflow.runtime.capabilities._try_torch_cuda",
        lambda: (False, None),
    )
    caps = detect()
    assert caps.gpu is False
    assert caps.cuda_version is None


def test_detect_when_torch_reports_gpu(monkeypatch):
    monkeypatch.delenv("MDFLOW_FORCE_CPU", raising=False)
    monkeypatch.setattr(
        "mdflow.runtime.capabilities._try_torch_cuda",
        lambda: (True, "12.1"),
    )
    caps = detect()
    assert caps.gpu is True
    assert caps.cuda_version == "12.1"


def test_boot_log_line_format(caplog, monkeypatch):
    monkeypatch.setenv("MDFLOW_FORCE_CPU", "1")
    with caplog.at_level(logging.INFO, logger="mdflow.runtime.capabilities"):
        Capabilities.log_boot(detect())
    msg = next(r.message for r in caplog.records if "mdflow ready" in r.message)
    assert "gpu=false" in msg
    assert "cuda=none" in msg
    assert "cpu_workers=" in msg


def test_boot_log_includes_cuda_version_when_present(caplog):
    caps = Capabilities(gpu=True, cuda_version="12.1", cpu_workers=8)
    with caplog.at_level(logging.INFO, logger="mdflow.runtime.capabilities"):
        Capabilities.log_boot(caps)
    msg = next(r.message for r in caplog.records if "mdflow ready" in r.message)
    assert "gpu=true" in msg
    assert "cuda=12.1" in msg
    assert "cpu_workers=8" in msg


def test_cpu_workers_is_at_least_one():
    caps = detect()
    assert caps.cpu_workers >= 1
