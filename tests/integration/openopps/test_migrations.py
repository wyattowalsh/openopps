from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from openopps.migrations import DatabaseSchemaError
from openopps.settings import OpenOppsSettings
from openopps.storage import OpenOppsStore


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
    assert version == ("0001_initial_app_sqlite",)


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
    assert version == ("0001_initial_app_sqlite",)


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
