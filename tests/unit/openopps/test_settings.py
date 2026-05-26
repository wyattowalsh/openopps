from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from openopps.settings import OpenOppsSettings


def test_settings_schema_describes_every_config_field() -> None:
    schema = OpenOppsSettings.model_json_schema()

    for field_name in OpenOppsSettings.model_fields:
        field_schema = schema["properties"][field_name]
        description = field_schema.get("description", "")
        assert len(description) >= 40, field_name


def test_settings_rejects_non_url_database_value() -> None:
    with pytest.raises(ValidationError, match="SQLAlchemy-style URL"):
        OpenOppsSettings(db_url="openoppsdb.sqlite")


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
