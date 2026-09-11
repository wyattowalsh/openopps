from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from alembic import command

from openopps import migrations as migrations_module
from openopps.migrations import DatabaseSchemaError
from openopps.models import BoardRecord, JobRecord, SourceRecord
from openopps.settings import OpenOppsSettings
from openopps.storage import OpenOppsStore

ALEMBIC_HEAD = "0005_update_snapshot_ledger"
_LIVE_OPERATIONAL_TABLES: tuple[str, ...] = (
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
_EXPECTED_UPDATE_SNAPSHOT_LEDGER_TABLES: frozenset[str] = frozenset(
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


def test_init_db_runs_initial_sqlite_schema(tmp_path: Path):
    db_path = tmp_path / "openopps.db"
    store = OpenOppsStore(OpenOppsSettings(db_url=f"sqlite:///{db_path}"))

    store.init_db()

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()

    assert set(_LIVE_OPERATIONAL_TABLES) <= tables
    assert _EXPECTED_UPDATE_SNAPSHOT_LEDGER_TABLES <= tables
    assert version == (ALEMBIC_HEAD,)


def test_initial_sqlite_schema_has_app_constraints_and_indexes(tmp_path: Path):
    db_path = tmp_path / "openopps.db"
    store = OpenOppsStore(OpenOppsSettings(db_url=f"sqlite:///{db_path}"))

    store.init_db()

    with sqlite3.connect(db_path) as conn:
        assert _has_sqlite_index(
            conn, "boards", ("source_key", "remote_id"), unique=True
        )
        assert _has_sqlite_index(
            conn,
            "board_providers",
            ("source_key", "board_key", "provider_id"),
            unique=True,
        )
        assert _has_sqlite_index(
            conn, "jobs", ("board_key", "provider_id", "remote_id"), unique=True
        )
        assert _has_sqlite_index(
            conn, "job_versions", ("job_id", "content_hash"), unique=True
        )
        assert _has_sqlite_index(conn, "boards", ("source_key",))
        assert _has_sqlite_index(conn, "jobs", ("provider_id",))
        assert _has_sqlite_index(conn, "job_versions", ("job_id",))
        assert _has_sqlite_index(conn, "job_sync_runs", ("status",))
        assert _has_sqlite_index(conn, "job_sync_runs", ("started_at",))
        assert _has_sqlite_index(
            conn, "job_version_skills", ("job_version_id", "ordinal"), unique=True
        )
        assert _has_sqlite_fk(conn, "boards", "source_key", "sources", "key")
        assert _has_sqlite_fk(conn, "board_providers", "board_key", "boards", "key")
        assert _has_sqlite_fk(conn, "job_versions", "job_id", "jobs", "id")
        assert _has_sqlite_fk(conn, "jobs", "current_version_id", "job_versions", "id")
        assert _has_sqlite_fk(
            conn, "job_version_skill_keywords", "skill_id", "job_version_skills", "id"
        )
        assert _has_sqlite_fk(conn, "job_sync_observations", "job_id", "jobs", "id")
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_concurrent_first_use_initializes_sqlite_schema_once(tmp_path: Path):
    pytest.importorskip("fcntl")
    db_path = tmp_path / "openopps.db"
    script = """
import sys
from openopps.settings import OpenOppsSettings
from openopps.storage import OpenOppsStore

db_path = sys.argv[1]
store = OpenOppsStore(OpenOppsSettings(db_url=f"sqlite:///{db_path}"))
assert store.status() == {
    "sources": 0,
    "boards": 0,
    "boardProviders": 0,
    "jobs": 0,
}
"""
    env = {**os.environ, "PYTHONPATH": str(Path.cwd() / "src")}
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(db_path)],
            cwd=Path.cwd(),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(6)
    ]

    results = [process.communicate(timeout=30) for process in processes]

    failures = [
        (process.returncode, stdout, stderr)
        for process, (stdout, stderr) in zip(processes, results, strict=True)
        if process.returncode != 0
    ]
    assert failures == []
    with sqlite3.connect(db_path) as conn:
        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    assert version == (ALEMBIC_HEAD,)


