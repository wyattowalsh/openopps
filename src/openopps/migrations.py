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
from alembic.script import ScriptDirectory
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
_UPDATE_SNAPSHOT_LEDGER_REVISION = "0005_update_snapshot_ledger"
_UPDATE_SNAPSHOT_HEADER_TABLE = "update_snapshots"
_UPDATE_SNAPSHOT_COPY_PREFIX = "update_snapshot_"
_EXPECTED_UPDATE_SNAPSHOT_HEADER_COLUMNS = (
    ("snapshot_id", "VARCHAR", False),
    ("captured_at", "DATETIME", False),
    ("appended_at", "DATETIME", False),
    ("collection_status", "VARCHAR", False),
    ("validation_ok", "BOOLEAN", False),
    ("attestation", "VARCHAR", False),
    ("run_digest", "VARCHAR", False),
    ("schema_revision", "VARCHAR", False),
    ("row_counts", "JSON", True),
)
_EXPECTED_UPDATE_SNAPSHOT_HEADER_INDEXES = {
    ("appended_at",),
    ("attestation",),
    ("captured_at",),
    ("collection_status",),
    ("run_digest",),
    ("schema_revision",),
    ("validation_ok",),
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
UPDATE_SNAPSHOT_LEDGER_TABLES: frozenset[str] = frozenset(
    {
        "update_snapshots",
        "update_snapshot_sources",
        "update_snapshot_boards",
        "update_snapshot_board_providers",
        "update_snapshot_jobs",
        "update_snapshot_job_versions",
        "update_snapshot_job_version_locations",
        "update_snapshot_job_version_skills",
        "update_snapshot_job_version_skill_keywords",
        "update_snapshot_job_version_bullets",
        "update_snapshot_job_payload_snapshots",
        "update_snapshot_job_sync_runs",
        "update_snapshot_job_sync_observations",
    }
)
_UPDATE_SNAPSHOT_COPY_TABLES_BY_LIVE_TABLE: dict[str, str] = {
    table_name.removeprefix(_UPDATE_SNAPSHOT_COPY_PREFIX): table_name
    for table_name in UPDATE_SNAPSHOT_LEDGER_TABLES
    if table_name != _UPDATE_SNAPSHOT_HEADER_TABLE
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
    *UPDATE_SNAPSHOT_LEDGER_TABLES,
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
        schema_issues: list[str] = []
        for table_name, column_names in REQUIRED_SQLITE_COLUMNS.items():
            if table_name not in table_names:
                schema_issues.extend(
                    f"{table_name}.{column}" for column in sorted(column_names)
                )
                continue
            existing_columns = {
                column["name"] for column in inspector.get_columns(table_name)
            }
            schema_issues.extend(
                f"{table_name}.{column}"
                for column in sorted(column_names - existing_columns)
            )
        schema_issues.extend(_missing_sqlite_unique_indexes(inspector))
        schema_issues.extend(_missing_sqlite_foreign_keys(inspector))
        schema_issues.extend(
            _update_snapshot_ledger_schema_issues(inspector, table_names)
        )
        if schema_issues:
            location = str(settings.sqlite_path or settings.db_url)
            raise DatabaseSchemaError(
                "does not match the OpenOpps v0.1.0 schema. "
                "Reset that local DB and rerun `openopps admin db init` "
                f"(path: {location}), or set OPENOPPS_DB_URL to a new SQLite file. "
                f"Schema mismatches: {', '.join(schema_issues)}. "
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
        _validate_existing_update_snapshot_ledger(settings, inspector, table_names)
    finally:
        engine.dispose()


def _validate_existing_update_snapshot_ledger(
    settings: OpenOppsSettings, inspector, table_names: set[str]
) -> None:
    current_revision = _current_alembic_revision(settings, inspector)
    observed_tables = _observed_update_snapshot_tables(table_names)
    if not _revision_includes_update_snapshot_ledger(settings, current_revision):
        if observed_tables:
            _raise_update_snapshot_ledger_error(
                settings,
                [
                    "unexpected pre-0005 table " + table_name
                    for table_name in sorted(observed_tables)
                ],
            )
        return

    issues = _update_snapshot_ledger_schema_issues(inspector, table_names)
    if issues:
        _raise_update_snapshot_ledger_error(settings, issues)


def _current_alembic_revision(settings: OpenOppsSettings, inspector) -> str:
    with inspector.bind.connect() as connection:
        revisions = [
            str(value)
            for value in connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalars()
        ]
    if len(revisions) != 1:
        location = str(settings.sqlite_path or settings.db_url)
        raise DatabaseSchemaError(
            "does not match the linear OpenOpps Alembic schema. "
            f"Expected one recorded revision at {location}; found {revisions!r}."
        )
    return revisions[0]


def _revision_includes_update_snapshot_ledger(
    settings: OpenOppsSettings, current_revision: str
) -> bool:
    script = ScriptDirectory.from_config(_alembic_config(settings))
    pending = [current_revision]
    visited: set[str] = set()
    while pending:
        revision_id = pending.pop()
        if revision_id in visited:
            continue
        visited.add(revision_id)
        if revision_id == _UPDATE_SNAPSHOT_LEDGER_REVISION:
            return True
        revision = script.get_revision(revision_id)
        if revision is None:
            return False
        down_revision = revision.down_revision
        if isinstance(down_revision, str):
            pending.append(down_revision)
        elif down_revision is not None:
            pending.extend(str(item) for item in down_revision)
    return False


def _observed_update_snapshot_tables(table_names: set[str]) -> set[str]:
    return {
        table_name
        for table_name in table_names
        if table_name == _UPDATE_SNAPSHOT_HEADER_TABLE
        or table_name.startswith(_UPDATE_SNAPSHOT_COPY_PREFIX)
    }


def _update_snapshot_ledger_schema_issues(
    inspector, table_names: set[str]
) -> list[str]:
    issues: list[str] = []
    observed_tables = _observed_update_snapshot_tables(table_names)
    issues.extend(
        f"missing table {table_name}"
        for table_name in sorted(UPDATE_SNAPSHOT_LEDGER_TABLES - observed_tables)
    )
    issues.extend(
        f"unexpected table {table_name}"
        for table_name in sorted(observed_tables - UPDATE_SNAPSHOT_LEDGER_TABLES)
    )

    if _UPDATE_SNAPSHOT_HEADER_TABLE in table_names:
        header_columns = _sqlite_column_signatures(
            inspector, _UPDATE_SNAPSHOT_HEADER_TABLE
        )
        if header_columns != _EXPECTED_UPDATE_SNAPSHOT_HEADER_COLUMNS:
            issues.append(f"{_UPDATE_SNAPSHOT_HEADER_TABLE}.columns")
        if _sqlite_primary_key(inspector, _UPDATE_SNAPSHOT_HEADER_TABLE) != (
            "snapshot_id",
        ):
            issues.append(f"{_UPDATE_SNAPSHOT_HEADER_TABLE}.primary_key")
        if _sqlite_foreign_keys(inspector, _UPDATE_SNAPSHOT_HEADER_TABLE):
            issues.append(f"{_UPDATE_SNAPSHOT_HEADER_TABLE}.foreign_keys")
        if _sqlite_unique_column_groups(inspector, _UPDATE_SNAPSHOT_HEADER_TABLE):
            issues.append(f"{_UPDATE_SNAPSHOT_HEADER_TABLE}.unique_constraints")
        if (
            _sqlite_nonunique_index_groups(inspector, _UPDATE_SNAPSHOT_HEADER_TABLE)
            != _EXPECTED_UPDATE_SNAPSHOT_HEADER_INDEXES
        ):
            issues.append(f"{_UPDATE_SNAPSHOT_HEADER_TABLE}.indexes")

    expected_snapshot_column = _EXPECTED_UPDATE_SNAPSHOT_HEADER_COLUMNS[0]
    expected_copy_foreign_keys = {
        (("snapshot_id",), _UPDATE_SNAPSHOT_HEADER_TABLE, ("snapshot_id",))
    }
    for live_table, copy_table in sorted(
        _UPDATE_SNAPSHOT_COPY_TABLES_BY_LIVE_TABLE.items()
    ):
        if live_table not in table_names:
            issues.append(f"missing live table {live_table}")
            continue
        if copy_table not in table_names:
            continue

        live_columns = _sqlite_column_signatures(inspector, live_table)
        copy_columns = _sqlite_column_signatures(inspector, copy_table)
        if not copy_columns or copy_columns[0] != expected_snapshot_column:
            issues.append(f"{copy_table}.snapshot_id")
        if set(copy_columns[1:]) != set(live_columns):
            issues.append(f"{copy_table}.columns")

        expected_primary_key = (
            "snapshot_id",
            *_sqlite_primary_key(inspector, live_table),
        )
        if _sqlite_primary_key(inspector, copy_table) != expected_primary_key:
            issues.append(f"{copy_table}.primary_key")
        if _sqlite_foreign_keys(inspector, copy_table) != expected_copy_foreign_keys:
            issues.append(f"{copy_table}.foreign_keys")

        expected_unique_groups = {
            ("snapshot_id", *columns)
            for columns in _sqlite_unique_column_groups(inspector, live_table)
        }
        if (
            _sqlite_unique_column_groups(inspector, copy_table)
            != expected_unique_groups
        ):
            issues.append(f"{copy_table}.unique_constraints")
        if _sqlite_nonunique_index_groups(
            inspector, copy_table
        ) != _sqlite_nonunique_index_groups(inspector, live_table):
            issues.append(f"{copy_table}.indexes")
    return issues


def _sqlite_column_signatures(
    inspector, table_name: str
) -> tuple[tuple[str, str, bool], ...]:
    return tuple(
        (
            str(column["name"]),
            str(column["type"]).upper(),
            bool(column["nullable"]),
        )
        for column in inspector.get_columns(table_name)
    )


def _sqlite_primary_key(inspector, table_name: str) -> tuple[str, ...]:
    columns = inspector.get_pk_constraint(table_name).get("constrained_columns") or []
    return tuple(str(column) for column in columns)


def _sqlite_foreign_keys(
    inspector, table_name: str
) -> set[tuple[tuple[str, ...], str, tuple[str, ...]]]:
    keys: set[tuple[tuple[str, ...], str, tuple[str, ...]]] = set()
    for item in inspector.get_foreign_keys(table_name):
        constrained = tuple(str(column) for column in item["constrained_columns"])
        referred_table = item.get("referred_table")
        referred = tuple(str(column) for column in item["referred_columns"])
        if referred_table:
            keys.add((constrained, str(referred_table), referred))
    return keys


def _sqlite_unique_column_groups(inspector, table_name: str) -> set[tuple[str, ...]]:
    groups = {
        tuple(str(column) for column in item["column_names"])
        for item in inspector.get_unique_constraints(table_name)
        if item.get("column_names")
    }
    groups.update(
        tuple(str(column) for column in item["column_names"])
        for item in inspector.get_indexes(table_name)
        if item.get("unique") and item.get("column_names")
    )
    return groups


def _sqlite_nonunique_index_groups(inspector, table_name: str) -> set[tuple[str, ...]]:
    return {
        tuple(str(column) for column in item["column_names"])
        for item in inspector.get_indexes(table_name)
        if not item.get("unique") and item.get("column_names")
    }


def _raise_update_snapshot_ledger_error(
    settings: OpenOppsSettings, issues: list[str]
) -> None:
    location = str(settings.sqlite_path or settings.db_url)
    raise DatabaseSchemaError(
        "does not match the OpenOpps update-snapshot ledger schema. "
        "Reset that local DB and rerun `openopps admin db init` "
        f"(path: {location}), or set OPENOPPS_DB_URL to a new SQLite file. "
        f"Schema mismatches: {', '.join(issues)}."
    )


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
