"""In-process request metrics surfaced on /capabilities (PRD §12).

Counters only (no PII/content). Updated from the single event loop in the
/convert SSE path, so plain int/float increments need no lock. Full
metrics backends (Prometheus) are v2.
"""

from __future__ import annotations


class Metrics:
    def __init__(self) -> None:
        self.requests = 0
        self.failures = 0
        self._latency_sum_s = 0.0
        self._latency_count = 0

    def record(self, *, success: bool, latency_s: float) -> None:
        self.requests += 1
        if not success:
            self.failures += 1
        self._latency_sum_s += latency_s
        self._latency_count += 1

    def snapshot(self) -> dict:
        avg_ms = (self._latency_sum_s / self._latency_count * 1000) if self._latency_count else 0.0
        return {
            "requests": self.requests,
            "failures": self.failures,
            "failure_rate": round(self.failures / self.requests, 4) if self.requests else 0.0,
            "avg_latency_ms": round(avg_ms, 2),
        }
