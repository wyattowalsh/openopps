from __future__ import annotations

from collections.abc import Callable
from importlib import resources
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text

from openopps.settings import OpenOppsSettings


APP_TABLES = {"sources", "boards", "board_providers", "jobs"}
ALEMBIC_HEAD = "head"


def upgrade_sqlite_database(
    settings: OpenOppsSettings,
    *,
    prepare_legacy_schema: Callable[[Engine], None] | None = None,
) -> None:
    """Upgrade or stamp the durable OpenOpps SQLite app database."""

    if not settings.db_url.startswith("sqlite"):
        return
    if settings.sqlite_path:
        settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(settings.db_url, connect_args={"check_same_thread": False})
    try:
        if _has_app_schema(engine) and not _has_alembic_version(engine):
            if prepare_legacy_schema:
                prepare_legacy_schema(engine)
            command.stamp(_alembic_config(settings), ALEMBIC_HEAD)
            return
        command.upgrade(_alembic_config(settings), ALEMBIC_HEAD)
    finally:
        engine.dispose()


def migration_script_location() -> Path:
    """Return the Alembic script directory for diagnostics and docs."""

    return Path(str(resources.files("openopps").joinpath("alembic")))


def _alembic_config(settings: OpenOppsSettings) -> Config:
    config = Config()
    config.set_main_option("script_location", str(migration_script_location()))
    config.set_main_option("sqlalchemy.url", settings.db_url)
    config.attributes["openopps_explicit_url"] = True
    return config


def _has_app_schema(engine: Engine) -> bool:
    return bool(APP_TABLES & _sqlite_tables(engine))


def _has_alembic_version(engine: Engine) -> bool:
    return "alembic_version" in _sqlite_tables(engine)


def _sqlite_tables(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        ).fetchall()
    return {str(row[0]) for row in rows}
