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
from openopps.settings import OpenOppsSettings
from openopps.storage import OpenOppsStore

ALEMBIC_HEAD = "0002_data_model_integrity"


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

    assert {
        "sources",
        "boards",
        "board_providers",
        "jobs",
        "job_versions",
        "job_payload_snapshots",
        "job_sync_runs",
        "job_sync_observations",
    }.issubset(tables)
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
        assert _has_sqlite_index(
            conn, "job_version_skills", ("job_version_id", "ordinal"), unique=True
        )
        assert _has_sqlite_fk(conn, "boards", "source_key", "sources", "key")
        assert _has_sqlite_fk(conn, "board_providers", "board_key", "boards", "key")
        assert _has_sqlite_fk(conn, "job_versions", "job_id", "jobs", "id")
        assert _has_sqlite_fk(
            conn, "job_version_skill_keywords", "skill_id", "job_version_skills", "id"
        )
        assert _has_sqlite_fk(conn, "job_sync_observations", "job_id", "jobs", "id")
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
