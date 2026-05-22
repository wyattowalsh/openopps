from __future__ import annotations

import sqlite3
from pathlib import Path

from openopps.settings import OpenOppsSettings
from openopps.storage import OpenOppsStore


def test_init_db_runs_alembic_for_fresh_sqlite(tmp_path: Path):
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

    assert {"sources", "boards", "board_providers", "jobs"}.issubset(tables)
    assert version == ("0001_initial_app_sqlite",)


def test_init_db_stamps_existing_unversioned_sqlite(tmp_path: Path):
    db_path = tmp_path / "openopps.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE sources (
                key TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                enabled BOOLEAN NOT NULL,
                version JSON,
                raw_metadata JSON,
                extra_payload JSON,
                synced_at DATETIME
            );
            CREATE TABLE boards (
                key TEXT PRIMARY KEY,
                source_key TEXT NOT NULL,
                remote_id TEXT NOT NULL,
                remote_slug TEXT,
                name TEXT NOT NULL
            );
            CREATE TABLE board_providers (
                id TEXT PRIMARY KEY,
                source_key TEXT NOT NULL,
                board_key TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                support_level TEXT NOT NULL
            );
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY,
                board_key TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                remote_id TEXT NOT NULL,
                title TEXT NOT NULL,
                locations JSON,
                department TEXT,
                team TEXT,
                workplace_type TEXT,
                posting_url TEXT,
                apply_url TEXT,
                posted_at TEXT,
                updated_at TEXT,
                status TEXT NOT NULL,
                raw_listing JSON,
                raw_detail JSON,
                extra_payload JSON,
                synced_at DATETIME NOT NULL
            );
            INSERT INTO sources (key, url, provider_id, enabled)
            VALUES ('a16z', 'https://a16z.com/jobs', 'consider', 1);
            INSERT INTO boards (key, source_key, remote_id, name)
            VALUES ('acme', 'a16z', 'acme', 'Acme');
            INSERT INTO board_providers (id, source_key, board_key, provider_id, support_level)
            VALUES ('a16z:acme:ashbyhq', 'a16z', 'acme', 'ashbyhq', 'jobs');
            INSERT INTO jobs (
                id, board_key, provider_id, remote_id, title, locations, status, synced_at
            ) VALUES (
                'acme:ashbyhq:1', 'acme', 'ashbyhq', '1', 'Engineer', '[]', 'open', '2026-01-01T00:00:00'
            );
            """
        )

    store = OpenOppsStore(OpenOppsSettings(db_url=f"sqlite:///{db_path}"))
    store.init_db()

    with sqlite3.connect(db_path) as conn:
        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        board_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(boards)").fetchall()
        }
        route_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(board_providers)").fetchall()
        }
        job_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
        }

    assert version == ("0001_initial_app_sqlite",)
    assert {"domain", "raw_payload", "extra_payload", "synced_at"}.issubset(
        board_columns
    )
    assert {"token", "raw_payload", "extra_payload", "detected_at"}.issubset(
        route_columns
    )
    assert "company" in job_columns
    assert "job_description" in job_columns
    assert store.list_boards()[0].providers[0].provider_id == "ashbyhq"
