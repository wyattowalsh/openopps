from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlmodel import SQLModel, create_engine

from openopps.migrations import (
    MANAGED_SQLITE_TABLES,
    UPDATE_SNAPSHOT_LEDGER_TABLES,
    migration_script_location,
)
from openopps.models import (
    UPDATE_SNAPSHOT_COPY_MODELS,
    BoardProviderRow,
    BoardRow,
    JobPayloadSnapshotRow,
    JobRow,
    JobSyncObservationRow,
    JobSyncRunRow,
    JobVersionBulletRow,
    JobVersionLocationRow,
    JobVersionRow,
    JobVersionSkillKeywordRow,
    JobVersionSkillRow,
    SourceRow,
    UpdateSnapshotAttestation,
    UpdateSnapshotJobPayloadSnapshotRow,
    UpdateSnapshotRow,
)
from openopps.update_snapshot import (
    EXCLUDED_FROM_LEDGER_COPY,
    HEADER_RETENTION_FORBIDDEN_COLUMNS,
    LEDGER_SQLITE_TABLES,
    LIVE_OPERATIONAL_TABLES,
    OPERATIONAL_COPY_TABLES,
    UPDATE_SNAPSHOT_HEADER_TABLE,
    UPDATE_SNAPSHOT_SCHEMA_REVISION,
    copy_model_for,
    copy_table_name,
    create_update_snapshot_ledger_tables,
    drop_update_snapshot_ledger_tables,
    empty_row_counts,
    is_calendar_day_identity,
    mint_snapshot_id,
    naive_copy_insert_sql_by_table,
    operational_column_names,
    sqlmodel_table,
)

LIVE_ROW_MODELS: tuple[type[SQLModel], ...] = (
    SourceRow,
    BoardRow,
    BoardProviderRow,
    JobRow,
    JobVersionRow,
    JobVersionLocationRow,
    JobVersionSkillRow,
    JobVersionSkillKeywordRow,
    JobVersionBulletRow,
    JobPayloadSnapshotRow,
    JobSyncRunRow,
    JobSyncObservationRow,
)

_DRAFT_REVISION = "0005_update_snapshot_ledger.py.draft"


def test_mint_snapshot_id_is_cadence_neutral_and_stable_for_retries() -> None:
    snapshot_id = mint_snapshot_id(nonce="logical-update-run-1")
    retried = mint_snapshot_id(nonce="logical-update-run-1")

    assert snapshot_id == retried
    assert snapshot_id.startswith("update-snapshot:")
    assert not is_calendar_day_identity(snapshot_id)
    assert snapshot_id != "2026-08-22"
    assert mint_snapshot_id(nonce="2026-08-22") != "2026-08-22"
    assert not is_calendar_day_identity(mint_snapshot_id(nonce="2026-08-22"))


def test_mint_snapshot_id_without_nonce_is_unique_per_call() -> None:
    left = mint_snapshot_id()
    right = mint_snapshot_id()
    assert left != right
    assert not is_calendar_day_identity(left)
    assert not is_calendar_day_identity(right)


def test_mint_snapshot_id_rejects_empty_nonce() -> None:
    try:
        mint_snapshot_id(nonce="  ")
    except ValueError as exc:
        assert "non-empty" in str(exc)
    else:
        raise AssertionError("empty nonce must fail closed")


def test_calendar_day_identity_detects_iso_dates_only() -> None:
    assert is_calendar_day_identity("2026-08-22")
    assert not is_calendar_day_identity("update-snapshot:2026-08-22")
    assert not is_calendar_day_identity("2026-08-22T00:00:00Z")


