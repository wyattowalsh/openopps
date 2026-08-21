"""Strict finite configuration for the isolated source-discovery scout."""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import Field, ValidationError
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


PositiveInt = Annotated[int, Field(strict=True, gt=0)]


class _CanonicalIntegerEnvSource(EnvSettingsSource):
    """Parse only canonical positive decimal spellings from the environment."""

    def prepare_field_value(
        self,
        field_name: str,
        field: FieldInfo,
        value: object,
        value_is_complex: bool,
    ) -> object:
        del field_name, field, value_is_complex
        if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]*", value):
            return int(value)
        return value


class DiscoverySettings(BaseSettings):
    """Credential-free finite limits loaded only from discovery-prefixed values."""

    model_config = SettingsConfigDict(
        env_prefix="OPENOPPS_DISCOVERY_",
        env_file=None,
        extra="ignore",
        strict=True,
        frozen=True,
        validate_default=True,
        hide_input_in_errors=True,
        title="DiscoverySettings",
        json_schema_extra={
            "description": (
                "Finite, maintainer-controlled limits for one isolated OpenOpps "
                "source-discovery invocation."
            )
        },
    )

    whole_run_timeout_seconds: PositiveInt = Field(
        default=300,
        le=3_600,
        description=(
            "Maximum wall-clock duration in seconds for the entire isolated "
            "discovery invocation before remaining work is cancelled."
        ),
    )
    channel_timeout_seconds: PositiveInt = Field(
        default=120,
        le=1_800,
        description=(
            "Maximum wall-clock duration in seconds for one discovery channel "
            "before its remaining operations are cancelled."
        ),
    )
    channel_query_limit: PositiveInt = Field(
        default=20,
        le=1_000,
        description=(
            "Maximum number of trusted, predeclared queries admitted by any one "
            "discovery channel during a single invocation."
        ),
    )
    channel_request_limit: PositiveInt = Field(
        default=100,
        le=5_000,
        description=(
            "Maximum number of requests, including retries, redirects, and "
            "pagination, consumed by one discovery channel."
        ),
    )
    origin_limit: PositiveInt = Field(
        default=25,
        le=500,
        description=(
            "Maximum number of distinct validated public HTTPS origins contacted "
            "by one discovery channel."
        ),
    )
    redirect_limit: PositiveInt = Field(
        default=5,
        le=10,
        description=(
            "Maximum number of manually validated redirect hops consumed by one "
            "logical discovery request."
        ),
    )
    per_host_concurrency: PositiveInt = Field(
        default=2,
        le=16,
        description=(
            "Maximum number of simultaneous discovery connections admitted for "
            "one validated public origin."
        ),
    )
    overall_concurrency: PositiveInt = Field(
        default=8,
        le=64,
        description=(
            "Maximum number of simultaneous requests admitted across every "
            "discovery channel in one isolated invocation."
        ),
    )
    response_max_bytes: PositiveInt = Field(
        default=1_048_576,
        le=10_485_760,
        description=(
            "Maximum decoded bytes admitted from one discovery response before "
            "the response is terminated and discarded."
        ),
    )
    aggregate_response_max_bytes: PositiveInt = Field(
        default=67_108_864,
        le=268_435_456,
        description=(
            "Maximum decoded response bytes admitted across every resource and "
            "channel during one isolated discovery invocation."
        ),
    )
    candidate_limit: PositiveInt = Field(
        default=1_000,
        le=10_000,
        description=(
            "Maximum candidate occurrences admitted by one discovery channel "
            "before remaining observations become unstarted."
        ),
    )
    retry_attempt_limit: PositiveInt = Field(
        default=3,
        le=10,
        description=(
            "Maximum total attempts for one logical request, including its first "
            "attempt and every transient retry."
        ),
    )
    pagination_limit: PositiveInt = Field(
        default=20,
        le=1_000,
        description=(
            "Maximum number of pagination requests consumed by one logical "
            "discovery enumeration before unfinished work is recorded."
        ),
    )
    parser_max_depth: PositiveInt = Field(
        default=32,
        le=128,
        description=(
            "Maximum trusted structural nesting depth accepted by bounded JSON, "
            "XML, HTML, and structured-text parsers."
        ),
    )
    evidence_retention_seconds: PositiveInt = Field(
        default=86_400,
        le=604_800,
        description=(
            "Maximum age in seconds for exact verified quarantine evidence to be "
            "considered reusable by a later scout."
        ),
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Use direct arguments plus the exact discovery environment only."""

        del cls, env_settings, dotenv_settings, file_secret_settings
        return (init_settings, _CanonicalIntegerEnvSource(settings_cls))


def format_discovery_settings_error(error: ValidationError) -> str:
    """Render bounded field-only settings failures without echoing input values."""

    fields: list[str] = []
    for item in error.errors(
        include_context=False,
        include_input=False,
        include_url=False,
    ):
        location = item.get("loc", ())
        field = str(location[0]) if location else "*"
        fields.append(f"OPENOPPS_DISCOVERY_{field}".upper())
    unique_fields = tuple(dict.fromkeys(fields))
    if not unique_fields:
        return "Invalid OpenOpps discovery configuration."
    visible = ", ".join(unique_fields[:3])
    if len(unique_fields) > 3:
        visible += f", and {len(unique_fields) - 3} more field(s)"
    return f"Invalid OpenOpps discovery configuration: {visible}."