def test_concurrent_first_use_serializes_app_and_cache_init(tmp_path: Path):
    pytest.importorskip("fcntl")
    db_path = tmp_path / "openopps.db"
    script = """
import sys
from openopps.cache import HttpCache
from openopps.settings import OpenOppsSettings
from openopps.storage import OpenOppsStore

db_path = sys.argv[1]
mode = sys.argv[2]
if mode == "cache":
    assert HttpCache(db_path).status()["total"] == 0
else:
    store = OpenOppsStore(OpenOppsSettings(db_url=f"sqlite:///{db_path}"))
    assert store.status() == {
        "sources": 0,
        "boards": 0,
        "boardProviders": 0,
        "jobs": 0,
    }
"""
    env = {**os.environ, "PYTHONPATH": str(Path.cwd() / "src")}
    modes = ["store", "cache", "store", "cache", "cache", "store", "cache", "store"]
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(db_path), mode],
            cwd=Path.cwd(),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for mode in modes
    ]

    results = [process.communicate(timeout=30) for process in processes]

    failures = [
        (process.returncode, stdout, stderr)
        for process, (stdout, stderr) in zip(processes, results, strict=True)
        if process.returncode != 0
    ]
    assert failures == []
    with sqlite3.connect(db_path) as conn:
        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert version == (ALEMBIC_HEAD,)
    assert "http_cache" in tables


def test_migration_nulls_observation_version_refs_after_version_cleanup(
    tmp_path: Path,
):
    db_path = tmp_path / "openopps.db"
    settings = OpenOppsSettings(db_url=f"sqlite:///{db_path}")
    command.upgrade(
        migrations_module._alembic_config(settings), "0001_initial_app_sqlite"
    )
    observed_at = "2026-01-01 00:00:00"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO sources (key, url, provider_id)
            VALUES ('source-1', 'https://example.com', 'manual')
            """
        )
        conn.execute(
            """
            INSERT INTO boards (key, source_key, remote_id, name)
            VALUES ('board-1', 'source-1', 'board-1', 'Board 1')
            """
        )
        conn.execute(
            """
            INSERT INTO jobs (
                id, board_key, provider_id, remote_id, status, current_version_id,
                current_content_hash, current_payload_hash, first_seen_at,
                last_seen_at, synced_at
            )
            VALUES (
                'job-keep', 'board-1', 'greenhouse', 'remote-1', 'open',
                'version-orphan', 'content-1', 'payload-1', ?, ?, ?
            )
            """,
            (observed_at, observed_at, observed_at),
        )
        conn.execute(
            """
            INSERT INTO job_versions (
                id, job_id, version, content_hash, payload_hash, title,
                first_seen_at, last_seen_at, created_at
            )
            VALUES (
                'version-orphan', 'missing-job', 1, 'content-1',
                'payload-1', 'Deleted version', ?, ?, ?
            )
            """,
            (observed_at, observed_at, observed_at),
        )
        conn.execute(
            """
            INSERT INTO job_sync_runs (
                id, board_key, provider_id, synced_at, success, job_count,
                new_count, unchanged_count, changed_count, reopened_count,
                closed_count
            )
            VALUES (
                'run-1', 'board-1', 'greenhouse', ?, 1, 1, 1, 0, 0, 0, 0
            )
            """,
            (observed_at,),
        )
        conn.execute(
            """
            INSERT INTO job_sync_observations (
                id, sync_run_id, job_id, job_version_id, observation_kind,
                content_hash, payload_hash, observed_at
            )
            VALUES (
                'observation-1', 'run-1', 'job-keep', 'version-orphan',
                'current', 'content-1', 'payload-1', ?
            )
            """,
            (observed_at,),
        )

    OpenOppsStore(settings).init_db()

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (
            ALEMBIC_HEAD,
        )
        assert (
            conn.execute(
                "SELECT job_version_id FROM job_sync_observations "
                "WHERE id = 'observation-1'"
            ).fetchone()[0]
            is None
        )
        assert (
            conn.execute(
                "SELECT current_version_id FROM jobs WHERE id = 'job-keep'"
            ).fetchone()[0]
            is None
        )
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migration_0003_nulls_orphan_job_current_version_refs(tmp_path: Path):
    db_path = tmp_path / "openopps.db"
    settings = OpenOppsSettings(db_url=f"sqlite:///{db_path}")
    command.upgrade(
        migrations_module._alembic_config(settings), "0002_data_model_integrity"
    )
    observed_at = "2026-01-01 00:00:00"
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            """
            INSERT INTO sources (key, url, provider_id)
            VALUES ('source-1', 'https://example.com', 'manual')
            """
        )
        conn.execute(
            """
            INSERT INTO boards (key, source_key, remote_id, name)
            VALUES ('board-1', 'source-1', 'board-1', 'Board 1')
            """
        )
        conn.execute(
            """
            INSERT INTO jobs (
                id, board_key, provider_id, remote_id, status, current_version_id,
                current_content_hash, current_payload_hash, first_seen_at,
                last_seen_at, synced_at
            )
            VALUES (
                'job-orphan-ref', 'board-1', 'greenhouse', 'remote-1', 'open',
                'missing-version', 'content-1', 'payload-1', ?, ?, ?
            )
            """,
            (observed_at, observed_at, observed_at),
        )

    OpenOppsStore(settings).init_db()

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (
            ALEMBIC_HEAD,
        )
        assert (
            conn.execute(
                "SELECT current_version_id FROM jobs WHERE id = 'job-orphan-ref'"
            ).fetchone()[0]
            is None
        )
        assert _has_sqlite_fk(conn, "jobs", "current_version_id", "job_versions", "id")


def test_migration_0004_upgrades_and_downgrades_sync_run_lifecycle(tmp_path: Path):
    db_path = tmp_path / "openopps.db"
    settings = OpenOppsSettings(db_url=f"sqlite:///{db_path}")
    command.upgrade(
        migrations_module._alembic_config(settings), "0003_jobs_current_version_fk"
    )
    observed_at = "2026-01-01 00:00:00"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO sources (key, url, provider_id)
            VALUES ('source-1', 'https://example.com', 'manual')
            """
        )
        conn.execute(
            """
            INSERT INTO boards (key, source_key, remote_id, name)
            VALUES ('board-1', 'source-1', 'board-1', 'Board 1')
            """
        )
        conn.execute(
            """
            INSERT INTO job_sync_runs (
                id, board_key, provider_id, synced_at, success, error, job_count,
                new_count, unchanged_count, changed_count, reopened_count,
                closed_count
            )
            VALUES (
                'run-legacy', 'board-1', 'greenhouse', ?, 0, 'legacy failure',
                0, 0, 0, 0, 0, 0
            )
            """,
            (observed_at,),
        )

    OpenOppsStore(settings).init_db()

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(job_sync_runs)")}
        upgraded = conn.execute(
            """
            SELECT status, started_at, finished_at, error_kind,
                   committed_batch_count, authoritative
            FROM job_sync_runs
            WHERE id = 'run-legacy'
            """
        ).fetchone()
    assert {
        "status",
        "started_at",
        "finished_at",
        "error_kind",
        "committed_batch_count",
        "authoritative",
    }.issubset(columns)
    assert upgraded == (
        "failed",
        observed_at,
        observed_at,
        "legacy_failure",
        0,
        0,
    )
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

    command.downgrade(
        migrations_module._alembic_config(settings), "0003_jobs_current_version_fk"
    )

    with sqlite3.connect(db_path) as conn:
        downgraded_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(job_sync_runs)")
        }
        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        legacy = conn.execute(
            "SELECT success, error FROM job_sync_runs WHERE id = 'run-legacy'"
        ).fetchone()
    assert "status" not in downgraded_columns
    assert version == ("0003_jobs_current_version_fk",)
    assert legacy == (0, "legacy failure")


