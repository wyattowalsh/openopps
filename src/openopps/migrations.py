from __future__ import annotations

from contextlib import contextmanager
import hashlib
from importlib import resources
from pathlib import Path
import tempfile
import threading
from collections.abc import Iterator
from typing import Protocol, cast

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event, inspect, text

from openopps.settings import OpenOppsSettings


class _FcntlModule(Protocol):
    LOCK_EX: int
    LOCK_UN: int

    def flock(self, fd: int, operation: int) -> None: ...


try:
    import fcntl as _fcntl_module
except ImportError:  # pragma: no cover - Windows fallback keeps process lock only.
    _fcntl: _FcntlModule | None = None
else:
    _fcntl = cast(_FcntlModule, _fcntl_module)


ALEMBIC_HEAD = "head"
_JOB_SYNC_RUN_LIFECYCLE_COLUMNS = {
    "started_at",
    "finished_at",
    "status",
    "error_kind",
    "authoritative",
    "committed_batch_count",
}
_SQLITE_UPGRADE_LOCKS_GUARD = threading.Lock()
_SQLITE_UPGRADE_LOCKS: dict[str, threading.Lock] = {}
REQUIRED_SQLITE_COLUMNS: dict[str, set[str]] = {
    "boards": {"source_keys", "source_board_keys"},
    "jobs": {"current_version_id", "current_content_hash", "last_seen_at"},
    "job_versions": {"job_id", "content_hash", "version"},
    "job_payload_snapshots": {"job_id", "payload_kind", "payload_hash"},
    "job_sync_runs": {
        "board_key",
        "provider_id",
        "synced_at",
    }
    | _JOB_SYNC_RUN_LIFECYCLE_COLUMNS,
    "job_sync_observations": {"sync_run_id", "job_id", "observation_kind"},
}
UNSUPPORTED_LEGACY_SQLITE_COLUMNS: dict[str, set[str]] = {
    "sources": {"enabled"},
}
EXPECTED_SQLITE_FOREIGN_KEYS: dict[str, set[tuple[str, str, str]]] = {
    "boards": {("source_key", "sources", "key")},
    "board_providers": {
        ("source_key", "sources", "key"),
        ("board_key", "boards", "key"),
    },
    "jobs": {
        ("board_key", "boards", "key"),
        ("current_version_id", "job_versions", "id"),
    },
    "job_versions": {("job_id", "jobs", "id")},
    "job_version_locations": {("job_version_id", "job_versions", "id")},
    "job_version_skills": {("job_version_id", "job_versions", "id")},
    "job_version_skill_keywords": {("skill_id", "job_version_skills", "id")},
    "job_version_bullets": {("job_version_id", "job_versions", "id")},
    "job_payload_snapshots": {("job_id", "jobs", "id")},
    "job_sync_runs": {("board_key", "boards", "key")},
    "job_sync_observations": {
        ("sync_run_id", "job_sync_runs", "id"),
        ("job_id", "jobs", "id"),
        ("job_version_id", "job_versions", "id"),
    },
}
EXPECTED_SQLITE_UNIQUE_INDEXES: dict[str, set[tuple[str, ...]]] = {
    "boards": {("source_key", "remote_id")},
    "board_providers": {("source_key", "board_key", "provider_id")},
    "jobs": {("board_key", "provider_id", "remote_id")},
    "job_versions": {("job_id", "content_hash"), ("job_id", "version")},
    "job_version_locations": {("job_version_id", "ordinal", "label")},
    "job_version_skills": {("job_version_id", "ordinal")},
    "job_version_skill_keywords": {("skill_id", "ordinal", "keyword")},
    "job_version_bullets": {("job_version_id", "kind", "ordinal", "text")},
    "job_payload_snapshots": {("job_id", "payload_kind", "payload_hash")},
}
MANAGED_SQLITE_TABLES: set[str] = {
    "sources",
    "boards",
    "board_providers",
    "jobs",
    "job_versions",
    "job_version_locations",
    "job_version_skills",
    "job_version_skill_keywords",
    "job_version_bullets",
    "job_payload_snapshots",
    "job_sync_runs",
    "job_sync_observations",
    "openopps_tables",
    "openopps_columns",
}


class DatabaseSchemaError(RuntimeError):
    """Raised when a local SQLite file is stamped but not v0.1-schema compatible."""


def upgrade_sqlite_database(settings: OpenOppsSettings) -> None:
    """Create or upgrade the durable OpenOpps SQLite app database."""

    if not settings.db_url.startswith("sqlite"):
        return
    if settings.sqlite_path:
        settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    with _sqlite_upgrade_lock(settings):
        _validate_existing_sqlite_columns(settings)
        command.upgrade(_alembic_config(settings), ALEMBIC_HEAD)
        _validate_sqlite_schema(settings)


def enable_sqlite_foreign_keys(engine: Engine) -> None:
    """Enable SQLite foreign-key enforcement for every new DB-API connection."""

    if engine.url.get_backend_name() != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


