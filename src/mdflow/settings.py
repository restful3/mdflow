"""Environment-derived settings (MDFLOW_*).

Reflects the URL handling agreement at
docs/reviews/2026-05-21-url-handling-final-agreement.md §3.10 — the v1
URL fetch knobs are read from env, never from request options.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MDFLOW_",
        env_file=None,
        extra="ignore",
    )

    force_cpu: bool = Field(default=False)
    cache_dir: Path = Field(default_factory=lambda: Path.home() / ".cache" / "mdflow")
    max_input_mb: int = Field(default=200, gt=0)
    max_url_input_mb: int = Field(default=200, gt=0)
    allow_private_urls: bool = Field(default=False)
    url_max_redirects: int = Field(default=5, ge=0)
    url_connect_timeout_s: float = Field(default=10.0, gt=0)
    url_read_timeout_s: float = Field(default=30.0, gt=0)
    url_user_agent: str = Field(default="mdflow/0.0.1 (+https://github.com/restful3/mdflow)")

    @model_validator(mode="after")
    def _check_url_input_cap(self) -> Settings:
        if self.max_url_input_mb > self.max_input_mb:
            raise ValueError(
                f"MDFLOW_MAX_URL_INPUT_MB ({self.max_url_input_mb}) must be <= "
                f"MDFLOW_MAX_INPUT_MB ({self.max_input_mb})"
            )
        return self
