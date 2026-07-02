from __future__ import annotations

import json
from pathlib import Path

import openopps_kaggle.generator as gen

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = REPO_ROOT / "scripts" / "openopps_kaggle" / "_core.py"


def _write_required_quality_files(
    output_dir: Path,
    *,
    current_jobs: int = 1,
    open_jobs: int = 1,
) -> None:
    sync_metrics = {
        "routesAttempted": 1,
        "routesSucceeded": 1,
        "routesFailed": 0,
        "jobsDiscovered": current_jobs,
        "jobsChanged": 0,
        "jobsClosed": 0,
        "providerErrors": [],
    }
    status = {
        "counts": {
            "currentJobs": current_jobs,
            "openJobs": open_jobs,
            "jobCapableRoutes": 1,
            "successfulJobSyncRuns": 1,
        }
    }
    coverage = {"providers": []}
    for name, payload in (
        (gen.SYNC_METRICS_FILE, sync_metrics),
        (gen.STATUS_FILE, status),
        (gen.COVERAGE_FILE, coverage),
    ):
        path = output_dir / name
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _notebook_setup_namespace(monkeypatch=None, *, output_dir: Path | None = None):
    import os
    import types

    if output_dir is not None:
        os.environ["OPENOPPS_KAGGLE_OUTPUT_DIR"] = str(output_dir)
    source = gen._notebook_setup_source()
    namespace: dict[str, object] = {}
    exec(source, namespace)
    return types.SimpleNamespace(**namespace)
