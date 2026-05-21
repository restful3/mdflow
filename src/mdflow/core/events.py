"""Pydantic event models for the SSE stream.

Full set of v1 events: Started, Queued, Progress, Cached, Done, Error.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _EventBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Started(_EventBase):
    converter: str
    gpu: bool
    sha256: str


class Queued(_EventBase):
    reason: str
    position: int


class Progress(_EventBase):
    stage: str
    pct: int = Field(ge=0, le=100)
    detail: str = ""


class Cached(_EventBase):
    sha256: str
    cached_at: str  # ISO-8601 string; v1 uses string for SSE simplicity


class Done(_EventBase):
    markdown: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    assets: list[str] = Field(default_factory=list)


class Error(_EventBase):
    code: str
    message: str
    retryable: bool
