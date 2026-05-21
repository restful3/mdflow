"""Pydantic event models for the SSE stream.

Built incrementally; this file currently exposes only the events the
service layer needs at the current milestone. Additional events
(Progress, Cached, Done, Error) land in subsequent steps.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _EventBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Started(_EventBase):
    converter: str
    gpu: bool
    sha256: str


class Queued(_EventBase):
    reason: str
    position: int