def test_migration_0005_round_trips_ledger_without_live_schema_drift(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "openopps.db"
    settings = OpenOppsSettings(db_url=f"sqlite:///{db_path}")
    config = migrations_module._alembic_config(settings)
    command.upgrade(config, "0004_job_sync_run_lifecycle")

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0004_job_sync_run_lifecycle",
        )
        conn.execute(
            """
            INSERT INTO sources (key, url, provider_id)
            VALUES ('source-0005', 'https://example.com/jobs', 'manual')
            """
        )
        conn.execute(
            """
            INSERT INTO boards (key, source_key, remote_id, name)
            VALUES ('board-0005', 'source-0005', 'board-0005', 'Board 0005')
            """
        )
        baseline_tables = _sqlite_table_names(conn)
        baseline_live_schema = _live_schema_manifest(conn)
        expected_live_rows = _representative_live_rows(conn)

    command.upgrade(config, ALEMBIC_HEAD)

    with sqlite3.connect(db_path) as conn:
        _assert_0005_ledger_state(
            conn,
            baseline_tables=baseline_tables,
            baseline_live_schema=baseline_live_schema,
            expected_live_rows=expected_live_rows,
        )

    command.downgrade(config, "0004_job_sync_run_lifecycle")

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0004_job_sync_run_lifecycle",
        )
        assert _sqlite_table_names(conn) == baseline_tables
        assert _sqlite_table_names(conn).isdisjoint(
            _EXPECTED_UPDATE_SNAPSHOT_LEDGER_TABLES
        )
        assert _live_schema_manifest(conn) == baseline_live_schema
        assert _representative_live_rows(conn) == expected_live_rows
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

    command.upgrade(config, ALEMBIC_HEAD)

    with sqlite3.connect(db_path) as conn:
        _assert_0005_ledger_state(
            conn,
            baseline_tables=baseline_tables,
            baseline_live_schema=baseline_live_schema,
            expected_live_rows=expected_live_rows,
        )


