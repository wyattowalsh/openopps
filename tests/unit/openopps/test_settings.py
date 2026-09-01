from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from openopps.settings import OpenOppsSettings, format_settings_validation_error


def test_settings_schema_describes_every_config_field() -> None:
    schema = OpenOppsSettings.model_json_schema()

    for field_name in OpenOppsSettings.model_fields:
        field_schema = schema["properties"][field_name]
        description = field_schema.get("description", "")
        assert len(description) >= 40, field_name


def test_settings_rejects_non_url_database_value() -> None:
    with pytest.raises(ValidationError, match="SQLAlchemy-style URL"):
        OpenOppsSettings(db_url="openoppsdb.sqlite")


@pytest.mark.parametrize(
    "db_url",
    [
        "sqlite:///:memory:",
        "postgresql://openopps@example.test/openopps",
        "sqlite+pysqlite:///openopps.db",
    ],
)
def test_settings_rejects_non_file_backed_sqlite_database_urls(db_url: str) -> None:
    with pytest.raises(ValidationError, match="file-backed SQLite"):
        OpenOppsSettings(db_url=db_url)


def test_settings_validation_error_message_is_redacted() -> None:
    raw_db_url = "openoppsdb.sqlite?password=supersecret"

    with pytest.raises(ValidationError) as exc_info:
        OpenOppsSettings(db_url=raw_db_url, max_connections=0)

    message = format_settings_validation_error(exc_info.value)

    assert message.startswith("Invalid OpenOpps configuration:")
    assert "OPENOPPS_DB_URL" in message
    assert "OPENOPPS_MAX_CONNECTIONS" in message
    assert raw_db_url not in message
    assert "supersecret" not in message


def test_settings_normalizes_plugin_filter_values() -> None:
    settings = OpenOppsSettings(
        plugin_allowed=" allowed, blocked ,, extra ",
        plugin_disabled=" blocked ,, skipped ",
    )

    assert settings.plugin_allowed == "allowed,blocked,extra"
    assert settings.plugin_allowed_names == ("allowed", "blocked", "extra")
    assert settings.plugin_disabled == "blocked,skipped"
    assert settings.plugin_disabled_names == ("blocked", "skipped")


def test_settings_computed_paths_are_documented_and_stable(tmp_path: Path) -> None:
    db_path = tmp_path / "openopps.db"
    settings = OpenOppsSettings(db_url=f"sqlite:///{db_path}")

    assert settings.sqlite_path == db_path
    assert "cache_path" not in OpenOppsSettings.model_computed_fields

def test_concurrency_profile_defaults_to_explicit_integers() -> None:
    settings = OpenOppsSettings()

    assert settings.concurrency_profile == "explicit"
    assert settings.source_concurrency == 4
    assert settings.board_concurrency == 16
    assert settings.provider_concurrency == 12
    assert settings.workday_concurrency == 2
    assert settings.max_connections == 40


def test_auto_concurrency_profile_never_raises_workday(monkeypatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr("openopps.settings.available_cpu_count", lambda: 32)
    settings = OpenOppsSettings(concurrency_profile="auto")

    assert settings.concurrency_profile == "auto"
    assert settings.board_concurrency == 32
    assert settings.source_concurrency == 8
    assert settings.provider_concurrency == 16
    assert settings.workday_concurrency == 2
    assert settings.max_connections >= settings.source_concurrency + settings.board_concurrency


def test_auto_concurrency_profile_selects_ci_when_ci_env_is_set(
    monkeypatch,
) -> None:
    monkeypatch.setenv("CI", "true")
    monkeypatch.setattr("openopps.settings.available_cpu_count", lambda: 64)
    settings = OpenOppsSettings(concurrency_profile="auto")

    assert settings.concurrency_profile == "ci"
    assert settings.board_concurrency == 16
    assert settings.workday_concurrency == 2


def test_explicit_board_concurrency_wins_over_auto_profile(monkeypatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr("openopps.settings.available_cpu_count", lambda: 32)
    settings = OpenOppsSettings(concurrency_profile="auto", board_concurrency=9)

    assert settings.board_concurrency == 9
    assert settings.workday_concurrency == 2


def test_constrained_profile_does_not_raise_workday() -> None:
    settings = OpenOppsSettings(concurrency_profile="constrained")

    assert settings.source_concurrency == 2
    assert settings.board_concurrency == 4
    assert settings.provider_concurrency == 4
    assert settings.workday_concurrency == 2
    snapshot = settings.concurrency_snapshot()
    assert snapshot["workday"] == 2
    assert snapshot["profile"] == "constrained"


def test_discovery_per_host_cap_is_independent_of_concurrency_profile() -> None:
    from openopps.discovery.settings import DiscoverySettings

    discovery = DiscoverySettings()
    assert discovery.per_host_concurrency == 2
    ingest = OpenOppsSettings(concurrency_profile="auto")
    assert ingest.workday_concurrency == 2
    assert discovery.per_host_concurrency == 2

