from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from openopps.discovery.settings import (
    DiscoverySettings,
    format_discovery_settings_error,
)


ENV_PREFIX = "OPENOPPS_DISCOVERY_"
EXPECTED_DEFAULTS = {
    "whole_run_timeout_seconds": 300,
    "channel_timeout_seconds": 120,
    "channel_query_limit": 20,
    "channel_request_limit": 100,
    "origin_limit": 25,
    "redirect_limit": 5,
    "per_host_concurrency": 2,
    "overall_concurrency": 8,
    "response_max_bytes": 1_048_576,
    "aggregate_response_max_bytes": 67_108_864,
    "candidate_limit": 1_000,
    "retry_attempt_limit": 3,
    "pagination_limit": 20,
    "parser_max_depth": 32,
    "evidence_retention_seconds": 86_400,
}

EXPECTED_MAXIMUMS = {
    "whole_run_timeout_seconds": 3_600,
    "channel_timeout_seconds": 1_800,
    "channel_query_limit": 1_000,
    "channel_request_limit": 5_000,
    "origin_limit": 500,
    "redirect_limit": 10,
    "per_host_concurrency": 16,
    "overall_concurrency": 64,
    "response_max_bytes": 10_485_760,
    "aggregate_response_max_bytes": 268_435_456,
    "candidate_limit": 10_000,
    "retry_attempt_limit": 10,
    "pagination_limit": 1_000,
    "parser_max_depth": 128,
    "evidence_retention_seconds": 604_800,
}


def _clear_discovery_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in tuple(os.environ):
        if name.startswith(ENV_PREFIX):
            monkeypatch.delenv(name)


def _environment_name(field_name: str) -> str:
    return f"{ENV_PREFIX}{field_name.upper()}"


def test_discovery_settings_have_a_closed_finite_default_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_discovery_environment(monkeypatch)

    settings = DiscoverySettings()

    assert set(DiscoverySettings.model_fields) == set(EXPECTED_DEFAULTS)
    assert settings.model_dump() == EXPECTED_DEFAULTS
    assert all(
        isinstance(value, int) and not isinstance(value, bool) and value > 0
        for value in settings.model_dump().values()
    )


def test_discovery_settings_use_only_the_dedicated_environment_namespace() -> None:
    config = DiscoverySettings.model_config

    assert config.get("env_prefix") == ENV_PREFIX
    assert config.get("env_file") is None
    assert config.get("extra") == "ignore"
    assert config.get("strict") is True
    assert config.get("validate_default") is True
    assert config.get("hide_input_in_errors") is True


def test_discovery_settings_parse_each_exact_environment_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_discovery_environment(monkeypatch)
    expected = dict.fromkeys(EXPECTED_DEFAULTS, 1)
    for field_name, value in expected.items():
        monkeypatch.setenv(_environment_name(field_name), str(value))

    assert DiscoverySettings().model_dump() == expected


def test_discovery_settings_ignore_similar_but_wrong_prefixes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_discovery_environment(monkeypatch)
    field_name = "whole_run_timeout_seconds"
    monkeypatch.setenv(f"OPENOPPS_{field_name.upper()}", "999")
    monkeypatch.setenv(f"DISCOVERY_{field_name.upper()}", "999")

    assert (
        DiscoverySettings().whole_run_timeout_seconds == EXPECTED_DEFAULTS[field_name]
    )

    monkeypatch.setenv(_environment_name(field_name), "7")

    assert DiscoverySettings().whole_run_timeout_seconds == 7


@pytest.mark.parametrize("field_name", EXPECTED_DEFAULTS)
@pytest.mark.parametrize("invalid_value", [0, -1])
def test_discovery_settings_reject_non_positive_integer_values(
    field_name: str,
    invalid_value: int,
) -> None:
    with pytest.raises(ValidationError):
        DiscoverySettings(**{field_name: invalid_value})


@pytest.mark.parametrize("invalid_value", [True, 1.0, "1"])
def test_discovery_settings_reject_python_type_coercion(
    invalid_value: object,
) -> None:
    with pytest.raises(ValidationError):
        DiscoverySettings(whole_run_timeout_seconds=invalid_value)


@pytest.mark.parametrize(
    "invalid_value",
    ["", "0", "-1", "01", "+1", " 1 ", "1.0", "1e2", "true"],
)
def test_discovery_settings_reject_ambiguous_environment_integers(
    monkeypatch: pytest.MonkeyPatch,
    invalid_value: str,
) -> None:
    _clear_discovery_environment(monkeypatch)
    monkeypatch.setenv(_environment_name("whole_run_timeout_seconds"), invalid_value)

    with pytest.raises(ValidationError):
        DiscoverySettings()