def test_twelve_naive_copies_and_header_are_named_distinctly() -> None:
    assert len(OPERATIONAL_COPY_TABLES) == 12
    assert len(UPDATE_SNAPSHOT_COPY_MODELS) == 12
    assert len(LEDGER_SQLITE_TABLES) == 13
    assert UPDATE_SNAPSHOT_HEADER_TABLE == "update_snapshots"
    assert UpdateSnapshotRow.__tablename__ == "update_snapshots"
    assert UPDATE_SNAPSHOT_LEDGER_TABLES == LEDGER_SQLITE_TABLES
    copy_names = {model.__tablename__ for model in UPDATE_SNAPSHOT_COPY_MODELS}
    assert copy_names == {copy_table_name(table) for table in OPERATIONAL_COPY_TABLES}
    assert JobPayloadSnapshotRow.__tablename__ == "job_payload_snapshots"
    assert (
        UpdateSnapshotJobPayloadSnapshotRow.__tablename__
        == "update_snapshot_job_payload_snapshots"
    )
    assert UpdateSnapshotJobPayloadSnapshotRow is not JobPayloadSnapshotRow


def test_live_operational_tables_do_not_gain_snapshot_id() -> None:
    for model in LIVE_ROW_MODELS:
        assert "snapshot_id" not in model.model_fields
        assert "snapshot_id" not in sqlmodel_table(model).c
        assert model.__tablename__ in LIVE_OPERATIONAL_TABLES


def test_copy_tables_are_one_to_one_with_operational_columns() -> None:
    for operational_table, live_model in zip(
        OPERATIONAL_COPY_TABLES, LIVE_ROW_MODELS, strict=True
    ):
        copy_model = copy_model_for(operational_table)
        live_columns = tuple(column.name for column in sqlmodel_table(live_model).columns)
        copy_columns = tuple(
            column.name
            for column in sqlmodel_table(copy_model).columns
            if column.name != "snapshot_id"
        )
        assert copy_columns == live_columns
        assert operational_column_names(operational_table) == live_columns
        assert set(copy_model.model_fields) - {"snapshot_id"} == set(
            live_model.model_fields
        )
        primary_key = tuple(
            column.name for column in sqlmodel_table(copy_model).primary_key.columns
        )
        live_pk = tuple(
            column.name for column in sqlmodel_table(live_model).primary_key.columns
        )
        assert primary_key == ("snapshot_id", *live_pk)


def test_copy_foreign_keys_are_snapshot_header_only() -> None:
    for model in UPDATE_SNAPSHOT_COPY_MODELS:
        fks = {
            (fk.parent.name, fk.column.table.name, fk.column.name)
            for fk in sqlmodel_table(model).foreign_keys
        }
        assert fks == {("snapshot_id", "update_snapshots", "snapshot_id")}
        referred_tables = {fk.column.table.name for fk in sqlmodel_table(model).foreign_keys}
        assert referred_tables.isdisjoint(LIVE_OPERATIONAL_TABLES)


def _unique_column_groups(model: type[SQLModel]) -> set[tuple[str, ...]]:
    groups: set[tuple[str, ...]] = set()
    for constraint in sqlmodel_table(model).constraints:
        if constraint.__class__.__name__ != "UniqueConstraint":
            continue
        columns = getattr(constraint, "columns", None)
        if columns is None:
            continue
        names = tuple(columns.keys())
        if names:
            groups.add(names)
    return groups


def test_copy_unique_constraints_include_snapshot_id() -> None:
    for operational_table, live_model in zip(
        OPERATIONAL_COPY_TABLES, LIVE_ROW_MODELS, strict=True
    ):
        copy_model = copy_model_for(operational_table)
        live_uniques = _unique_column_groups(live_model)
        copy_uniques = _unique_column_groups(copy_model)
        expected = {("snapshot_id", *columns) for columns in live_uniques}
        assert copy_uniques == expected
        for columns in copy_uniques:
            assert columns[0] == "snapshot_id"


def test_header_has_no_retention_or_calendar_key() -> None:
    columns = set(sqlmodel_table(UpdateSnapshotRow).c.keys())
    assert columns.isdisjoint(HEADER_RETENTION_FORBIDDEN_COLUMNS)
    assert "calendar_date" not in columns
    assert "snapshot_day" not in columns
    assert UpdateSnapshotAttestation.COMPLETE == "complete"
    assert UpdateSnapshotAttestation.DEGRADED == "degraded"
    assert UpdateSnapshotAttestation.FAILED == "failed"
    assert UPDATE_SNAPSHOT_SCHEMA_REVISION == "0005_update_snapshot_ledger"
    assert set(empty_row_counts()) == set(OPERATIONAL_COPY_TABLES)


