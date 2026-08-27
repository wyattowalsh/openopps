"""Naïve update-snapshot ledger helpers.

L.0/L.1 schema: header `update_snapshots` plus twelve `update_snapshot_*`
copies. Live operational tables do not gain `snapshot_id`. Payload CAS
(`JobPayloadSnapshotRow` / `job_payload_snapshots`) is copied, never reused
as the update-snapshot identity.

Staging clone sync (L.2) is out of scope here.
"""

from __future__ import annotations

from collections.abc import Mapping
import re
from uuid import uuid4

from sqlalchemy import Table
from sqlalchemy.engine import Connection, Engine
from sqlmodel import SQLModel

from openopps.models import (
    UPDATE_SNAPSHOT_COPY_MODELS,
    UpdateSnapshotBoardProviderRow,
    UpdateSnapshotBoardRow,
    UpdateSnapshotJobPayloadSnapshotRow,
    UpdateSnapshotJobRow,
    UpdateSnapshotJobSyncObservationRow,
    UpdateSnapshotJobSyncRunRow,
    UpdateSnapshotJobVersionBulletRow,
    UpdateSnapshotJobVersionLocationRow,
    UpdateSnapshotJobVersionRow,
    UpdateSnapshotJobVersionSkillKeywordRow,
    UpdateSnapshotJobVersionSkillRow,
    UpdateSnapshotRow,
    UpdateSnapshotSourceRow,
)
from openopps.utils import stable_id

UPDATE_SNAPSHOT_HEADER_TABLE = "update_snapshots"
UPDATE_SNAPSHOT_SCHEMA_REVISION = "0005_update_snapshot_ledger"
_CALENDAR_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SNAPSHOT_ID_PREFIX = "update-snapshot"

# Twelve operational tables copied per update. Do not add http_cache,
# alembic_version, or Kaggle bookkeeping tables to this tuple.
OPERATIONAL_COPY_TABLES: tuple[str, ...] = (
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
)

EXCLUDED_FROM_LEDGER_COPY: frozenset[str] = frozenset(
    {
        "http_cache",
        "http_cache_metadata",
        "alembic_version",
        "openopps_tables",
        "openopps_columns",
    }
)

HEADER_RETENTION_FORBIDDEN_COLUMNS: frozenset[str] = frozenset(
    {
        "expires_at",
        "ttl",
        "ttl_seconds",
        "prune_after",
        "pruned_at",
        "retention_days",
        "deleted_at",
    }
)

_COPY_MODELS_BY_OPERATIONAL_TABLE: dict[str, type[SQLModel]] = {
    "sources": UpdateSnapshotSourceRow,
    "boards": UpdateSnapshotBoardRow,
    "board_providers": UpdateSnapshotBoardProviderRow,
    "jobs": UpdateSnapshotJobRow,
    "job_versions": UpdateSnapshotJobVersionRow,
    "job_version_locations": UpdateSnapshotJobVersionLocationRow,
    "job_version_skills": UpdateSnapshotJobVersionSkillRow,
    "job_version_skill_keywords": UpdateSnapshotJobVersionSkillKeywordRow,
    "job_version_bullets": UpdateSnapshotJobVersionBulletRow,
    "job_payload_snapshots": UpdateSnapshotJobPayloadSnapshotRow,
    "job_sync_runs": UpdateSnapshotJobSyncRunRow,
    "job_sync_observations": UpdateSnapshotJobSyncObservationRow,
}

LEDGER_SQLITE_TABLES: frozenset[str] = frozenset(
    {UPDATE_SNAPSHOT_HEADER_TABLE}
    | {f"update_snapshot_{table}" for table in OPERATIONAL_COPY_TABLES}
)

LIVE_OPERATIONAL_TABLES: frozenset[str] = frozenset(OPERATIONAL_COPY_TABLES)


