"""In-process request metrics surfaced on /capabilities (PRD §12).

Single-process best-effort counters (no PII/content). Writes happen on the
/convert event loop (non-awaiting int/float increments under the GIL); the
/capabilities read may run in a threadpool and is eventually consistent (a
read can momentarily observe a record() mid-update — harmless, converges on
the next snapshot). Full metrics backends (Prometheus) are v2.

`requests` counts conversion attempts that reached the SSE stream (success,
conversion/fetch/lookup failure, or cache hit). Pre-stream rejections
(400 invalid input, 413 too large) are returned before the stream and are
NOT counted here. HTTP /convert only — the MCP path is not aggregated (v1).
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