def test_stamped_head_missing_ledger_table_fails_with_reset_guidance(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "openopps.db"
    settings = OpenOppsSettings(db_url=f"sqlite:///{db_path}")
    store = OpenOppsStore(settings)
    store.init_db()
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE update_snapshot_sources")

    with pytest.raises(DatabaseSchemaError, match="update_snapshot_sources"):
        OpenOppsStore(settings).init_db()


def test_migration_preflight_rejects_partial_ledger_before_0005(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "openopps.db"
    settings = OpenOppsSettings(db_url=f"sqlite:///{db_path}")
    command.upgrade(
        migrations_module._alembic_config(settings), "0004_job_sync_run_lifecycle"
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE update_snapshots (snapshot_id VARCHAR NOT NULL PRIMARY KEY)"
        )

    with pytest.raises(DatabaseSchemaError, match="update_snapshots"):
        OpenOppsStore(settings).init_db()


def test_migration_preflight_rejects_partial_lifecycle_schema(tmp_path: Path):
    db_path = tmp_path / "openopps.db"
    settings = OpenOppsSettings(db_url=f"sqlite:///{db_path}")
    command.upgrade(
        migrations_module._alembic_config(settings), "0003_jobs_current_version_fk"
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "ALTER TABLE job_sync_runs ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'"
        )

    with pytest.raises(
        DatabaseSchemaError, match=r"job_sync_runs\.(?:authoritative|started_at)"
    ):
        OpenOppsStore(settings).init_db()


def test_deleting_current_job_version_nulls_job_pointer(tmp_path: Path):
    store = OpenOppsStore(
        OpenOppsSettings(db_url=f"sqlite:///{tmp_path / 'openopps.db'}")
    )
    store.init_db()
    store.upsert_source(
        SourceRecord(key="source-1", url="https://example.com", provider_id="manual")
    )
    store.upsert_boards(
        [
            BoardRecord(
                key="board-1", source_key="source-1", remote_id="board-1", name="Board"
            )
        ]
    )
    store.upsert_jobs(
        [
            JobRecord.model_validate(
                {
                    "id": "board-1:greenhouse:1",
                    "board_key": "board-1",
                    "provider_id": "greenhouse",
                    "remote_id": "1",
                    "title": "Engineer",
                    "company": "Board",
                    "locations": ["Remote"],
                }
            )
        ]
    )
    db_path = tmp_path / "openopps.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        version_id = conn.execute(
            "SELECT current_version_id FROM jobs WHERE id = 'board-1:greenhouse:1'"
        ).fetchone()[0]
        assert version_id is not None
        conn.execute("DELETE FROM job_versions WHERE id = ?", (version_id,))
        assert (
            conn.execute(
                "SELECT current_version_id FROM jobs WHERE id = 'board-1:greenhouse:1'"
            ).fetchone()[0]
            is None
        )


def test_stamped_sqlite_db_missing_v01_columns_fails_with_reset_guidance(
    tmp_path: Path,
):
    db_path = tmp_path / "openopps.db"
    _create_stale_stamped_database(db_path)
    store = OpenOppsStore(OpenOppsSettings(db_url=f"sqlite:///{db_path}"))

    with pytest.raises(DatabaseSchemaError, match="Reset that local DB") as exc_info:
        store.init_db()

    message = str(exc_info.value)
    assert "boards.source_keys" in message
    assert "boards.source_board_keys" in message
    assert str(db_path) in message


def test_stamped_sqlite_db_with_legacy_source_enabled_column_fails(
    tmp_path: Path,
):
    db_path = tmp_path / "openopps.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.execute(f"INSERT INTO alembic_version VALUES ('{ALEMBIC_HEAD}')")
        conn.execute(
            """
            CREATE TABLE sources (
                key VARCHAR NOT NULL PRIMARY KEY,
                url VARCHAR NOT NULL,
                provider_id VARCHAR NOT NULL,
                enabled BOOLEAN NOT NULL
            )
            """
        )
    store = OpenOppsStore(OpenOppsSettings(db_url=f"sqlite:///{db_path}"))

    with pytest.raises(DatabaseSchemaError, match="Reset that local DB") as exc_info:
        store.init_db()

    message = str(exc_info.value)
    assert "Unsupported legacy columns: sources.enabled" in message
    assert "Source enabled/disabled state is no longer supported" in message
    assert "every persisted source is active" in message
    assert str(db_path) in message


def test_unstamped_sqlite_db_with_app_tables_fails_with_reset_guidance(
    tmp_path: Path,
):
    db_path = tmp_path / "openopps.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE sources (key VARCHAR NOT NULL PRIMARY KEY)")
    store = OpenOppsStore(OpenOppsSettings(db_url=f"sqlite:///{db_path}"))

    with pytest.raises(DatabaseSchemaError, match="Reset that local DB") as exc_info:
        store.init_db()

    message = str(exc_info.value)
    assert "without Alembic schema metadata" in message
    assert "public OpenOppsDB Kaggle snapshot" in message
    assert "sources" in message
    assert str(db_path) in message