def test_excluded_bookkeeping_tables_are_never_copied() -> None:
    assert EXCLUDED_FROM_LEDGER_COPY.isdisjoint(LEDGER_SQLITE_TABLES)
    assert EXCLUDED_FROM_LEDGER_COPY.isdisjoint(LIVE_OPERATIONAL_TABLES)
    assert "openopps_tables" in MANAGED_SQLITE_TABLES
    assert "openopps_columns" in MANAGED_SQLITE_TABLES
    assert MANAGED_SQLITE_TABLES.isdisjoint(LEDGER_SQLITE_TABLES)
    for excluded in EXCLUDED_FROM_LEDGER_COPY:
        try:
            copy_table_name(excluded)
        except ValueError as exc:
            assert excluded in str(exc)
        else:
            raise AssertionError(f"{excluded} must not have a copy table")


def test_naive_copy_insert_sql_lists_original_columns_and_bind_snapshot_id() -> None:
    statements = naive_copy_insert_sql_by_table()
    assert tuple(statements) == OPERATIONAL_COPY_TABLES
    for operational_table, sql in statements.items():
        columns = ", ".join(operational_column_names(operational_table))
        copy_table = copy_table_name(operational_table)
        assert sql == (
            f"INSERT INTO {copy_table} (snapshot_id, {columns}) "
            f"SELECT :snapshot_id, {columns} FROM {operational_table}"
        )
        assert "http_cache" not in sql
        assert "alembic_version" not in sql
        assert "openopps_tables" not in sql
        assert "SELECT *" not in sql


def test_alembic_head_stays_0004_while_0005_is_a_g3_draft() -> None:
    config = Config()
    config.set_main_option("script_location", str(migration_script_location()))
    script = ScriptDirectory.from_config(config)
    assert script.get_current_head() == "0004_job_sync_run_lifecycle"
    assert "0005_update_snapshot_ledger" not in set(script.get_heads())
    draft = files("openopps").joinpath("alembic/versions") / _DRAFT_REVISION
    assert Path(str(draft)).is_file()
    text = Path(str(draft)).read_text(encoding="utf-8")
    assert "G3 BLOCKER" in text
    assert 'down_revision: str | None = "0004_job_sync_run_lifecycle"' in text
    assert "http_cache" in text
    assert (migration_script_location() / "versions" / "0005_update_snapshot_ledger.py").exists() is False


def test_draft_ledger_ddl_creates_header_and_twelve_copies_only() -> None:
    engine = create_engine("sqlite://")
    try:
        create_update_snapshot_ledger_tables(engine)
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert tables == LEDGER_SQLITE_TABLES
        assert tables.isdisjoint(LIVE_OPERATIONAL_TABLES)
        assert tables.isdisjoint(EXCLUDED_FROM_LEDGER_COPY)
        pk = inspector.get_pk_constraint("update_snapshot_jobs")
        assert pk["constrained_columns"] == ["snapshot_id", "id"]
        fks = inspector.get_foreign_keys("update_snapshot_jobs")
        assert len(fks) == 1
        assert fks[0]["constrained_columns"] == ["snapshot_id"]
        assert fks[0]["referred_table"] == "update_snapshots"
        live_job_columns = [column.name for column in sqlmodel_table(JobRow).columns]
        copied = [
            column["name"]
            for column in inspector.get_columns("update_snapshot_jobs")
            if column["name"] != "snapshot_id"
        ]
        assert copied == live_job_columns
        header_columns = {
            column["name"] for column in inspector.get_columns("update_snapshots")
        }
        assert header_columns.isdisjoint(HEADER_RETENTION_FORBIDDEN_COLUMNS)
        drop_update_snapshot_ledger_tables(engine)
        assert inspect(engine).get_table_names() == []
    finally:
        engine.dispose()
