"""Quality-gate checks against a deterministic v54-shaped SQLite snapshot.

An explicit ``OPENOPPS_V54_SQLITE`` override may exercise a captured snapshot,
but the default fixture must not select the mutable ignored current database.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

import openopps_kaggle.generator as gen  # ty: ignore[unresolved-import]

def _sync_metrics() -> dict[str, object]:
    return {
        "name": "sync",
        "jobsPersisted": 6,
        "jobSyncAttempts": 3,
        "jobSyncRuns": 3,
        "jobsDeduped": 0,
        "providerErrors": {},
        "providerErrorDetails": {},
    }


def _status() -> dict[str, object]:
    return {
        "database": {
            "counts": {
                "sources": 1,
                "boards": 2,
                "boardProviders": 4,
                "jobs": 6,
            }
        },
        "readiness": {"executableRoutes": 3},
    }


def _coverage() -> dict[str, object]:
    return {"routes": {"executable": 3}, "jobs": {"current": 6}}


def _v54_sqlite_override() -> Path | None:
    override = os.environ.get("OPENOPPS_V54_SQLITE", "").strip()
    if not override:
        return None
    path = Path(override).expanduser()
    if not path.is_file():
        pytest.fail(f"OPENOPPS_V54_SQLITE does not name a file: {path}")
    return path


def _write_v54_shaped_sqlite(path: Path) -> None:
    """Write the public table shape with the pre-lifecycle run columns."""

    with sqlite3.connect(path) as conn:
        for table in gen.TABLES:
            columns = [
                name
                for name in table.model.model_fields
                if not (table.name == "job_sync_runs" and name == "started_at")
            ]
            column_sql = ", ".join(f'"{column}" TEXT' for column in columns)
            conn.execute(f'CREATE TABLE "{table.name}" ({column_sql})')


@pytest.fixture
def v54_sqlite(tmp_path: Path) -> Path:
    path = _v54_sqlite_override()
    if path is None:
        path = tmp_path / "openoppsdb-v54.sqlite"
        _write_v54_shaped_sqlite(path)
    return path


def test_v54_public_sqlite_hits_lifecycle_column_quality_wall(
    v54_sqlite: Path,
    tmp_path: Path,
) -> None:
    report = gen.snapshot_quality_report(
        output_dir=tmp_path,
        db_path=v54_sqlite,
        sync_metrics=_sync_metrics(),
        status=_status(),
        coverage=_coverage(),
    )

    blockers = report["hardBlockers"]
    assert "missing_sqlite_column:job_sync_runs.started_at" in blockers
    assert "missing_job_version_skill_rows" not in blockers
    assert "missing_job_version_skill_keyword_rows" not in blockers
