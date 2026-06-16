from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Annotated

from pydantic import (
    AfterValidator,
    Field,
    StringConstraints,
    computed_field,
    field_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


def _validate_db_url(value: str) -> str:
    if "://" not in value:
        raise ValueError(
            "db_url must be a SQLAlchemy-style URL such as sqlite:///openoppsdb.sqlite"
        )
    return value


DatabaseUrl = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
    AfterValidator(_validate_db_url),
]
PositiveIntSetting = Annotated[int, Field(ge=1)]
PositiveFloatSetting = Annotated[float, Field(gt=0, allow_inf_nan=False)]
NonNegativeFloatSetting = Annotated[float, Field(ge=0, allow_inf_nan=False)]
StrippedString = Annotated[str, StringConstraints(strip_whitespace=True)]


class OpenOppsSettings(BaseSettings):
    """Environment-backed runtime settings shared by CLI commands and services."""

    model_config = SettingsConfigDict(
        env_prefix="OPENOPPS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        str_strip_whitespace=True,
        validate_assignment=True,
        validate_default=True,
        title="OpenOppsSettings",
        json_schema_extra={
            "description": (
                "Runtime configuration loaded from keyword arguments, environment "
                "variables prefixed with OPENOPPS_, and an optional local .env file."
            )
        },
    )

    db_url: DatabaseUrl = Field(
        default="sqlite:///openoppsdb.sqlite",
        description=(
            "SQLAlchemy database URL used by storage, migrations, and status output. "
            "Use sqlite:///relative/path.db for local project data, "
            "sqlite:////absolute/path.db for absolute SQLite files, or another "
            "SQLAlchemy URL when running against a supported external database."
        ),
        examples=["sqlite:///openoppsdb.sqlite", "sqlite:////tmp/openoppsdb.sqlite"],
    )
    max_connections: PositiveIntSetting = Field(
        default=40,
        description=(
            "Maximum number of simultaneous outbound HTTP connections shared by the "
            "async client. The keep-alive pool is derived from this value, so raise "
            "it only when upstream providers and the local network can handle more "
            "parallelism."
        ),
        examples=[40],
    )
    source_concurrency: PositiveIntSetting = Field(
        default=4,
        description=(
            "Maximum number of board-source discovery adapters that may run at the "
            "same time during source sync and provider health checks."
        ),
        examples=[4],
    )
    source_timeout_seconds: PositiveFloatSetting = Field(
        default=900.0,
        description=(
            "Maximum wall-clock time, in seconds, allowed for one source adapter "
            "during source sync before OpenOpps records a classified timeout and "
            "continues with the remaining sources."
        ),
        examples=[900.0],
    )
    source_freshness_seconds: NonNegativeFloatSetting = Field(
        default=0.0,
        description=(
            "Freshness window, in seconds, for skipping recently synced source "
            "catalogs during unscoped full sync retries. A value of 0 disables the "
            "skip and refreshes every enabled source."
        ),
        examples=[0.0, 86400.0],
    )
    board_concurrency: PositiveIntSetting = Field(
        default=16,
        description=(
            "Maximum number of ready board routes or board-scoped listing requests "
            "processed concurrently during job sync, route checks, and providers that "
            "fan out across job detail pages."
        ),
        examples=[16],
    )
    job_route_timeout_seconds: PositiveFloatSetting = Field(
        default=180.0,
        description=(
            "Maximum wall-clock time, in seconds, allowed for one executable job "
            "provider route during job sync before OpenOpps records a classified "
            "timeout and continues with the remaining routes."
        ),
        examples=[180.0],
    )
    job_route_freshness_seconds: NonNegativeFloatSetting = Field(
        default=0.0,
        description=(
            "Freshness window, in seconds, for skipping recently synced provider "
            "routes during job sync. A value of 0 disables the skip and refreshes "
            "every selected route."
        ),
        examples=[0.0, 86400.0],
    )
    job_route_limit: PositiveIntSetting | None = Field(
        default=None,
        description=(
            "Maximum number of stale or never-synced provider routes to process "
            "during one job sync. Unset means every selected stale route is processed."
        ),
        examples=[500],
    )
    provider_concurrency: PositiveIntSetting = Field(
        default=12,
        description=(
            "Maximum number of provider route probes running concurrently when "
            "OpenOpps detects executable job-board routes."
        ),
        examples=[12],
    )
    workday_concurrency: PositiveIntSetting = Field(
        default=2,
        description=(
            "Maximum number of Workday CXS job detail requests processed at once. "
            "The default is intentionally conservative because Workday careers sites "
            "are slower and more rate-limit sensitive than most public JSON APIs."
        ),
        examples=[2],
    )
    db_batch_size: PositiveIntSetting = Field(
        default=500,
        description=(
            "Number of normalized records written per database transaction batch for "
            "bulk source, board, provider, and job upserts. Larger values reduce "
            "commit overhead but keep more pending records in memory."
        ),
        examples=[500],
    )
    http_timeout: PositiveFloatSetting = Field(
        default=30.0,
        description=(
            "Per-request HTTP timeout, in seconds, applied to the shared async HTTPX "
            "client before Tenacity retry handling decides whether to retry."
        ),
        examples=[30.0],
    )
    retry_attempts: PositiveIntSetting = Field(
        default=3,
        description=(
            "Maximum attempts for retryable HTTP requests. Retries cover transient "
            "network failures and retryable upstream status codes such as 429 and 5xx."
        ),
        examples=[3],
    )
    user_agent: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1),
    ] = Field(
        default="openopps/0.1 openopps@wyattowalsh.com",
        description=(
            "User-Agent header sent with public provider requests. Keep it descriptive "
            "so upstream operators can identify OpenOpps traffic and contact the "
            "project if needed."
        ),
        examples=["openopps/0.1 openopps@wyattowalsh.com"],
    )
    cache_enabled: bool = Field(
        default=True,
        description=(
            "Enable the shared HTTP JSON cache in the configured SQLite database for "
            "cache-aware provider requests. Disable only when tests or one-off "
            "diagnostics must force live upstream reads."
        ),
        examples=[True],
    )
    cache_ttl_seconds: PositiveIntSetting = Field(
        default=3600,
        description=(
            "Freshness window, in seconds, for cache entries before OpenOpps considers "
            "them stale and refetches the upstream response."
        ),
        examples=[3600],
    )
    cache_refresh: bool = Field(
        default=False,
        description=(
            "Bypass fresh cache hits and refresh upstream responses for cache-aware "
            "requests. CLI commands usually set this through --refresh-cache instead "
            "of requiring an environment variable."
        ),
        examples=[False],
    )
    cache_stale_on_error: bool = Field(
        default=False,
        description=(
            "Return a stale cached JSON response when an upstream refresh fails after "
            "all retries. This improves resilience for read-heavy workflows but can "
            "surface older provider data."
        ),
        examples=[False],
    )
    plugin_autoload: bool = Field(
        default=False,
        description=(
            "Allow all installed openopps.plugins entry points to load unless they are "
            "explicitly disabled. Keep this off for predictable CLI startup and use "
            "plugin_allowed for explicit opt-in."
        ),
        examples=[False],
    )
    plugin_disabled: StrippedString = Field(
        default="",
        description=(
            "Comma-separated openopps.plugins entry-point names that must never load. "
            "Whitespace is ignored, empty entries are dropped, and names are evaluated "
            "before the allow-list."
        ),
        examples=["experimental_plugin,legacy_plugin"],
    )
    plugin_allowed: StrippedString = Field(
        default="",
        description=(
            "Comma-separated openopps.plugins entry-point names allowed to load when "
            "plugin_autoload is false. Leave empty to disable third-party plugin "
            "autoloading by default."
        ),
        examples=["trusted_source_plugin,internal_export_plugin"],
    )

    @field_validator("plugin_disabled", "plugin_allowed", mode="before")
    @classmethod
    def _normalize_plugin_csv(cls, value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return ",".join(_comma_separated(value))
        if isinstance(value, Sequence):
            items = (str(item).strip() for item in value)
            return ",".join(item for item in items if item)
        raise ValueError("plugin filters must be a comma-separated string or sequence")

    @computed_field(
        description=(
            "Resolved filesystem path for sqlite:/// database URLs, or None when the "
            "database URL is not a local SQLite file."
        ),
        return_type=Path | None,
        repr=False,
    )
    @property
    def sqlite_path(self) -> Path | None:
        if not self.db_url.startswith("sqlite:///"):
            return None
        return Path(self.db_url.removeprefix("sqlite:///")).expanduser()

    @computed_field(
        description="Normalized tuple of disabled plugin entry-point names.",
        return_type=tuple[str, ...],
        repr=False,
    )
    @property
    def plugin_disabled_names(self) -> tuple[str, ...]:
        return _comma_separated(self.plugin_disabled)

    @computed_field(
        description="Normalized tuple of allowed plugin entry-point names.",
        return_type=tuple[str, ...],
        repr=False,
    )
    @property
    def plugin_allowed_names(self) -> tuple[str, ...]:
        return _comma_separated(self.plugin_allowed)


def _comma_separated(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())
