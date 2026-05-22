from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OpenOppsSettings(BaseSettings):
    """Runtime settings shared by CLI commands and services."""

    model_config = SettingsConfigDict(
        env_prefix="OPENOPPS_", env_file=".env", extra="ignore"
    )

    db_url: str = "sqlite:///openopps.db"
    max_connections: int = Field(default=40, ge=1)
    source_concurrency: int = Field(default=4, ge=1)
    board_concurrency: int = Field(default=16, ge=1)
    provider_concurrency: int = Field(default=12, ge=1)
    workday_concurrency: int = Field(default=2, ge=1)
    db_batch_size: int = Field(default=500, ge=1)
    http_timeout: float = Field(default=30.0, gt=0)
    retry_attempts: int = Field(default=3, ge=1)
    user_agent: str = "openopps/0.1 (+https://github.com/wyattowalsh/openopps)"
    cache_enabled: bool = True
    cache_ttl_seconds: int = Field(default=3600, ge=1)
    cache_refresh: bool = False
    cache_stale_on_error: bool = False
    plugin_disabled: str = ""
    plugin_allowed: str = ""

    @property
    def sqlite_path(self) -> Path | None:
        if not self.db_url.startswith("sqlite:///"):
            return None
        return Path(self.db_url.removeprefix("sqlite:///")).expanduser()

    @property
    def cache_path(self) -> Path:
        sqlite_path = self.sqlite_path
        if sqlite_path is None:
            return Path("openopps.cache.db")
        return sqlite_path.with_suffix(".cache.db")

    @property
    def plugin_disabled_names(self) -> tuple[str, ...]:
        return _comma_separated(self.plugin_disabled)

    @property
    def plugin_allowed_names(self) -> tuple[str, ...]:
        return _comma_separated(self.plugin_allowed)


def _comma_separated(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())