def _sqlite_table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }


def _live_schema_manifest(
    conn: sqlite3.Connection,
) -> tuple[tuple[str, str, str, str | None], ...]:
    placeholders = ", ".join("?" for _ in _LIVE_OPERATIONAL_TABLES)
    rows = conn.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE type IN ('table', 'index', 'trigger') "
        f"AND tbl_name IN ({placeholders}) ORDER BY type, name",
        _LIVE_OPERATIONAL_TABLES,
    ).fetchall()
    return tuple((row[0], row[1], row[2], row[3]) for row in rows)


def _representative_live_rows(
    conn: sqlite3.Connection,
) -> tuple[tuple[object, ...] | None, tuple[object, ...] | None]:
    source = conn.execute(
        "SELECT key, url, provider_id FROM sources WHERE key = 'source-0005'"
    ).fetchone()
    board = conn.execute(
        "SELECT key, source_key, remote_id, name FROM boards WHERE key = 'board-0005'"
    ).fetchone()
    return source, board


def _assert_0005_ledger_state(
    conn: sqlite3.Connection,
    *,
    baseline_tables: set[str],
    baseline_live_schema: tuple[tuple[str, str, str, str | None], ...],
    expected_live_rows: tuple[tuple[object, ...] | None, tuple[object, ...] | None],
) -> None:
    tables = _sqlite_table_names(conn)
    assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (
        ALEMBIC_HEAD,
    )
    assert tables == baseline_tables | _EXPECTED_UPDATE_SNAPSHOT_LEDGER_TABLES
    assert tables - baseline_tables == _EXPECTED_UPDATE_SNAPSHOT_LEDGER_TABLES
    assert baseline_tables <= tables
    assert _live_schema_manifest(conn) == baseline_live_schema
    assert _representative_live_rows(conn) == expected_live_rows
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    _assert_frozen_ledger_schema(conn)