def migration_script_location() -> Path:
    """Return the Alembic script directory for diagnostics and docs."""

    return Path(str(resources.files("openopps").joinpath("alembic")))


def _alembic_config(settings: OpenOppsSettings) -> Config:
    config = Config()
    config.set_main_option("script_location", str(migration_script_location()))
    config.set_main_option("sqlalchemy.url", settings.db_url)
    config.attributes["openopps_explicit_url"] = True
    return config


@contextmanager
def sqlite_database_lock(path_or_url: Path | str) -> Iterator[None]:
    """Serialize first-use SQLite initialization across local processes."""

    lock_key = _sqlite_lock_key(path_or_url)
    process_lock = _process_upgrade_lock(lock_key)
    with process_lock:
        lock_path = _sqlite_lock_path(lock_key)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            if _fcntl is not None:
                _fcntl.flock(lock_file.fileno(), _fcntl.LOCK_EX)
            try:
                yield
            finally:
                if _fcntl is not None:
                    _fcntl.flock(lock_file.fileno(), _fcntl.LOCK_UN)


@contextmanager
def _sqlite_upgrade_lock(settings: OpenOppsSettings) -> Iterator[None]:
    if settings.sqlite_path is not None:
        with sqlite_database_lock(settings.sqlite_path):
            yield
        return
    with sqlite_database_lock(settings.db_url):
        yield


def _sqlite_lock_key(path_or_url: Path | str) -> str:
    if isinstance(path_or_url, Path):
        return str(path_or_url.expanduser().resolve(strict=False))
    return path_or_url


def _sqlite_lock_path(lock_key: str) -> Path:
    digest = hashlib.sha256(lock_key.encode("utf-8")).hexdigest()
    return Path(tempfile.gettempdir()) / "openopps-locks" / f"{digest}.init.lock"


def _process_upgrade_lock(lock_key: str) -> threading.Lock:
    with _SQLITE_UPGRADE_LOCKS_GUARD:
        lock = _SQLITE_UPGRADE_LOCKS.get(lock_key)
        if lock is None:
            lock = threading.Lock()
            _SQLITE_UPGRADE_LOCKS[lock_key] = lock
        return lock


def _validate_sqlite_schema(settings: OpenOppsSettings) -> None:
    connect_args = {"check_same_thread": False}
    engine = create_engine(settings.db_url, connect_args=connect_args)
    enable_sqlite_foreign_keys(engine)
    try:
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
        _validate_unsupported_legacy_sqlite_columns(settings, inspector, table_names)
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
        missing.extend(_missing_sqlite_unique_indexes(inspector))
        missing.extend(_missing_sqlite_foreign_keys(inspector))
        if missing:
            location = str(settings.sqlite_path or settings.db_url)
            raise DatabaseSchemaError(
                "does not match the OpenOpps v0.1.0 schema. "
                "Reset that local DB and rerun `openopps admin db init` "
                f"(path: {location}), or set OPENOPPS_DB_URL to a new SQLite file. "
                f"Missing columns: {', '.join(missing)}. "
                "This usually means a pre-release local SQLite database was stamped "
                "before the v0.1 schema was finalized."
            )
        with engine.connect() as connection:
            foreign_key_enabled = connection.execute(
                text("PRAGMA foreign_keys")
            ).scalar()
            if int(foreign_key_enabled or 0) != 1:
                raise DatabaseSchemaError("SQLite foreign key enforcement is disabled.")
            foreign_key_errors = connection.execute(
                text("PRAGMA foreign_key_check")
            ).all()
            if foreign_key_errors:
                location = str(settings.sqlite_path or settings.db_url)
                sample = ", ".join(str(tuple(row)) for row in foreign_key_errors[:5])
                raise DatabaseSchemaError(
                    "does not pass OpenOpps foreign key validation. "
                    f"Reset or repair that local DB (path: {location}). "
                    f"Foreign key errors: {sample}"
                )
    finally:
        engine.dispose()


def _validate_existing_sqlite_columns(settings: OpenOppsSettings) -> None:
    if settings.sqlite_path is not None and not settings.sqlite_path.exists():
        return
    connect_args = {"check_same_thread": False}
    engine = create_engine(settings.db_url, connect_args=connect_args)
    try:
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
        if "alembic_version" not in table_names:
            managed_tables = table_names & MANAGED_SQLITE_TABLES
            if managed_tables:
                _raise_unstamped_sqlite_database_error(settings, managed_tables)
            return
        _validate_unsupported_legacy_sqlite_columns(settings, inspector, table_names)
        _validate_required_sqlite_columns(settings, inspector, table_names)
    finally:
        engine.dispose()