def test_discovery_settings_do_not_read_dotenv_or_ambient_secrets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_discovery_environment(monkeypatch)
    dotenv_secret = "dotenv-discovery-secret-7f14"
    ambient_secret = "ambient-discovery-secret-9a31"
    (tmp_path / ".env").write_text(
        "\n".join(
            (
                "OPENOPPS_DISCOVERY_WHOLE_RUN_TIMEOUT_SECONDS=999",
                f"OPENOPPS_DISCOVERY_API_TOKEN={dotenv_secret}",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", ambient_secret)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", ambient_secret)
    monkeypatch.setenv("OPENOPPS_DB_URL", ambient_secret)

    settings = DiscoverySettings()
    rendered = repr(settings.model_dump())

    assert settings.model_dump() == EXPECTED_DEFAULTS
    assert dotenv_secret not in rendered
    assert ambient_secret not in rendered


def test_discovery_settings_ignore_unknown_prefixed_ambient_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_discovery_environment(monkeypatch)
    marker = "unknown-prefixed-secret-2c63"
    monkeypatch.setenv("OPENOPPS_DISCOVERY_API_TOKEN", marker)

    rendered = repr(DiscoverySettings().model_dump())

    assert marker not in rendered


def test_discovery_settings_schema_semantically_describes_every_field() -> None:
    schema = DiscoverySettings.model_json_schema()

    for field_name in EXPECTED_DEFAULTS:
        field_schema = schema["properties"][field_name]
        description = str(field_schema.get("description", "")).lower()
        assert len(description) >= 40, field_name
        assert field_schema.get("type") == "integer", field_name
        assert field_schema.get("exclusiveMinimum") == 0, field_name
        assert field_schema.get("maximum") == EXPECTED_MAXIMUMS[field_name], field_name


@pytest.mark.parametrize(("field_name", "maximum"), EXPECTED_MAXIMUMS.items())
def test_discovery_settings_accept_exact_maximum_and_reject_larger_value(
    field_name: str,
    maximum: int,
) -> None:
    assert (
        DiscoverySettings(**{field_name: maximum}).model_dump()[field_name] == maximum
    )
    with pytest.raises(ValidationError):
        DiscoverySettings(**{field_name: maximum + 1})


def test_discovery_settings_are_immutable() -> None:
    settings = DiscoverySettings()

    with pytest.raises(ValidationError):
        settings.channel_request_limit = 1


def test_discovery_settings_validation_error_hides_secret_bearing_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_discovery_environment(monkeypatch)
    marker = "validation-secret-5e82"
    monkeypatch.setenv(
        "OPENOPPS_DISCOVERY_WHOLE_RUN_TIMEOUT_SECONDS",
        f"1password={marker}",
    )

    with pytest.raises(ValidationError) as exc_info:
        DiscoverySettings()

    assert marker not in str(exc_info.value)
    assert marker not in repr(exc_info.value)


def test_format_discovery_settings_error_names_single_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_discovery_environment(monkeypatch)
    monkeypatch.setenv(_environment_name("whole_run_timeout_seconds"), "0")

    with pytest.raises(ValidationError) as exc_info:
        DiscoverySettings()

    assert (
        format_discovery_settings_error(exc_info.value)
        == "Invalid OpenOpps discovery configuration: "
        "OPENOPPS_DISCOVERY_WHOLE_RUN_TIMEOUT_SECONDS."
    )


def test_format_discovery_settings_error_lists_first_three_unique_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_discovery_environment(monkeypatch)
    for field_name in (
        "whole_run_timeout_seconds",
        "channel_timeout_seconds",
        "channel_query_limit",
        "channel_request_limit",
    ):
        monkeypatch.setenv(_environment_name(field_name), "0")

    with pytest.raises(ValidationError) as exc_info:
        DiscoverySettings()

    message = format_discovery_settings_error(exc_info.value)

    assert message == (
        "Invalid OpenOpps discovery configuration: "
        "OPENOPPS_DISCOVERY_WHOLE_RUN_TIMEOUT_SECONDS, "
        "OPENOPPS_DISCOVERY_CHANNEL_TIMEOUT_SECONDS, "
        "OPENOPPS_DISCOVERY_CHANNEL_QUERY_LIMIT, "
        "and 1 more field(s)."
    )
    assert "CHANNEL_REQUEST_LIMIT" not in message


def test_format_discovery_settings_error_does_not_echo_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_discovery_environment(monkeypatch)
    marker = "formatter-secret-8b17"
    monkeypatch.setenv(
        _environment_name("whole_run_timeout_seconds"),
        f"1password={marker}",
    )

    with pytest.raises(ValidationError) as exc_info:
        DiscoverySettings()

    message = format_discovery_settings_error(exc_info.value)

    assert marker not in message
    assert "1password=" not in message


def test_format_discovery_settings_error_empty_loc_uses_star() -> None:
    marker = "empty-loc-secret-3d44"
    error = ValidationError.from_exception_data(
        "DiscoverySettings",
        [{"type": "int_parsing", "loc": (), "input": marker}],
    )

    message = format_discovery_settings_error(error)

    assert message == "Invalid OpenOpps discovery configuration: OPENOPPS_DISCOVERY_*."
    assert marker not in message


def test_format_discovery_settings_error_no_fields_fallback() -> None:
    error = ValidationError.from_exception_data("DiscoverySettings", [])

    assert (
        format_discovery_settings_error(error)
        == "Invalid OpenOpps discovery configuration."
    )