def _assert_frozen_ledger_schema(conn: sqlite3.Connection) -> None:
    observed = {
        table
        for table in _sqlite_table_names(conn)
        if table == "update_snapshots" or table.startswith("update_snapshot_")
    }
    assert observed == _EXPECTED_UPDATE_SNAPSHOT_LEDGER_TABLES
    for table_name in sorted(_EXPECTED_UPDATE_SNAPSHOT_LEDGER_TABLES):
        assert conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone() == (0,)

    assert _sqlite_column_signatures(conn, "update_snapshots") == (
        ("snapshot_id", "VARCHAR", 1, None),
        ("captured_at", "DATETIME", 1, None),
        ("appended_at", "DATETIME", 1, None),
        ("collection_status", "VARCHAR", 1, None),
        ("validation_ok", "BOOLEAN", 1, None),
        ("attestation", "VARCHAR", 1, None),
        ("run_digest", "VARCHAR", 1, None),
        ("schema_revision", "VARCHAR", 1, None),
        ("row_counts", "JSON", 0, None),
    )
    assert _sqlite_primary_key(conn, "update_snapshots") == ("snapshot_id",)
    assert _sqlite_foreign_keys(conn, "update_snapshots") == set()
    assert _sqlite_index_column_groups(conn, "update_snapshots", unique=False) == {
        ("appended_at",),
        ("attestation",),
        ("captured_at",),
        ("collection_status",),
        ("run_digest",),
        ("schema_revision",),
        ("validation_ok",),
    }
    assert _sqlite_index_column_groups(conn, "update_snapshots", unique=True) == set()

    for live_table in _LIVE_OPERATIONAL_TABLES:
        copy_table = f"update_snapshot_{live_table}"
        live_columns = _sqlite_column_signatures(conn, live_table)
        copy_columns = _sqlite_column_signatures(conn, copy_table)
        assert copy_columns[0] == ("snapshot_id", "VARCHAR", 1, None)
        assert {
            name: (column_type, required)
            for name, column_type, required, _default in copy_columns[1:]
        } == {
            name: (column_type, required)
            for name, column_type, required, _default in live_columns
        }
        assert _sqlite_primary_key(conn, copy_table) == (
            "snapshot_id",
            *_sqlite_primary_key(conn, live_table),
        )
        assert _sqlite_foreign_keys(conn, copy_table) == {
            ("snapshot_id", "update_snapshots", "snapshot_id")
        }
        live_uniques = _sqlite_index_column_groups(conn, live_table, unique=True)
        assert _sqlite_index_column_groups(conn, copy_table, unique=True) == {
            ("snapshot_id", *columns) for columns in live_uniques
        }
        assert _sqlite_index_column_groups(
            conn, copy_table, unique=False
        ) == _sqlite_index_column_groups(conn, live_table, unique=False)
        assert "snapshot_id" not in {
            column[0] for column in _sqlite_column_signatures(conn, live_table)
        }


def _sqlite_column_signatures(
    conn: sqlite3.Connection, table_name: str
) -> tuple[tuple[str, str, int, str | None], ...]:
    rows = conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
    return tuple((row[1], row[2], row[3], row[4]) for row in rows)


def _sqlite_primary_key(conn: sqlite3.Connection, table_name: str) -> tuple[str, ...]:
    rows = conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
    keyed = sorted((row[5], row[1]) for row in rows if row[5])
    return tuple(name for _, name in keyed)


def _sqlite_foreign_keys(
    conn: sqlite3.Connection, table_name: str
) -> set[tuple[str, str, str]]:
    rows = conn.execute(f'PRAGMA foreign_key_list("{table_name}")').fetchall()
    return {(row[3], row[2], row[4]) for row in rows}


def _sqlite_index_column_groups(
    conn: sqlite3.Connection, table_name: str, *, unique: bool
) -> set[tuple[str, ...]]:
    groups: set[tuple[str, ...]] = set()
    for row in conn.execute(f'PRAGMA index_list("{table_name}")').fetchall():
        if bool(row[2]) != unique or row[3] == "pk":
            continue
        columns = tuple(
            item[2]
            for item in conn.execute(f'PRAGMA index_info("{row[1]}")').fetchall()
        )
        if columns:
            groups.add(columns)
    return groups


def _has_sqlite_index(
    conn: sqlite3.Connection,
    table_name: str,
    columns: tuple[str, ...],
    *,
    unique: bool = False,
) -> bool:
    indexes = conn.execute(f"PRAGMA index_list({table_name})").fetchall()
    for index in indexes:
        if unique and not index[2]:
            continue
        indexed_columns = tuple(
            row[2] for row in conn.execute(f"PRAGMA index_info({index[1]})").fetchall()
        )
        if indexed_columns == columns:
            return True
    return False


def _has_sqlite_fk(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
    target_table: str,
    target_column: str,
) -> bool:
    rows = conn.execute(f"PRAGMA foreign_key_list({table_name})").fetchall()
    return any(
        row[3] == column_name and row[2] == target_table and row[4] == target_column
        for row in rows
    )


def _create_stale_stamped_database(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.execute("INSERT INTO alembic_version VALUES ('0001_initial_app_sqlite')")
        conn.execute(
            """
            CREATE TABLE boards (
                key VARCHAR NOT NULL PRIMARY KEY,
                source_key VARCHAR NOT NULL,
                remote_id VARCHAR NOT NULL,
                name VARCHAR NOT NULL
            )
            """
        )
