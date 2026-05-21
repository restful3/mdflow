"""Detect GPU + CPU runtime properties.

PRD §3 — at boot the app inspects torch.cuda.is_available(); the
result populates a `Capabilities` singleton stored on app.state and
drives PDF converter selection in later milestones. `MDFLOW_FORCE_CPU`
overrides detection regardless of host hardware.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Capabilities:
    gpu: bool
    cuda_version: str | None
    cpu_workers: int

    @staticmethod
    def log_boot(caps: Capabilities) -> None:
        cuda = caps.cuda_version or "none"
        logger.info(
            "mdflow ready: gpu=%s cuda=%s cpu_workers=%d",
            str(caps.gpu).lower(),
            cuda,
            caps.cpu_workers,
        )


def _try_torch_cuda() -> tuple[bool, str | None]:
    try:
        import torch  # type: ignore[import-not-found]
    except ImportError:
        return False, None
    try:
        if torch.cuda.is_available():
            return True, torch.version.cuda  # type: ignore[attr-defined]
        return False, None
    except Exception:  # noqa: BLE001 — defensive: torch import succeeded but cuda probe failed
        return False, None


def detect() -> Capabilities:
    if os.environ.get("MDFLOW_FORCE_CPU", "").lower() in {"1", "true", "yes"}:
        gpu, cuda = False, None
    else:
        gpu, cuda = _try_torch_cuda()
    cpu_workers = max(1, os.cpu_count() or 1)
    return Capabilities(gpu=gpu, cuda_version=cuda, cpu_workers=cpu_workers)