def _raise_unstamped_sqlite_database_error(
    settings: OpenOppsSettings, table_names: set[str]
) -> None:
    location = str(settings.sqlite_path or settings.db_url)
    sample = ", ".join(sorted(table_names)[:8])
    if len(table_names) > 8:
        sample = f"{sample}, ..."
    raise DatabaseSchemaError(
        "does not match the OpenOpps v0.1.0 schema. "
        "Reset that local DB and rerun `openopps admin db init` "
        f"(path: {location}), or set OPENOPPS_DB_URL to a new SQLite file. "
        "Existing OpenOpps tables were found without Alembic schema metadata: "
        f"{sample}. "
        "If this is a public OpenOppsDB Kaggle snapshot, rehydrate it into a "
        "fresh operational database instead of running `admin db init` in place."
    )


def _validate_required_sqlite_columns(
    settings: OpenOppsSettings, inspector, table_names: set[str]
) -> None:
    missing: list[str] = []
    for table_name, column_names in REQUIRED_SQLITE_COLUMNS.items():
        if table_name not in table_names:
            missing.extend(f"{table_name}.{column}" for column in sorted(column_names))
            continue
        existing_columns = {
            column["name"] for column in inspector.get_columns(table_name)
        }
        missing.extend(
            f"{table_name}.{column}"
            for column in sorted(column_names - existing_columns)
        )
    if missing and _is_expected_pre_lifecycle_schema(inspector, missing):
        return
    if missing:
        location = str(settings.sqlite_path or settings.db_url)
        raise DatabaseSchemaError(
            "does not match the OpenOpps v0.1.0 schema. "
            "Reset that local DB and rerun `openopps admin db init` "
            f"(path: {location}), or set OPENOPPS_DB_URL to a new SQLite file. "
            f"Missing columns: {', '.join(missing)}. "
            "This usually means a pre-release local SQLite database was stamped "
            "before the v0.1 schema was finalized."
        )


def _is_expected_pre_lifecycle_schema(inspector, missing: list[str]) -> bool:
    expected_missing = {
        f"job_sync_runs.{column}" for column in _JOB_SYNC_RUN_LIFECYCLE_COLUMNS
    }
    # A genuine pre-0004 schema is missing the entire lifecycle column set.
    # A partial subset indicates a malformed/manual schema and must fail closed
    # before Alembic encounters duplicate or incompatible columns.
    if set(missing) != expected_missing:
        return False
    with inspector.bind.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version"))
        current = revision.scalar()
    return current in {
        "0001_initial_app_sqlite",
        "0002_data_model_integrity",
        "0003_jobs_current_version_fk",
    }


def _validate_unsupported_legacy_sqlite_columns(
    settings: OpenOppsSettings, inspector, table_names: set[str]
) -> None:
    legacy_columns: list[str] = []
    for table_name, column_names in UNSUPPORTED_LEGACY_SQLITE_COLUMNS.items():
        if table_name not in table_names:
            continue
        existing_columns = {
            column["name"] for column in inspector.get_columns(table_name)
        }
        legacy_columns.extend(
            f"{table_name}.{column}"
            for column in sorted(column_names & existing_columns)
        )
    if not legacy_columns:
        return

    location = str(settings.sqlite_path or settings.db_url)
    raise DatabaseSchemaError(
        "does not match the OpenOpps v0.1.0 schema. "
        "Reset that local DB and rerun `openopps admin db init` "
        f"(path: {location}), or set OPENOPPS_DB_URL to a new SQLite file. "
        f"Unsupported legacy columns: {', '.join(legacy_columns)}. "
        "Source enabled/disabled state is no longer supported; every persisted "
        "source is active by definition, and excluded sources should be removed "
        "instead of stored as disabled."
    )


def _missing_sqlite_unique_indexes(inspector) -> list[str]:
    missing: list[str] = []
    for table_name, expected_indexes in EXPECTED_SQLITE_UNIQUE_INDEXES.items():
        existing = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints(table_name)
            if item.get("column_names")
        }
        existing.update(
            tuple(item["column_names"])
            for item in inspector.get_indexes(table_name)
            if item.get("unique") and item.get("column_names")
        )
        for columns in sorted(expected_indexes):
            if columns not in existing:
                missing.append(f"{table_name}.unique({', '.join(columns)})")
    return missing


def _missing_sqlite_foreign_keys(inspector) -> list[str]:
    missing: list[str] = []
    for table_name, expected_keys in EXPECTED_SQLITE_FOREIGN_KEYS.items():
        existing = set()
        for item in inspector.get_foreign_keys(table_name):
            constrained = item.get("constrained_columns") or []
            referred = item.get("referred_columns") or []
            referred_table = item.get("referred_table")
            if len(constrained) == 1 and len(referred) == 1 and referred_table:
                existing.add((constrained[0], referred_table, referred[0]))
        for column_name, referred_table, referred_column in sorted(expected_keys):
            if (column_name, referred_table, referred_column) not in existing:
                missing.append(
                    f"{table_name}.{column_name}->{referred_table}.{referred_column}"
                )
    return missing
