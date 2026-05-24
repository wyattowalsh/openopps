from __future__ import annotations

from importlib import resources
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from openopps.settings import OpenOppsSettings


ALEMBIC_HEAD = "head"
REQUIRED_SQLITE_COLUMNS: dict[str, set[str]] = {
    "boards": {"source_keys", "source_board_keys"},
    "jobs": {"current_version_id", "current_content_hash", "last_seen_at"},
    "job_versions": {"job_id", "content_hash", "version"},
    "job_payload_snapshots": {"job_id", "payload_kind", "payload_hash"},
    "job_sync_runs": {"board_key", "provider_id", "synced_at"},
    "job_sync_observations": {"sync_run_id", "job_id", "observation_kind"},
}


class DatabaseSchemaError(RuntimeError):
    """Raised when a local SQLite file is stamped but not v0.1-schema compatible."""


def upgrade_sqlite_database(settings: OpenOppsSettings) -> None:
    """Create or upgrade the durable OpenOpps SQLite app database."""

    if not settings.db_url.startswith("sqlite"):
        return
    if settings.sqlite_path:
        settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    command.upgrade(_alembic_config(settings), ALEMBIC_HEAD)
    _validate_sqlite_schema(settings)


def migration_script_location() -> Path:
    """Return the Alembic script directory for diagnostics and docs."""

    return Path(str(resources.files("openopps").joinpath("alembic")))


def _alembic_config(settings: OpenOppsSettings) -> Config:
    config = Config()
    config.set_main_option("script_location", str(migration_script_location()))
    config.set_main_option("sqlalchemy.url", settings.db_url)
    config.attributes["openopps_explicit_url"] = True
    return config


def _validate_sqlite_schema(settings: OpenOppsSettings) -> None:
    connect_args = {"check_same_thread": False}
    engine = create_engine(settings.db_url, connect_args=connect_args)
    try:
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
        missing: list[str] = []
        for table_name, column_names in REQUIRED_SQLITE_COLUMNS.items():
            if table_name not in table_names:
                missing.extend(
                    f"{table_name}.{column}" for column in sorted(column_names)
                )
                continue
            existing_columns = {
                column["name"] for column in inspector.get_columns(table_name)
            }
            missing.extend(
                f"{table_name}.{column}"
                for column in sorted(column_names - existing_columns)
            )
        if missing:
            location = str(settings.sqlite_path or settings.db_url)
            raise DatabaseSchemaError(
                "does not match the OpenOpps v0.1.0 schema. "
                "Reset that local DB and rerun `openopps admin db init` "
                f"(path: {location}), or set OPENOPPS_DB_URL to a new SQLite file. "
                f"Missing columns: {', '.join(missing)}. "
                "This usually means a pre-release openopps.db was stamped before "
                "the v0.1 schema was finalized."
            )
    finally:
        engine.dispose()