def mint_snapshot_id(*, nonce: str | None = None) -> str:
    """Return a cadence-neutral logical update identity.

    Identity is one update run, not a calendar day. Callers reuse the same
    id for bounded retries inside one update; they must not mint extra
    snapshots per attempt.
    """

    token = uuid4().hex if nonce is None else str(nonce).strip()
    if not token:
        raise ValueError("update snapshot nonce must be a non-empty string")
    snapshot_id = stable_id(_SNAPSHOT_ID_PREFIX, token)
    if is_calendar_day_identity(snapshot_id):
        raise ValueError(
            "update snapshot_id must be cadence-neutral, not a calendar day"
        )
    return snapshot_id


def is_calendar_day_identity(value: str) -> bool:
    """Return whether `value` is a YYYY-MM-DD calendar-day identity."""

    return bool(_CALENDAR_DAY_RE.fullmatch(value.strip()))


def copy_table_name(operational_table: str) -> str:
    """Return the naïve copy table name for an operational table."""

    _require_operational_copy_table(operational_table)
    return f"update_snapshot_{operational_table}"


def copy_model_for(operational_table: str) -> type[SQLModel]:
    """Return the SQLModel copy class for an operational table."""

    _require_operational_copy_table(operational_table)
    return _COPY_MODELS_BY_OPERATIONAL_TABLE[operational_table]


def sqlmodel_table(model: type[SQLModel]) -> Table:
    """Return the SQLAlchemy table mapped by a SQLModel table class."""

    table = getattr(model, "__table__", None)
    if not isinstance(table, Table):
        raise TypeError(f"{model.__name__} is not a mapped SQLModel table")
    return table


def operational_column_names(operational_table: str) -> tuple[str, ...]:
    """Return operational column names in table order (no snapshot_id)."""

    copy_model = copy_model_for(operational_table)
    names = tuple(
        column.name
        for column in sqlmodel_table(copy_model).columns
        if column.name != "snapshot_id"
    )
    if not names:
        raise ValueError(f"{operational_table} has no operational columns to copy")
    return names


def naive_copy_insert_sql(operational_table: str) -> str:
    """Return INSERT…SELECT SQL that copies one operational table into a snapshot.

    Parameter `:snapshot_id` is the cadence-neutral update identity. Original
    columns are listed explicitly so `SELECT *` cannot pull excluded tables or
    a live `snapshot_id` column (which must not exist).
    """

    copy_table = copy_table_name(operational_table)
    quoted = ", ".join(operational_column_names(operational_table))
    return (
        f"INSERT INTO {copy_table} (snapshot_id, {quoted}) "
        f"SELECT :snapshot_id, {quoted} FROM {operational_table}"
    )


def naive_copy_insert_sql_by_table() -> Mapping[str, str]:
    """Return copy INSERT SQL for every operational table in ledger order."""

    return {
        table: naive_copy_insert_sql(table) for table in OPERATIONAL_COPY_TABLES
    }


def empty_row_counts() -> dict[str, int]:
    """Return zeroed copied-row counts keyed by operational table name."""

    return {table: 0 for table in OPERATIONAL_COPY_TABLES}


def create_update_snapshot_ledger_tables(bind: Engine | Connection) -> None:
    """Create the header plus twelve naïve copies (L.1 draft helper)."""

    _header_table().create(bind, checkfirst=False)
    for model in UPDATE_SNAPSHOT_COPY_MODELS:
        sqlmodel_table(model).create(bind, checkfirst=False)


def drop_update_snapshot_ledger_tables(bind: Engine | Connection) -> None:
    """Drop naïve copies then the header (L.1 draft helper)."""

    for model in reversed(UPDATE_SNAPSHOT_COPY_MODELS):
        sqlmodel_table(model).drop(bind, checkfirst=False)
    _header_table().drop(bind, checkfirst=False)


def _header_table() -> Table:
    return sqlmodel_table(UpdateSnapshotRow)


def _require_operational_copy_table(operational_table: str) -> None:
    if operational_table in EXCLUDED_FROM_LEDGER_COPY:
        raise ValueError(
            f"{operational_table} is excluded from the naïve update-snapshot copy"
        )
    if operational_table not in _COPY_MODELS_BY_OPERATIONAL_TABLE:
        raise ValueError(
            f"{operational_table} is not one of the twelve operational copy tables"
        )
