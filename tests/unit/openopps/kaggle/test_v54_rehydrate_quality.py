"""Optional local checks against a v54-shaped public sqlite snapshot.

CI does not ship kaggle/openoppsdb.sqlite. Set OPENOPPS_V54_SQLITE or keep the
ignored local snapshot to run these assertions.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import openopps_kaggle.generator as gen  # ty: ignore[unresolved-import]

REPO_ROOT = Path(__file__).resolve().parents[4]


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


def _v54_sqlite() -> Path | None:
    override = os.environ.get("OPENOPPS_V54_SQLITE", "").strip()
    candidates = []
    if override:
        candidates.append(Path(override).expanduser())
    candidates.append(REPO_ROOT / "kaggle" / "openoppsdb.sqlite")
    for path in candidates:
        if path.is_file():
            return path
    return None


@pytest.fixture
def v54_sqlite() -> Path:
    path = _v54_sqlite()
    if path is None:
        pytest.skip("no local v54 openoppsdb.sqlite available")
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
