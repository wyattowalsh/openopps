from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from hashlib import sha1
import json
from pathlib import Path
from pprint import pformat
import re
import shutil
import sqlite3
import subprocess
import time
import types
from typing import Annotated, Any, Literal, Union, get_args, get_origin

import polars as pl
from pydantic import BaseModel, Field
from pydantic_core import PydanticUndefined

from openopps.models import (
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
    _SKILL_CATALOG,
    extract_job_skills,
)
from openopps.utils import slugify


@dataclass(frozen=True)
class Table:
    name: str
    model: type[BaseModel]
    description: str


@dataclass(frozen=True)
class Resource:
    name: str
    path: str
    description: str
    format: str
    mediatype: str
    model: type[BaseModel] | None = None
    tables: tuple[Table, ...] = ()


class OpenOppsTableRow(BaseModel):
    table_name: str = Field(description="SQLite table name.")
    table_title: str = Field(description="Human-readable table label.")
    table_description: str = Field(description="Plain-language table description.")
    csv_path: str = Field(description="CSV export path for this SQLite table.")
    parquet_path: str = Field(description="Parquet export path for this SQLite table.")


class OpenOppsColumnRow(BaseModel):
    table_name: str = Field(description="SQLite table that owns this column.")
    column_name: str = Field(description="SQLite column name.")
    column_title: str = Field(description="Human-readable column label.")
    column_description: str = Field(description="Plain-language column description.")
    logical_type: str = Field(description="Python or typing-level logical type label.")
    json_schema_type: str = Field(
        description="JSON Schema type derived from the model field."
    )
    required: bool = Field(
        description="Whether the source model marks the column as required."
    )
    source_name: str | None = Field(
        default=None,
        description="Original source alias when it differs from the column name.",
    )
    format: str | None = Field(
        default=None, description="JSON Schema format hint, when available."
    )
    enum_json: str | None = Field(
        default=None, description="JSON array of allowed values, when available."
    )
    examples_json: str | None = Field(
        default=None, description="JSON array of example values, when available."
    )
    default_json: str | None = Field(
        default=None, description="JSON-encoded default value, when available."
    )


DATASET_ID = "wyattowalsh/openoppsdb"
DATASET_LICENSE = "CC0-1.0"
DB_FILE = "openoppsdb.sqlite"
CSV_DIR = "exports/csv"
PARQUET_DIR = "exports/parquet"
SYNC_METRICS_FILE = "sync_metrics.json"
STATUS_FILE = "status.json"
COVERAGE_FILE = "coverage.json"
SNAPSHOT_QUALITY_FILE = "snapshot-quality.json"
SYNC_STDERR_FILE = "sync_stderr.txt"
DATAPACKAGE_FILE = "datapackage.json"
EXPOSED_DATAPACKAGE_FILE = "metadata/datapackage.json"
NB_FILE = "openoppsdb-manager.ipynb"
NB_ID = "wyattowalsh/openoppsdb-manager"
STARTER_NB_FILE = "openoppsdb-starter.ipynb"
STARTER_NB_ID = "wyattowalsh/openoppsdb-starter-notebook"
DATASET_IMAGE_FILE = "dataset-cover-image.png"
DATASET_IMAGE_SOURCE = Path("docs/public/social/openoppsdb.png")
DEFAULT_DATASET_DIR = Path(__file__).resolve().parents[1] / "kaggle"
DEFAULT_MANAGER_DIR = DEFAULT_DATASET_DIR
DEFAULT_STARTER_DIR = DEFAULT_DATASET_DIR / "starter"
GENERATOR_SCRIPT_URL = (
    "https://raw.githubusercontent.com/wyattowalsh/openopps/main/"
    "scripts/generate_kaggle_metadata.py"
)
DATASET_IMAGE_URL = (
    "https://raw.githubusercontent.com/wyattowalsh/openopps/main/"
    "docs/public/social/openoppsdb.png"
)
SQLITE_SIDECAR_SUFFIXES = ("-journal", "-shm", "-wal")
MAX_COLUMN_DESCRIPTION_LENGTH = 160
NOTEBOOK_SYNC_ENV_DEFAULTS: dict[str, str] = {
    "OPENOPPS_SOURCE_FRESHNESS_SECONDS": "86400",
    "OPENOPPS_SOURCE_CONCURRENCY": "40",
    "OPENOPPS_PROVIDER_CONCURRENCY": "80",
    "OPENOPPS_BOARD_CONCURRENCY": "80",
    "OPENOPPS_JOB_ROUTE_TIMEOUT_SECONDS": "180",
    "OPENOPPS_JOB_ROUTE_FRESHNESS_SECONDS": "86400",
    "OPENOPPS_MAX_CONNECTIONS": "120",
    "OPENOPPS_SOURCE_TIMEOUT_SECONDS": "120",
    "OPENOPPS_HTTP_TIMEOUT": "20",
    "OPENOPPS_RETRY_ATTEMPTS": "2",
}
NOTEBOOK_SYNC_TIMEOUT_SECONDS = 3300
NOTEBOOK_JOB_ROUTE_LIMIT = 120


DATA_TABLES: tuple[Table, ...] = (
    Table(
        name="sources",
        model=SourceRow,
        description="Durable source catalogs that discover company boards.",
    ),
    Table(
        name="boards",
        model=BoardRow,
        description="Durable normalized company or organization hiring boards.",
    ),
    Table(
        name="board_providers",
        model=BoardProviderRow,
        description="Durable provider routes that connect boards to upstream systems.",
    ),
    Table(
        name="jobs",
        model=JobRow,
        description="Stable job identities and lifecycle state.",
    ),
    Table(
        name="job_versions",
        model=JobVersionRow,
        description="Versioned normalized job content snapshots.",
    ),
    Table(
        name="job_version_locations",
        model=JobVersionLocationRow,
        description="Indexed location labels for each normalized job version.",
    ),
    Table(
        name="job_version_skills",
        model=JobVersionSkillRow,
        description="Indexed skill groups for each normalized job version.",
    ),
    Table(
        name="job_version_skill_keywords",
        model=JobVersionSkillKeywordRow,
        description="Indexed skill keywords for each normalized job version skill.",
    ),
    Table(
        name="job_version_bullets",
        model=JobVersionBulletRow,
        description="Indexed responsibility and qualification bullets for each job version.",
    ),
    Table(
        name="job_payload_snapshots",
        model=JobPayloadSnapshotRow,
        description="Raw upstream payload snapshots for audit and replay.",
    ),
    Table(
        name="job_sync_runs",
        model=JobSyncRunRow,
        description="Provider route sync attempts and aggregate change counts.",
    ),
    Table(
        name="job_sync_observations",
        model=JobSyncObservationRow,
        description="Per-job observations recorded during provider route syncs.",
    ),
)

METADATA_TABLES: tuple[Table, ...] = (
    Table(
        name="openopps_tables",
        model=OpenOppsTableRow,
        description="In-database table labels and descriptions for openoppsdb.sqlite.",
    ),
    Table(
        name="openopps_columns",
        model=OpenOppsColumnRow,
        description="In-database column labels, descriptions, and schema hints for openoppsdb.sqlite.",
    ),
)

TABLES: tuple[Table, ...] = DATA_TABLES + METADATA_TABLES


DATA_RESOURCES: tuple[Resource, ...] = (
    (
        Resource(
            name="openopps_database",
            path=DB_FILE,
            description=(
                "Full SQLite ledger with source, board, provider route, job lifecycle, "
                "version history, raw payload snapshot, sync observation, and in-DB "
                "table and column metadata tables. The SQLite upload nulls bulky "
                "text and JSON mirrors so Kaggle can index table previews; full "
                "rendered descriptions, structured job-description JSON, and raw "
                "payloads remain in the CSV and Parquet exports."
            ),
            format="sqlite",
            mediatype="application/vnd.sqlite3",
            tables=TABLES,
        ),
    )
    + tuple(
        Resource(
            name=f"{table.name}_csv",
            path=f"{CSV_DIR}/{table.name}.csv",
            description=f"Full CSV table export for {table.description}",
            format="csv",
            mediatype="text/csv",
            model=table.model,
        )
        for table in TABLES
    )
    + tuple(
        Resource(
            name=f"{table.name}_parquet",
            path=f"{PARQUET_DIR}/{table.name}.parquet",
            description=f"Full Parquet table export for {table.description}",
            format="parquet",
            mediatype="application/vnd.apache.parquet",
            model=table.model,
        )
        for table in TABLES
    )
)

EVIDENCE_RESOURCES: tuple[Resource, ...] = (
    Resource(
        name="sync_metrics",
        path=SYNC_METRICS_FILE,
        description=(
            "JSON metrics emitted by the unfiltered `openopps sync --metrics-json` "
            "manager run, including provider error summaries."
        ),
        format="json",
        mediatype="application/json",
    ),
    Resource(
        name="status",
        path=STATUS_FILE,
        description=(
            "JSON `openopps status --json` report captured after the manager sync, "
            "including persisted counts and route readiness evidence."
        ),
        format="json",
        mediatype="application/json",
    ),
    Resource(
        name="coverage",
        path=COVERAGE_FILE,
        description=(
            "JSON `openopps providers coverage --json` report captured from the "
            "persisted snapshot after syncing."
        ),
        format="json",
        mediatype="application/json",
    ),
    Resource(
        name="snapshot_quality",
        path=SNAPSHOT_QUALITY_FILE,
        description=(
            "Pre-publish quality gate report with pass/fail status, blockers, "
            "warnings, counts, required file checks, and provider error summaries."
        ),
        format="json",
        mediatype="application/json",
    ),
)

RESOURCES: tuple[Resource, ...] = DATA_RESOURCES
PRIVATE_EVIDENCE_FILES: tuple[str, ...] = (
    SYNC_METRICS_FILE,
    STATUS_FILE,
    COVERAGE_FILE,
    SNAPSHOT_QUALITY_FILE,
    SYNC_STDERR_FILE,
)
PRIVATE_METADATA_FILES: tuple[str, ...] = (
    DATAPACKAGE_FILE,
    EXPOSED_DATAPACKAGE_FILE,
)
PUBLIC_UPLOAD_CONTROL_FILES: tuple[str, ...] = (
    "dataset-metadata.json",
    DATASET_IMAGE_FILE,
)
PUBLIC_UPLOAD_DATA_FILES: tuple[str, ...] = (
    (DB_FILE,)
    + tuple(f"{CSV_DIR}/{table.name}.csv" for table in TABLES)
    + tuple(f"{PARQUET_DIR}/{table.name}.parquet" for table in TABLES)
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Kaggle dataset metadata from OpenOpps package models."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_DATASET_DIR,
        help="Directory to receive Kaggle dataset metadata and data artifacts.",
    )
    parser.add_argument(
        "--manager-dir",
        type=Path,
        default=DEFAULT_MANAGER_DIR,
        help="Directory to receive the connected Kaggle manager notebook.",
    )
    parser.add_argument(
        "--starter-dir",
        type=Path,
        default=DEFAULT_STARTER_DIR,
        help="Directory to receive the public Kaggle starter notebook.",
    )
    parser.add_argument(
        "--data-db",
        type=Path,
        default=None,
        help=f"Existing SQLite DB to copy as {DB_FILE} and export alongside tables.",
    )
    parser.add_argument(
        "--sync-metrics",
        type=Path,
        default=None,
        help="JSON metrics file from `openopps sync --metrics-json`.",
    )
    parser.add_argument(
        "--status-json",
        type=Path,
        default=None,
        help="JSON status file from `openopps status --json`.",
    )
    parser.add_argument(
        "--coverage-json",
        type=Path,
        default=None,
        help="JSON coverage file from `openopps providers coverage --json`.",
    )
    parser.add_argument(
        "--quality-report",
        type=Path,
        default=None,
        help=(
            f"Write {SNAPSHOT_QUALITY_FILE} and fail when the snapshot is not "
            "publishable."
        ),
    )
    parser.add_argument(
        "--prune-private-upload-files",
        action="store_true",
        help=(
            "Remove private manager evidence files from the upload directory "
            "after validation so the public dataset contains only SQLite, CSV, "
            "and Parquet data files."
        ),
    )
    parser.add_argument(
        "--stage-public-upload-dir",
        type=Path,
        default=None,
        help=(
            "Copy only Kaggle dataset control files plus public SQLite, CSV, "
            "and Parquet data artifacts into this temporary upload directory."
        ),
    )
    parser.add_argument(
        "--update-live-file-metadata",
        action="store_true",
        help=(
            "Update Kaggle's live per-file descriptions and column metadata "
            "from generated dataset-metadata.json. Requires the kaggle package "
            "and Kaggle API credentials."
        ),
    )
    parser.add_argument(
        "--live-file-metadata-browser-cookies",
        action="store_true",
        help=(
            "Also repair Kaggle's live databundle metadata checklist using "
            "the logged-in local Chrome session. Requires browser-cookie3 and "
            "is intended for local publish verification."
        ),
    )
    parser.add_argument(
        "--live-file-metadata-sqlite-timeout-seconds",
        type=float,
        default=1200.0,
        help=(
            "Seconds to wait for Kaggle's SQLite indexer to expose sqliteInfo "
            "when repairing live table metadata."
        ),
    )
    parser.add_argument(
        "--live-file-metadata-sqlite-poll-seconds",
        type=float,
        default=30.0,
        help="Polling interval for live SQLite indexer metadata repair.",
    )
    parser.add_argument(
        "--wait-live-dataset-ready",
        action="store_true",
        help=(
            "Wait until the live Kaggle dataset status is ready before running "
            "other requested live operations."
        ),
    )
    parser.add_argument(
        "--wait-live-dataset-min-version",
        type=int,
        default=None,
        help="Minimum live Kaggle dataset version required by --wait-live-dataset-ready.",
    )
    parser.add_argument(
        "--wait-live-dataset-timeout-seconds",
        type=float,
        default=1800.0,
        help="Seconds to wait for the live Kaggle dataset to become ready.",
    )
    parser.add_argument(
        "--wait-live-dataset-poll-seconds",
        type=float,
        default=30.0,
        help="Polling interval for --wait-live-dataset-ready.",
    )
    parser.add_argument(
        "--empty-snapshot-explanation",
        default=None,
        help=(
            "Documented first-run or upstream-outage explanation when a snapshot "
            "has no current jobs."
        ),
    )
    args = parser.parse_args()

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.data_db is not None:
        _write_data_artifacts(output_dir, args.data_db)
    _write_dataset_image(output_dir)
    _remove_dataset_notebooks(output_dir)
    if args.quality_report is None:
        _prune_private_upload_files(output_dir)

    _write_json(output_dir / "dataset-metadata.json", dataset_metadata())

    if args.quality_report is not None:
        if args.sync_metrics is None or args.status_json is None:
            parser.error("--quality-report requires --sync-metrics and --status-json")
        _write_snapshot_quality_report(
            output_dir=output_dir,
            db_path=output_dir / DB_FILE,
            report_path=args.quality_report,
            sync_metrics=_read_json(args.sync_metrics),
            status=_read_json(args.status_json),
            coverage=_read_json(args.coverage_json) if args.coverage_json else None,
            empty_snapshot_explanation=args.empty_snapshot_explanation,
        )
        if args.prune_private_upload_files:
            _prune_private_upload_files(output_dir)

    manager_dir: Path = args.manager_dir
    _write_manager_notebook(manager_dir)
    starter_dir: Path = args.starter_dir
    _write_starter_notebook(starter_dir)

    if args.stage_public_upload_dir is not None:
        _stage_public_upload_dir(output_dir, args.stage_public_upload_dir)
    if args.wait_live_dataset_ready:
        _wait_live_dataset_ready(
            DATASET_ID,
            min_version=args.wait_live_dataset_min_version,
            timeout_seconds=args.wait_live_dataset_timeout_seconds,
            poll_seconds=args.wait_live_dataset_poll_seconds,
        )
    if args.update_live_file_metadata:
        _update_live_file_metadata(
            output_dir / "dataset-metadata.json",
            use_browser_cookies=args.live_file_metadata_browser_cookies,
            sqlite_index_timeout_seconds=(
                args.live_file_metadata_sqlite_timeout_seconds
            ),
            sqlite_index_poll_seconds=args.live_file_metadata_sqlite_poll_seconds,
        )


def dataset_metadata() -> dict[str, Any]:
    return {
        "id": DATASET_ID,
        "title": "openoppsdb",
        "subtitle": "Daily SQLite, CSV, and Parquet public startup hiring-board ledger.",
        "description": _dataset_description(),
        "licenses": [{"name": DATASET_LICENSE}],
        "keywords": ["business", "internet", "software", "tabular"],
        "expectedUpdateFrequency": "daily",
        "userSpecifiedSources": (
            "Public company and startup hiring boards, public portfolio-company "
            "directories, and provider-hosted public job posting endpoints discovered "
            "by the OpenOpps CLI."
        ),
        "image": DATASET_IMAGE_FILE,
        "isPrivate": False,
        "resources": dataset_resources(),
    }


def _dataset_description() -> str:
    return """# OpenOppsDB

OpenOppsDB is a versioned public hiring-board ledger generated by the OpenOpps CLI. It tracks discovered company boards, executable provider routes, normalized job identities, versioned job content, raw provider payload snapshots, and sync observations over time.

## What is included

- `openoppsdb.sqlite`: the relational SQLite ledger, including metadata tables named `openopps_tables` and `openopps_columns`. To keep Kaggle table previews indexable, this SQLite copy nulls bulky text/JSON mirrors after export: `job_versions.description_html`, `job_versions.job_description`, and `job_payload_snapshots.payload`.
- `exports/csv/*.csv`: full table exports for spreadsheet and lightweight analysis workflows, including rendered HTML descriptions, structured job-description JSON, and raw payloads.
- `exports/parquet/*.parquet`: full table exports for Python, DuckDB, Polars, Spark, and warehouse workflows, including rendered HTML descriptions, structured job-description JSON, and raw payloads.

## How updates work

The connected Kaggle notebook `openoppsdb-manager` is intended to run once per day on a Kaggle cron schedule. Each run installs OpenOpps from GitHub, copies the current `openoppsdb.sqlite` from this dataset, runs `openopps sync --metrics-json`, captures private run evidence for the quality gate, exports every SQLite table to CSV and Parquet, regenerates Kaggle field metadata, prunes private manager evidence from the upload directory, and publishes a new dataset version only when the quality gate passes. The public file surface is intentionally limited to `openoppsdb.sqlite`, `exports/csv/*.csv`, and `exports/parquet/*.parquet`.

## Quick start

```python
import sqlite3
import polars as pl

conn = sqlite3.connect('/kaggle/input/openoppsdb/openoppsdb.sqlite')
jobs = pl.read_database('select * from jobs limit 10', conn)
versions = pl.read_parquet('/kaggle/input/openoppsdb/exports/parquet/job_versions.parquet')
```

## Notes and limitations

OpenOpps only uses public endpoints and public pages. Provider payloads are preserved for auditability, but normalized fields should be treated as best-effort public-data extraction rather than official ATS records. A row can appear across multiple source catalogs; durable keys and sync observation tables are provided so downstream users can reason about provenance and change history.
"""


def dataset_resources() -> list[dict[str, Any]]:
    return [_kaggle_resource_metadata(resource) for resource in RESOURCES]


def dataset_file_metadata(base_dir: Path | None = None) -> list[dict[str, Any]]:
    return [
        _kaggle_file_metadata(resource, base_dir=base_dir) for resource in RESOURCES
    ]


def kernel_metadata() -> dict[str, Any]:
    return {
        "id": NB_ID,
        "title": "openoppsdb manager",
        "code_file": NB_FILE,
        "language": "python",
        "kernel_type": "notebook",
        "is_private": True,
        "enable_gpu": False,
        "enable_tpu": False,
        "enable_internet": True,
        "keywords": [],
        "dataset_sources": [DATASET_ID],
        "competition_sources": [],
        "kernel_sources": [],
        "model_sources": [],
        "docker_image": "",
        "machine_shape": "None",
    }


def starter_kernel_metadata() -> dict[str, Any]:
    return {
        "id": STARTER_NB_ID,
        "title": "OpenOppsDB starter notebook",
        "code_file": STARTER_NB_FILE,
        "language": "python",
        "kernel_type": "notebook",
        "is_private": False,
        "enable_gpu": False,
        "enable_tpu": False,
        "enable_internet": False,
        "keywords": [],
        "dataset_sources": [DATASET_ID],
        "competition_sources": [],
        "kernel_sources": [],
        "model_sources": [],
        "docker_image": "",
        "machine_shape": "None",
    }


def notebook() -> dict[str, Any]:
    return {
        "cells": [
            _markdown_cell(
                "overview",
                "# openoppsdb manager\n\n"
                "This notebook is connected to `wyattowalsh/openoppsdb`. Schedule "
                "it with a daily Kaggle cron "
                "cadence such as `0 6 * * *`. Each run installs OpenOpps from "
                "GitHub, copies the newest `/kaggle/input/**/openoppsdb.sqlite` "
                "snapshot into `/kaggle/working/openoppsdb/openoppsdb.sqlite`, "
                "runs `openopps sync --metrics-json`, captures status and coverage "
                "evidence for the private quality gate, prepares SQLite/CSV/"
                "Parquet artifacts, writes in-database table and column "
                "metadata, prunes private evidence from the upload directory, "
                "and deploys a new dataset version only after the quality gate "
                "passes.",
            ),
            _code_cell("setup", _notebook_setup_source()),
            _code_cell("sync-openopps", _notebook_sync_source()),
            _code_cell("export-artifacts", _notebook_export_source()),
            _code_cell("publish-dataset", _notebook_publish_source()),
        ],
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {
                "codemirror_mode": {"name": "ipython", "version": 3},
                "file_extension": ".py",
                "mimetype": "text/x-python",
                "name": "python",
                "nbconvert_exporter": "python",
                "pygments_lexer": "ipython3",
                "version": "3.12",
            },
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def starter_notebook() -> dict[str, Any]:
    return {
        "cells": [
            _markdown_cell(
                "overview",
                "# OpenOppsDB starter notebook\n\n"
                "This public example reads the OpenOppsDB Kaggle dataset from "
                "the attached input files. It is read-only, does not need "
                "internet access, and does not use credentials.",
            ),
            _code_cell(
                "load",
                """from pathlib import Path
import sqlite3

import pandas as pd

db_candidates = sorted(Path("/kaggle/input").glob("**/openoppsdb.sqlite"))
if not db_candidates:
    raise FileNotFoundError("No openoppsdb.sqlite input found under /kaggle/input")
DB_PATH = db_candidates[0]
DATASET_DIR = DB_PATH.parent
print(f"Reading OpenOppsDB snapshot from {DB_PATH}")
DB_URI = f"file:{DB_PATH}?mode=ro&immutable=1"

with sqlite3.connect(DB_URI, uri=True) as conn:
    tables = pd.read_sql_query(
        "select table_name, table_title, table_description "
        "from openopps_tables order by table_name",
        conn,
    )
    counts = {
        table: conn.execute(f'select count(*) from "{table}"').fetchone()[0]
        for table in tables["table_name"].tolist()
    }
    recent_jobs = pd.read_sql_query(
        \"\"\"
        select
            job_id,
            title,
            company,
            locations,
            employment_type,
            first_seen_at,
            last_seen_at,
            posting_url
        from job_versions
        order by last_seen_at desc
        limit 20
        \"\"\",
        conn,
    )

summary = pd.DataFrame(
    {
        "metric": [
            "tables",
            "jobs",
            "job_versions",
            "job_sync_runs",
            "sources",
        ],
        "value": [
            counts["openopps_tables"],
            counts["jobs"],
            counts["job_versions"],
            counts["job_sync_runs"],
            counts["sources"],
        ],
    }
)
summary
""",
            ),
            _code_cell(
                "tables",
                """tables
""",
            ),
            _code_cell(
                "recent_jobs",
                """recent_jobs
""",
            ),
        ],
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {
                "codemirror_mode": {"name": "ipython", "version": 3},
                "file_extension": ".py",
                "mimetype": "text/x-python",
                "name": "python",
                "nbconvert_exporter": "python",
                "pygments_lexer": "ipython3",
                "version": "3.12",
            },
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def datapackage() -> dict[str, Any]:
    return {
        "profile": "data-package",
        "name": "openoppsdb",
        "title": "OpenOpps DB",
        "description": (
            "Package-derived Kaggle data dictionary for the full OpenOpps SQLite "
            "ledger and full table exports. Do not edit by hand; regenerate "
            "with scripts/generate_kaggle_metadata.py."
        ),
        "resources": [_resource_metadata(resource) for resource in RESOURCES],
    }


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_dataset_image(output_dir: Path) -> None:
    source = Path(__file__).resolve().parents[1] / DATASET_IMAGE_SOURCE
    target = output_dir / DATASET_IMAGE_FILE
    if not source.exists():
        if target.exists():
            return
        raise FileNotFoundError(f"Kaggle dataset image does not exist: {source}")
    shutil.copy2(source, target)


def _write_manager_notebook(manager_dir: Path) -> None:
    manager_dir.mkdir(parents=True, exist_ok=True)
    _clean_notebooks(manager_dir)
    _write_json(manager_dir / "kernel-metadata.json", kernel_metadata())
    _write_json(manager_dir / NB_FILE, notebook())


def _write_starter_notebook(starter_dir: Path) -> None:
    starter_dir.mkdir(parents=True, exist_ok=True)
    for path in starter_dir.glob("*.ipynb"):
        if path.name != STARTER_NB_FILE:
            path.unlink()
    _write_json(starter_dir / "kernel-metadata.json", starter_kernel_metadata())
    _write_json(starter_dir / STARTER_NB_FILE, starter_notebook())


def _remove_dataset_notebooks(output_dir: Path) -> None:
    notebooks_dir = output_dir / "notebooks"
    if notebooks_dir.exists():
        shutil.rmtree(notebooks_dir)
    ds_store = output_dir / ".DS_Store"
    if ds_store.exists():
        ds_store.unlink()


def _write_data_artifacts(output_dir: Path, data_db: Path) -> None:
    source_db = data_db.expanduser().resolve()
    if not source_db.exists():
        raise FileNotFoundError(f"SQLite database does not exist: {source_db}")
    target_db = output_dir / DB_FILE
    build_db = output_dir / f".{DB_FILE}.build"
    _remove_sqlite_sidecars(build_db)
    if build_db.exists():
        build_db.unlink()
    _clean_data_artifacts(output_dir, preserve=source_db)
    _checkpoint_sqlite(source_db)
    shutil.copy2(source_db, build_db)
    try:
        _drop_cache_tables(build_db)
        _backfill_sqlite_skill_tables(build_db)
        _write_sqlite_metadata(build_db)
        _checkpoint_sqlite(build_db)

        _write_full_table_exports(output_dir, build_db)
        _project_sqlite_for_kaggle_indexer(build_db)
        _normalize_sqlite_schema_for_kaggle_indexer(build_db)
        _finalize_sqlite_for_upload(build_db)
        build_db.replace(target_db)
    finally:
        _remove_sqlite_sidecars(build_db)
        if build_db.exists():
            build_db.unlink()
    if source_db.parent == output_dir.resolve() and source_db != target_db.resolve():
        source_db.unlink()
        _remove_sqlite_sidecars(source_db)


def _clean_data_artifacts(output_dir: Path, *, preserve: Path) -> None:
    preserve = preserve.resolve()
    for pattern in ("*.csv", "*.db", "*.db-*", "*.sqlite", "*.sqlite-*"):
        for path in output_dir.glob(pattern):
            if path.is_file() and path.resolve() != preserve:
                path.unlink()
    exports_dir = output_dir / "exports"
    if exports_dir.exists():
        shutil.rmtree(exports_dir)
    for path in output_dir.glob("*.whl"):
        if path.is_file():
            path.unlink()


def _clean_notebooks(notebooks_dir: Path) -> None:
    for path in notebooks_dir.glob("*.ipynb"):
        if path.name != NB_FILE:
            path.unlink()


def _write_full_table_exports(output_dir: Path, db_path: Path) -> None:
    csv_dir = output_dir / CSV_DIR
    parquet_dir = output_dir / PARQUET_DIR
    csv_dir.mkdir(parents=True, exist_ok=True)
    parquet_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        for table in TABLES:
            csv_path = csv_dir / f"{table.name}.csv"
            parquet_path = parquet_dir / f"{table.name}.parquet"
            print(f"Exporting {table.name}...", flush=True)
            _write_table_csv(conn, table, csv_path)
            pl.scan_csv(
                csv_path,
                infer_schema_length=1000,
                low_memory=True,
            ).sink_parquet(parquet_path)


def _project_sqlite_for_kaggle_indexer(db_path: Path) -> dict[str, int]:
    """Trim upload-only SQLite mirrors that prevent Kaggle from indexing tables."""
    projection_columns = (
        ("job_versions", "description_html"),
        ("job_versions", "job_description"),
        ("job_payload_snapshots", "payload"),
    )
    total_rows = 0
    total_bytes = 0
    nulled_columns = []
    with sqlite3.connect(db_path) as conn:
        for table_name, column_name in projection_columns:
            row = conn.execute(
                f"""
                SELECT COUNT(*), COALESCE(SUM(length(CAST("{column_name}" AS blob))), 0)
                FROM "{table_name}"
                WHERE "{column_name}" IS NOT NULL
                """
            ).fetchone()
            rows = int(row[0] or 0)
            bytes_removed = int(row[1] or 0)
            if rows:
                conn.execute(
                    f'UPDATE "{table_name}" SET "{column_name}" = NULL '
                    f'WHERE "{column_name}" IS NOT NULL'
                )
                nulled_columns.append(f"{table_name}.{column_name}")
                total_rows += rows
                total_bytes += bytes_removed
        conn.commit()
    if nulled_columns:
        print(
            "Prepared SQLite upload projection for Kaggle indexer: "
            + json.dumps(
                {
                    "nulledColumns": nulled_columns,
                    "rows": total_rows,
                    "estimatedBytesRemoved": total_bytes,
                },
                sort_keys=True,
            ),
            flush=True,
        )
    return {"projected_rows": total_rows, "estimated_bytes_removed": total_bytes}


def _normalize_sqlite_schema_for_kaggle_indexer(db_path: Path) -> int:
    replacements = (
        (re.compile(r"\bVARCHAR(?:\(\d+\))?\b"), "TEXT"),
        (re.compile(r"\bJSON\b"), "TEXT"),
        (re.compile(r"\bDATETIME\b"), "TEXT"),
        (re.compile(r"\bBOOLEAN\b"), "INTEGER"),
        (re.compile(r"\bFLOAT\b"), "REAL"),
    )
    updated = 0
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT rowid, sql FROM sqlite_schema WHERE type = 'table' AND sql IS NOT NULL"
        ).fetchall()
        conn.execute("PRAGMA writable_schema = ON")
        try:
            for rowid, sql in rows:
                normalized = str(sql)
                for pattern, replacement in replacements:
                    normalized = pattern.sub(replacement, normalized)
                if normalized != sql:
                    conn.execute(
                        "UPDATE sqlite_schema SET sql = ? WHERE rowid = ?",
                        (normalized, rowid),
                    )
                    updated += 1
            if updated:
                schema_version = int(conn.execute("PRAGMA schema_version").fetchone()[0])
                conn.execute(f"PRAGMA schema_version = {schema_version + 1}")
        finally:
            conn.execute("PRAGMA writable_schema = OFF")
        conn.commit()
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
    if integrity.lower() != "ok":
        raise RuntimeError(
            f"SQLite schema normalization failed integrity_check: {integrity}"
        )
    if updated:
        print(
            "Normalized SQLite upload schema for Kaggle indexer: "
            + json.dumps({"tables": updated}, sort_keys=True),
            flush=True,
        )
    return updated


def _write_table_csv(conn: sqlite3.Connection, table: Table, csv_path: Path) -> None:
    cursor = conn.execute(f'SELECT * FROM "{table.name}"')
    headers = (
        [column[0] for column in cursor.description]
        if cursor.description
        else list(table.model.model_fields)
    )
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(headers)
        while rows := cursor.fetchmany(10_000):
            writer.writerows(rows)


def _table_export_frame(table: Table, rows: list[dict[str, object]]) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame({field: [] for field in table.model.model_fields})
    return pl.DataFrame(rows, infer_schema_length=None)


def _backfill_sqlite_skill_tables(db_path: Path) -> dict[str, int]:
    """Populate deterministic skill child rows for ledgers created before skills."""

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA temp_store = MEMORY")
        table_names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        required_tables = {
            "jobs",
            "job_versions",
            "job_version_skills",
            "job_version_skill_keywords",
        }
        if not required_tables <= table_names:
            return {
                "versionsExamined": 0,
                "versionsBackfilled": 0,
                "skillsInserted": 0,
                "skillKeywordsInserted": 0,
            }

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_job_version_skills_job_version_id
            ON job_version_skills (job_version_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_job_version_skill_keywords_skill_id
            ON job_version_skill_keywords (skill_id)
            """
        )
        versions_examined = 0
        versions_backfilled = 0
        skills_inserted = 0
        keywords_inserted = 0
        last_rowid = 0
        chunk_size = 2000
        while True:
            rows = conn.execute(
                """
                SELECT
                    v.rowid AS _rowid,
                    v.id,
                    v.title,
                    v.department,
                    v.team,
                    v.employment_type,
                    v.description,
                    v.description_html,
                    v.experience,
                    v.responsibilities,
                    v.qualifications,
                    v.skills
                FROM job_versions AS v
                WHERE v.rowid > ?
                  AND (
                    NOT EXISTS (
                        SELECT 1
                        FROM job_version_skills AS s
                        WHERE s.job_version_id = v.id
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM job_version_skills AS s
                        WHERE s.job_version_id = v.id
                          AND NOT EXISTS (
                            SELECT 1
                            FROM job_version_skill_keywords AS k
                            WHERE k.skill_id = s.id
                          )
                    )
                  )
                ORDER BY v.rowid
                LIMIT ?
                """,
                (last_rowid, chunk_size),
            ).fetchall()
            if not rows:
                break
            last_rowid = int(rows[-1]["_rowid"])
            version_ids = [(row["id"],) for row in rows]
            conn.executemany(
                """
                DELETE FROM job_version_skill_keywords
                WHERE skill_id IN (
                    SELECT id
                    FROM job_version_skills
                    WHERE job_version_id = ?
                )
                """,
                version_ids,
            )
            conn.executemany(
                "DELETE FROM job_version_skills WHERE job_version_id = ?",
                version_ids,
            )
            version_updates: list[tuple[str, str]] = []
            skill_rows: list[tuple[str, str, int, str | None, str | None]] = []
            keyword_rows: list[tuple[str, str, int, str]] = []
            for row in rows:
                versions_examined += 1
                skills = _extract_version_skills(row)
                if not skills:
                    continue

                version_slug = slugify(str(row["id"]))
                if not _json_list(row["skills"]):
                    version_updates.append(
                        (
                            json.dumps(
                                skills,
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                            row["id"],
                        )
                    )
                for ordinal, skill in enumerate(skills):
                    skill_id = _stable_id_from_slugs(
                        version_slug,
                        "skill",
                        str(ordinal),
                    )
                    skill_slug = slugify(skill_id)
                    skill_rows.append(
                        (
                            skill_id,
                            row["id"],
                            ordinal,
                            _string_or_none(skill.get("name")),
                            _string_or_none(skill.get("level")),
                        )
                    )
                    for keyword_ordinal, keyword in enumerate(
                        skill.get("keywords") or []
                    ):
                        keyword_text = str(keyword)
                        keyword_rows.append(
                            (
                                _stable_id_from_slugs(
                                    skill_slug,
                                    "keyword",
                                    str(keyword_ordinal),
                                    _cached_slug(keyword_text),
                                ),
                                skill_id,
                                keyword_ordinal,
                                keyword_text,
                            )
                        )
                versions_backfilled += 1
            if version_updates:
                conn.executemany(
                    "UPDATE job_versions SET skills = ? WHERE id = ?",
                    version_updates,
                )
            if skill_rows:
                cursor = conn.executemany(
                    """
                    INSERT INTO job_version_skills (
                        id,
                        job_version_id,
                        ordinal,
                        name,
                        level
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    skill_rows,
                )
                if cursor.rowcount and cursor.rowcount > 0:
                    skills_inserted += cursor.rowcount
            if keyword_rows:
                cursor = conn.executemany(
                    """
                    INSERT INTO job_version_skill_keywords (
                        id,
                        skill_id,
                        ordinal,
                        keyword
                    ) VALUES (?, ?, ?, ?)
                    """,
                    keyword_rows,
                )
                if cursor.rowcount and cursor.rowcount > 0:
                    keywords_inserted += cursor.rowcount
            conn.commit()
        conn.commit()
    return {
        "versionsExamined": versions_examined,
        "versionsBackfilled": versions_backfilled,
        "skillsInserted": skills_inserted,
        "skillKeywordsInserted": keywords_inserted,
    }


def _extract_version_skills(row: sqlite3.Row) -> list[dict[str, Any]]:
    existing = _json_list(row["skills"])
    if existing:
        return [skill for skill in existing if isinstance(skill, dict)]
    record = types.SimpleNamespace(
        title=row["title"],
        department=row["department"],
        team=row["team"],
        employment_type=row["employment_type"],
        description=row["description"],
        description_html=row["description_html"],
        experience=row["experience"],
        responsibilities=_json_list(row["responsibilities"]),
        qualifications=_json_list(row["qualifications"]),
    )
    return [
        skill.model_dump(mode="json", exclude_none=True)
        for skill in extract_job_skills(record)
    ]


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _stable_id_from_slugs(*slugs: str) -> str:
    visible = ":".join(slug for slug in slugs if slug)
    if len(visible) <= 180:
        return visible
    return f"{visible[:120]}-{sha1(visible.encode('utf-8')).hexdigest()[:16]}"


@lru_cache(maxsize=512)
def _cached_slug(value: str) -> str:
    return slugify(value)


def _json_list(value: Any) -> list[Any]:
    data = _json_value(value)
    return data if isinstance(data, list) else []


def _json_value(value: Any) -> Any:
    if value in (None, ""):
        return None
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_snapshot_quality_report(
    *,
    output_dir: Path,
    db_path: Path,
    report_path: Path,
    sync_metrics: dict[str, Any],
    status: dict[str, Any],
    coverage: dict[str, Any] | None,
    empty_snapshot_explanation: str | None,
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = snapshot_quality_report(
        output_dir=output_dir,
        db_path=db_path,
        sync_metrics=sync_metrics,
        status=status,
        coverage=coverage,
        empty_snapshot_explanation=empty_snapshot_explanation,
        include_quality_file=False,
    )
    _write_json(report_path, report)
    report = snapshot_quality_report(
        output_dir=output_dir,
        db_path=db_path,
        sync_metrics=sync_metrics,
        status=status,
        coverage=coverage,
        empty_snapshot_explanation=empty_snapshot_explanation,
        include_quality_file=True,
    )
    _write_json(report_path, report)
    _checkpoint_sqlite(db_path)
    if report["status"] != "pass":
        blockers = "; ".join(report["hardBlockers"]) or "unknown quality failure"
        raise SystemExit(f"Snapshot quality gate failed: {blockers}")


def snapshot_quality_report(
    *,
    output_dir: Path,
    db_path: Path,
    sync_metrics: dict[str, Any],
    status: dict[str, Any],
    coverage: dict[str, Any] | None = None,
    empty_snapshot_explanation: str | None = None,
    include_quality_file: bool = True,
) -> dict[str, Any]:
    hard_blockers: list[str] = []
    warnings: list[str] = []
    required_files = _required_file_checks(
        output_dir, include_quality_file=include_quality_file
    )
    for item in required_files:
        if not item["exists"]:
            hard_blockers.append(f"missing_required_file:{item['path']}")
        elif item["sizeBytes"] == 0:
            hard_blockers.append(f"empty_required_file:{item['path']}")

    sqlite_report = _sqlite_snapshot_report(db_path)
    if not sqlite_report["readable"]:
        hard_blockers.append("unreadable_sqlite_database")
    for table_name in sqlite_report["missingTables"]:
        hard_blockers.append(f"missing_sqlite_table:{table_name}")

    status_counts = _nested_dict(status, "database", "counts")
    readiness = _nested_dict(status, "readiness")
    sqlite_counts = sqlite_report["counts"]

    enabled_sources = _int_count(sqlite_counts.get("enabledSources"))
    source_count = _int_count(
        status_counts.get("sources"), sqlite_counts.get("sources")
    )
    board_count = _int_count(status_counts.get("boards"), sqlite_counts.get("boards"))
    route_count = _int_count(
        status_counts.get("boardProviders"), sqlite_counts.get("boardProviders")
    )
    executable_routes = _int_count(
        readiness.get("executableRoutes"), sqlite_counts.get("jobCapableRoutes")
    )
    persisted_jobs = _int_count(status_counts.get("jobs"), sqlite_counts.get("jobs"))
    current_jobs = _int_count(sqlite_counts.get("openJobs"), persisted_jobs)
    job_sync_runs = _int_count(
        sync_metrics.get("jobSyncRuns"), sqlite_counts.get("successfulJobSyncRuns")
    )
    jobs_persisted = _int_count(sync_metrics.get("jobsPersisted"), persisted_jobs)
    provider_errors = _dict_value(sync_metrics.get("providerErrors"))
    provider_error_details = _dict_value(sync_metrics.get("providerErrorDetails"))
    total_provider_errors = sum(_int_count(value) for value in provider_errors.values())

    if source_count == 0 or enabled_sources == 0:
        hard_blockers.append("missing_enabled_source_evidence")
    if board_count == 0:
        hard_blockers.append("missing_board_data")
    if route_count == 0 or executable_routes == 0:
        hard_blockers.append("missing_executable_route_evidence")
    if executable_routes > 0 and job_sync_runs == 0 and not empty_snapshot_explanation:
        hard_blockers.append("missing_job_sync_run_evidence")
    if current_jobs == 0 and jobs_persisted == 0 and not empty_snapshot_explanation:
        hard_blockers.append("missing_current_job_evidence")
    if sqlite_counts.get("job_versions", 0) > 0:
        if sqlite_counts.get("job_version_skills", 0) == 0:
            hard_blockers.append("missing_job_version_skill_rows")
        if sqlite_counts.get("job_version_skill_keywords", 0) == 0:
            hard_blockers.append("missing_job_version_skill_keyword_rows")

    for provider_id, count in provider_errors.items():
        details = _dict_value(provider_error_details.get(provider_id))
        classified_count = sum(_int_count(value) for value in details.values())
        if classified_count < _int_count(count):
            hard_blockers.append(f"unclassified_provider_errors:{provider_id}")

    if (
        total_provider_errors
        and total_provider_errors > max(job_sync_runs, 0)
        and current_jobs == 0
        and not empty_snapshot_explanation
    ):
        hard_blockers.append("dominant_provider_failures")

    if provider_errors and not any(
        blocker.startswith("unclassified_provider_errors")
        or blocker == "dominant_provider_failures"
        for blocker in hard_blockers
    ):
        warnings.append("classified_provider_errors_present")
    if empty_snapshot_explanation:
        warnings.append("empty_snapshot_explanation_present")
    status_issues = status.get("issues")
    if isinstance(status_issues, list):
        for issue in status_issues:
            warnings.append(f"status_issue:{issue}")

    counts = {
        "enabledSources": enabled_sources,
        "sources": source_count,
        "boards": board_count,
        "boardProviders": route_count,
        "executableRoutes": executable_routes,
        "persistedJobs": persisted_jobs,
        "currentJobs": current_jobs,
        "jobSyncRuns": job_sync_runs,
        "jobsPersisted": jobs_persisted,
        "providerErrorCount": total_provider_errors,
    }
    return {
        "status": "fail" if hard_blockers else "pass",
        "generatedAt": datetime.now(UTC).isoformat(),
        "hardBlockers": hard_blockers,
        "warnings": warnings,
        "counts": counts,
        "metrics": {
            key: sync_metrics.get(key)
            for key in (
                "name",
                "pages",
                "boards",
                "boardProviders",
                "jobs",
                "jobsPersisted",
                "jobSyncRuns",
                "jobsDeduped",
                "skipped",
                "duplicateRoutesSkipped",
                "retries",
            )
        },
        "providerErrors": provider_errors,
        "providerErrorDetails": provider_error_details,
        "requiredFiles": required_files,
        "sqlite": sqlite_report,
        "coverage": _coverage_excerpt(coverage),
        "emptySnapshotExplanation": empty_snapshot_explanation,
    }


def _required_file_checks(
    output_dir: Path, *, include_quality_file: bool
) -> list[dict[str, Any]]:
    paths = [
        DB_FILE,
        "dataset-metadata.json",
        DATASET_IMAGE_FILE,
        SYNC_METRICS_FILE,
        STATUS_FILE,
        COVERAGE_FILE,
    ]
    if include_quality_file:
        paths.append(SNAPSHOT_QUALITY_FILE)
    paths.extend(f"{CSV_DIR}/{table.name}.csv" for table in TABLES)
    paths.extend(f"{PARQUET_DIR}/{table.name}.parquet" for table in TABLES)
    checks = []
    for relative_path in paths:
        path = output_dir / relative_path
        checks.append(
            {
                "path": relative_path,
                "exists": path.is_file(),
                "sizeBytes": path.stat().st_size if path.is_file() else 0,
            }
        )
    return checks


def _prune_private_upload_files(output_dir: Path) -> None:
    for relative_path in PRIVATE_EVIDENCE_FILES + PRIVATE_METADATA_FILES:
        path = output_dir / relative_path
        if path.exists():
            path.unlink()
    metadata_dir = output_dir / "metadata"
    if metadata_dir.exists() and not any(metadata_dir.iterdir()):
        metadata_dir.rmdir()


def _stage_public_upload_dir(dataset_dir: Path, upload_dir: Path) -> None:
    dataset_dir = dataset_dir.expanduser().resolve()
    upload_dir = upload_dir.expanduser().resolve()
    if upload_dir == dataset_dir:
        raise ValueError("Public upload staging directory must differ from dataset dir")
    if upload_dir.exists():
        shutil.rmtree(upload_dir)
    upload_dir.mkdir(parents=True)

    for relative_path in PUBLIC_UPLOAD_CONTROL_FILES + PUBLIC_UPLOAD_DATA_FILES:
        source = dataset_dir / relative_path
        if not source.is_file():
            raise FileNotFoundError(f"Public upload source file is missing: {source}")
        target = upload_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.hardlink_to(source)
        except OSError:
            shutil.copy2(source, target)


def _sqlite_snapshot_report(db_path: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "path": str(db_path),
        "readable": False,
        "missingTables": [],
        "counts": {},
    }
    if not db_path.is_file():
        return report
    try:
        with sqlite3.connect(db_path) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            missing_tables = [
                table.name for table in TABLES if table.name not in tables
            ]
            report["missingTables"] = missing_tables
            counts = {
                table.name: _sqlite_count(conn, table.name)
                for table in TABLES
                if table.name in tables
            }
            counts["enabledSources"] = _sqlite_count_where(
                conn, "sources", "enabled = 1"
            )
            counts["openJobs"] = _sqlite_count_where(conn, "jobs", "status = 'open'")
            counts["jobCapableRoutes"] = _sqlite_count_where(
                conn, "board_providers", "support_level = 'jobs'"
            )
            counts["successfulJobSyncRuns"] = _sqlite_count_where(
                conn, "job_sync_runs", "success = 1"
            )
            counts["sources"] = counts.get("sources", 0)
            counts["boards"] = counts.get("boards", 0)
            counts["boardProviders"] = counts.get("board_providers", 0)
            counts["jobs"] = counts.get("jobs", 0)
            report["counts"] = counts
            report["readable"] = True
    except sqlite3.Error as exc:
        report["error"] = str(exc)
    return report


def _sqlite_count(conn: sqlite3.Connection, table_name: str) -> int:
    return int(conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0])


def _sqlite_count_where(
    conn: sqlite3.Connection, table_name: str, predicate: str
) -> int:
    try:
        return int(
            conn.execute(
                f'SELECT COUNT(*) FROM "{table_name}" WHERE {predicate}'
            ).fetchone()[0]
        )
    except sqlite3.Error:
        return 0


def _nested_dict(data: dict[str, Any], *keys: str) -> dict[str, Any]:
    value: Any = data
    for key in keys:
        if not isinstance(value, dict):
            return {}
        value = value.get(key)
    return value if isinstance(value, dict) else {}


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _int_count(*values: Any) -> int:
    for value in values:
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def _coverage_excerpt(coverage: dict[str, Any] | None) -> dict[str, Any] | None:
    if coverage is None:
        return None
    return {
        key: coverage.get(key)
        for key in ("snapshot", "sources", "boards", "routes", "jobs", "gaps")
        if key in coverage
    }


def _drop_cache_tables(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE IF EXISTS http_cache")


def _write_sqlite_metadata(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS openopps_tables (
                table_name TEXT PRIMARY KEY,
                table_title TEXT NOT NULL,
                table_description TEXT NOT NULL,
                csv_path TEXT NOT NULL,
                parquet_path TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS openopps_columns (
                table_name TEXT NOT NULL,
                column_name TEXT NOT NULL,
                column_title TEXT NOT NULL,
                column_description TEXT NOT NULL,
                logical_type TEXT NOT NULL,
                json_schema_type TEXT NOT NULL,
                required INTEGER NOT NULL,
                source_name TEXT,
                format TEXT,
                enum_json TEXT,
                examples_json TEXT,
                default_json TEXT,
                PRIMARY KEY (table_name, column_name),
                FOREIGN KEY (table_name) REFERENCES openopps_tables(table_name)
            )
            """
        )
        conn.execute("DELETE FROM openopps_columns")
        conn.execute("DELETE FROM openopps_tables")
        for table in TABLES:
            conn.execute(
                """
                INSERT INTO openopps_tables (
                    table_name,
                    table_title,
                    table_description,
                    csv_path,
                    parquet_path
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    table.name,
                    _title_from_name(table.name),
                    table.description,
                    f"{CSV_DIR}/{table.name}.csv",
                    f"{PARQUET_DIR}/{table.name}.parquet",
                ),
            )
            for field in _model_schema_metadata(table.model)["fields"]:
                conn.execute(
                    """
                    INSERT INTO openopps_columns (
                        table_name,
                        column_name,
                        column_title,
                        column_description,
                        logical_type,
                        json_schema_type,
                        required,
                        source_name,
                        format,
                        enum_json,
                        examples_json,
                        default_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        table.name,
                        field["name"],
                        field["title"],
                        field["description"],
                        field.get("logicalType", field["type"]),
                        field["jsonSchemaType"],
                        int(field["required"]),
                        field.get("sourceName"),
                        field.get("format"),
                        _json_or_none(field.get("enum")),
                        _json_or_none(field.get("examples")),
                        _json_or_none(field.get("default")),
                    ),
                )


def _json_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True, default=str)


def _checkpoint_sqlite(path: Path) -> None:
    if not path.exists():
        return
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
    _remove_sqlite_sidecars(path)


def _finalize_sqlite_for_upload(path: Path) -> None:
    if not path.exists():
        return
    portable_db = path.with_name(f".{path.name}.portable")
    _remove_sqlite_sidecars(portable_db)
    if portable_db.exists():
        portable_db.unlink()
    with sqlite3.connect(path) as conn:
        checkpoint = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint and int(checkpoint[0]) != 0:
            raise RuntimeError(f"SQLite upload copy has busy WAL readers: {checkpoint}")
        conn.execute(f"VACUUM INTO {_sqlite_string_literal(portable_db.as_posix())}")
    with sqlite3.connect(portable_db) as conn:
        journal_mode = str(conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0])
    _assert_portable_sqlite_upload(portable_db)
    portable_db.replace(path)
    _remove_sqlite_sidecars(path)
    if journal_mode.lower() != "delete":
        raise RuntimeError(
            f"SQLite upload copy did not switch to DELETE journal mode: {journal_mode}"
        )
    _assert_portable_sqlite_upload(path)


def _sqlite_string_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _assert_portable_sqlite_upload(path: Path) -> None:
    write_version, read_version = _sqlite_header_read_write_versions(path)
    if (write_version, read_version) != (1, 1):
        raise RuntimeError(
            "SQLite upload copy is not in portable rollback-journal format: "
            f"header read/write versions are {(write_version, read_version)}"
        )
    with sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True) as conn:
        quick_check = str(conn.execute("PRAGMA quick_check").fetchone()[0])
        if quick_check.lower() != "ok":
            raise RuntimeError(f"SQLite upload copy failed quick_check: {quick_check}")
        table_count = int(
            conn.execute(
                "SELECT count(*) FROM sqlite_master WHERE type = 'table'"
            ).fetchone()[0]
        )
    if table_count == 0:
        raise RuntimeError("SQLite upload copy has no readable tables.")


def _sqlite_header_read_write_versions(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(20)
    if len(header) < 20 or not header.startswith(b"SQLite format 3\x00"):
        raise RuntimeError(f"Not a SQLite database file: {path}")
    return header[18], header[19]


def _remove_sqlite_sidecars(path: Path) -> None:
    for suffix in SQLITE_SIDECAR_SUFFIXES:
        sidecar = path.with_name(f"{path.name}{suffix}")
        if sidecar.exists():
            sidecar.unlink()


def _markdown_cell(cell_id: str, source: str) -> dict[str, Any]:
    return {
        "cell_type": "markdown",
        "id": cell_id,
        "metadata": {},
        "source": _cell_lines(source),
    }


def _code_cell(cell_id: str, source: str) -> dict[str, Any]:
    return {
        "cell_type": "code",
        "execution_count": None,
        "id": cell_id,
        "metadata": {},
        "outputs": [],
        "source": _cell_lines(source),
    }


def _cell_lines(source: str) -> list[str]:
    return [f"{line}\n" for line in source.rstrip("\n").split("\n")]


def _notebook_setup_source() -> str:
    sync_env_defaults = json.dumps(NOTEBOOK_SYNC_ENV_DEFAULTS, indent=4, sort_keys=True)
    skill_catalog = json.dumps(_SKILL_CATALOG, indent=4)
    notebook_dataset_metadata = pformat(
        dataset_metadata(),
        sort_dicts=True,
        width=100,
    )
    sqlite_table_metadata = pformat(
        [_table_metadata(table) for table in TABLES],
        sort_dicts=True,
        width=100,
    )
    table_rows = pformat(_notebook_table_rows(), sort_dicts=True, width=100)
    column_rows = pformat(_notebook_column_rows(), sort_dicts=True, width=100)
    public_upload_data_files = pformat(
        PUBLIC_UPLOAD_DATA_FILES,
        sort_dicts=True,
        width=100,
    )
    return """#@title Initialize
from __future__ import annotations

import base64
import csv
import hashlib
from functools import lru_cache
from html import unescape
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime
import urllib.request

DATASET_ID = os.environ.get(
    "OPENOPPS_KAGGLE_DATASET",
    "wyattowalsh/openoppsdb",
)
PACKAGE_SPEC = os.environ.get(
    "OPENOPPS_PACKAGE_SPEC",
    "git+https://github.com/wyattowalsh/openopps.git@main",
)
OUTPUT_DIR = Path(
    os.environ.get(
        "OPENOPPS_KAGGLE_OUTPUT_DIR",
        "/kaggle/working/openoppsdb",
    )
)
DB_PATH = OUTPUT_DIR / "openoppsdb.sqlite"
GENERATOR_SCRIPT = OUTPUT_DIR / "generate_kaggle_metadata.py"
CSV_DIR = "exports/csv"
PARQUET_DIR = "exports/parquet"
KAGGLE_INPUT_DIR = Path("/kaggle/input")
INPUT_DB_GLOB = "**/openoppsdb.sqlite"
INPUT_JOB_VERSIONS_PARQUET_GLOB = "**/exports/parquet/job_versions.parquet"
INPUT_JOB_PAYLOAD_SNAPSHOTS_PARQUET_GLOB = "**/exports/parquet/job_payload_snapshots.parquet"
GENERATOR_SCRIPT_URL = os.environ.get(
    "OPENOPPS_GENERATOR_SCRIPT_URL",
    "https://raw.githubusercontent.com/wyattowalsh/openopps/main/scripts/generate_kaggle_metadata.py",
)
DATASET_IMAGE_URL = os.environ.get(
    "OPENOPPS_DATASET_IMAGE_URL",
    "https://raw.githubusercontent.com/wyattowalsh/openopps/main/docs/public/social/openoppsdb.png",
)
OPENOPPS_SYNC_ENV_DEFAULTS = __OPENOPPS_SYNC_ENV_DEFAULTS__
SKILL_CATALOG = __SKILL_CATALOG__
DATASET_METADATA = __DATASET_METADATA__
SQLITE_TABLE_METADATA = __SQLITE_TABLE_METADATA__
OPENOPPS_TABLE_ROWS = __OPENOPPS_TABLE_ROWS__
OPENOPPS_COLUMN_ROWS = __OPENOPPS_COLUMN_ROWS__
PUBLIC_UPLOAD_DATA_FILES = __PUBLIC_UPLOAD_DATA_FILES__
SKILL_TEXT_VALUE_LIMIT = 4000
SKILL_LEVEL_ALIASES = (
    ("Executive", ("chief", "c-level", "c suite", "vp", "vice president")),
    ("Principal", ("principal", "staff")),
    ("Senior", ("senior", "sr", "lead")),
    ("Manager", ("manager", "director", "head of")),
    ("Junior", ("junior", "jr", "entry level", "intern", "associate")),
)
SLUG_RE = re.compile(r"[^a-z0-9]+")
KAGGLE_SYNC_TIMEOUT_SECONDS = float(
    os.environ.get(
        "OPENOPPS_KAGGLE_SYNC_TIMEOUT_SECONDS",
        "__OPENOPPS_KAGGLE_SYNC_TIMEOUT_SECONDS__",
    )
)
KAGGLE_JOB_ROUTE_LIMIT = int(
    os.environ.get(
        "OPENOPPS_KAGGLE_JOB_ROUTE_LIMIT",
        "__OPENOPPS_KAGGLE_JOB_ROUTE_LIMIT__",
    )
)
KAGGLE_CREDENTIALS_ERROR = (
    "Kaggle API credentials are required to publish openoppsdb. "
    "Configure KAGGLE_USERNAME and KAGGLE_KEY as Kaggle notebook secrets "
    "before running the manager."
)
KAGGLE_SECRET_RETRIES = int(os.environ.get("OPENOPPS_KAGGLE_SECRET_RETRIES", "30"))
KAGGLE_SECRET_RETRY_SECONDS = float(
    os.environ.get("OPENOPPS_KAGGLE_SECRET_RETRY_SECONDS", "10")
)
KAGGLE_SECRET_LOOKUP_ERRORS: dict[str, str] = {}

if OUTPUT_DIR.exists():
    shutil.rmtree(OUTPUT_DIR)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def normalize_kaggle_notebook_secret(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None

def read_kaggle_notebook_secrets() -> tuple[str | None, str | None]:
    last_key = None
    last_username = None
    for attempt in range(1, KAGGLE_SECRET_RETRIES + 1):
        key_error = None
        username_error = None
        try:
            from kaggle_secrets import UserSecretsClient
        except Exception as exc:
            KAGGLE_SECRET_LOOKUP_ERRORS["kaggle_secrets"] = type(exc).__name__
            print(f"Kaggle notebook secrets client unavailable: {type(exc).__name__}")
            return last_key, last_username

        user_secrets = UserSecretsClient()
        try:
            secret_value_0 = user_secrets.get_secret("KAGGLE_KEY")
        except Exception as exc:
            key_error = type(exc).__name__
            KAGGLE_SECRET_LOOKUP_ERRORS["KAGGLE_KEY"] = key_error
            print(
                f"KAGGLE_KEY notebook secret lookup failed "
                f"(attempt {attempt}/{KAGGLE_SECRET_RETRIES}): "
                f"{key_error}"
            )
            secret_value_0 = None

        try:
            secret_value_1 = user_secrets.get_secret("KAGGLE_USERNAME")
        except Exception as exc:
            username_error = type(exc).__name__
            KAGGLE_SECRET_LOOKUP_ERRORS["KAGGLE_USERNAME"] = username_error
            print(
                f"KAGGLE_USERNAME notebook secret lookup failed "
                f"(attempt {attempt}/{KAGGLE_SECRET_RETRIES}): "
                f"{username_error}"
            )
            secret_value_1 = None

        key = normalize_kaggle_notebook_secret(secret_value_0)
        username = normalize_kaggle_notebook_secret(secret_value_1)
        if key:
            last_key = key
            KAGGLE_SECRET_LOOKUP_ERRORS.pop("KAGGLE_KEY", None)
        elif key_error is None:
            KAGGLE_SECRET_LOOKUP_ERRORS["KAGGLE_KEY"] = "NotFound"
            print(
                f"KAGGLE_KEY not found in Kaggle notebook secrets "
                f"(attempt {attempt}/{KAGGLE_SECRET_RETRIES})."
            )

        if username:
            last_username = username
            KAGGLE_SECRET_LOOKUP_ERRORS.pop("KAGGLE_USERNAME", None)
        elif username_error is None:
            KAGGLE_SECRET_LOOKUP_ERRORS["KAGGLE_USERNAME"] = "NotFound"
            print(
                f"KAGGLE_USERNAME not found in Kaggle notebook secrets "
                f"(attempt {attempt}/{KAGGLE_SECRET_RETRIES})."
            )

        if key and username:
            return key, username

        if attempt < KAGGLE_SECRET_RETRIES:
            time.sleep(KAGGLE_SECRET_RETRY_SECONDS)
            continue
    return last_key, last_username

def load_kaggle_notebook_secrets() -> None:
    if os.environ.get("KAGGLE_USERNAME") and os.environ.get("KAGGLE_KEY"):
        print("KAGGLE_USERNAME and KAGGLE_KEY already present in environment.")
        return

    key, username = read_kaggle_notebook_secrets()

    if os.environ.get("KAGGLE_USERNAME"):
        print("KAGGLE_USERNAME already present in environment.")
    elif username:
        os.environ["KAGGLE_USERNAME"] = username
        print("KAGGLE_USERNAME loaded from Kaggle notebook secrets.")

    if os.environ.get("KAGGLE_KEY"):
        print("KAGGLE_KEY already present in environment.")
    elif key:
        os.environ["KAGGLE_KEY"] = key
        print("KAGGLE_KEY loaded from Kaggle notebook secrets.")

def has_kaggle_credentials() -> bool:
    load_kaggle_notebook_secrets()
    kaggle_json = Path.home() / ".kaggle" / "kaggle.json"
    token_path = os.environ.get("KAGGLE_API_V1_TOKEN_PATH")
    return bool(
        os.environ.get("KAGGLE_API_TOKEN")
        or (token_path and Path(token_path).expanduser().exists())
        or (os.environ.get("KAGGLE_USERNAME") and os.environ.get("KAGGLE_KEY"))
        or kaggle_json.exists()
    )

def require_kaggle_credentials() -> None:
    if not has_kaggle_credentials():
        if KAGGLE_SECRET_LOOKUP_ERRORS:
            details = ", ".join(
                f"{key}={value}"
                for key, value in sorted(KAGGLE_SECRET_LOOKUP_ERRORS.items())
            )
            raise RuntimeError(f"{KAGGLE_CREDENTIALS_ERROR} Lookup diagnostics: {details}")
        raise RuntimeError(KAGGLE_CREDENTIALS_ERROR)

def run(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    timeout_seconds: float | None = None,
) -> None:
    print("+", " ".join(command))
    subprocess.run(command, check=True, env=env, timeout=timeout_seconds)

def run_json(
    command: list[str],
    output_path: Path,
    *,
    env: dict[str, str] | None = None,
    timeout_seconds: float | None = None,
) -> dict:
    print("+", " ".join(command), ">", output_path)
    try:
        completed = subprocess.run(
            command,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        if exc.stdout:
            print(exc.stdout)
        if exc.stderr:
            print(exc.stderr, file=sys.stderr)
        timeout_label = (
            f"{timeout_seconds:g}" if timeout_seconds is not None else "unknown"
        )
        raise TimeoutError(
            f"Command exceeded {timeout_label}s: {' '.join(command)}"
        ) from exc
    if completed.returncode:
        if completed.stdout:
            print(completed.stdout)
        if completed.stderr:
            print(completed.stderr, file=sys.stderr)
        completed.check_returncode()
    data = json.loads(completed.stdout)
    output_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\\n")
    print(f"Wrote {output_path}")
    return data

EMBEDDED_BOUNDED_JOB_SYNC_CODE = r'''
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sqlite3
import sys

from openopps.ingest import sync_jobs
from openopps.metrics import SyncMetrics
from openopps.route_registry import BoardRouteRegistry
from openopps.settings import OpenOppsSettings
from openopps.storage import OpenOppsStore


def parse_dt(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def latest_job_syncs(db_path: Path):
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT board_key, provider_id, max(synced_at) "
            "FROM job_sync_runs "
            "WHERE success = 1 "
            "GROUP BY board_key, provider_id"
        ).fetchall()
    return {
        (board_key, provider_id): parse_dt(synced_at)
        for board_key, provider_id, synced_at in rows
        if synced_at
    }


def route_sync_key(entry):
    return (entry.route.board_key, entry.route.provider_id)


def route_priority(item):
    index, entry, synced_at = item
    earliest = datetime.min.replace(tzinfo=UTC)
    return (
        0 if synced_at is None else 1,
        synced_at or earliest,
        entry.route.provider_id,
        entry.board.key,
        index,
    )


def selected_routes(store, db_path: Path, freshness_seconds: float, route_limit: int):
    selection = BoardRouteRegistry(store).select(ready_only=True)
    latest = latest_job_syncs(db_path)
    cutoff = datetime.now(UTC) - timedelta(seconds=freshness_seconds)
    fresh_skipped = 0
    stale = []
    for index, entry in enumerate(selection.entries):
        synced_at = latest.get(route_sync_key(entry))
        if freshness_seconds > 0 and synced_at and synced_at >= cutoff:
            fresh_skipped += 1
            continue
        stale.append((index, entry, synced_at))
    stale.sort(key=route_priority)
    selected = stale[:route_limit]
    deferred = max(0, len(stale) - len(selected))
    return [entry for _, entry, _ in selected], fresh_skipped, deferred, selection


def add_metrics(total: SyncMetrics, item: SyncMetrics) -> None:
    total.pages += item.pages
    total.boards += item.boards
    total.board_providers += item.board_providers
    total.jobs += item.jobs
    total.jobs_persisted += item.jobs_persisted
    total.job_sync_runs += item.job_sync_runs
    total.jobs_deduped += item.jobs_deduped
    total.skipped += item.skipped
    total.duplicate_routes_skipped += item.duplicate_routes_skipped
    total.retries += item.retries
    for provider_id, count in item.provider_errors.items():
        total.provider_errors[provider_id] = (
            total.provider_errors.get(provider_id, 0) + count
        )
    for provider_id, details in item.provider_error_details.items():
        total_details = total.provider_error_details.setdefault(provider_id, {})
        for reason, count in details.items():
            total_details[reason] = total_details.get(reason, 0) + count


async def main() -> None:
    db_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    freshness_seconds = float(sys.argv[3])
    route_limit = int(sys.argv[4])
    settings = OpenOppsSettings()
    store = OpenOppsStore(settings)
    routes, fresh_skipped, deferred, selection = selected_routes(
        store, db_path, freshness_seconds, route_limit
    )
    metrics = SyncMetrics(name="jobs.sync")
    metrics.skipped += fresh_skipped + deferred
    metrics.duplicate_routes_skipped += len(selection.duplicate_routes)
    for entry in routes:
        add_metrics(
            metrics,
            await sync_jobs(
                settings=settings,
                store=store,
                board_key=entry.route.board_key,
                provider_id=entry.route.provider_id,
            ),
        )
    data = metrics.finish().as_dict()
    data["selectedRoutes"] = len(routes)
    data["freshRoutesSkipped"] = fresh_skipped
    data["deferredRoutes"] = deferred
    data["missingRouteMetadataSkipped"] = len(selection.missing_route_metadata)
    data["compatibilityMode"] = "embedded-bounded-job-sync"
    output_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\\n")


asyncio.run(main())
'''

def openopps_cli_supports_bounded_jobs_sync(env: dict[str, str]) -> bool:
    completed = subprocess.run(
        ["openopps", "jobs", "sync", "--help"],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    help_text = completed.stdout + completed.stderr
    return completed.returncode == 0 and "--freshness-seconds" in help_text and "--limit" in help_text

def run_embedded_bounded_job_sync(
    output_path: Path,
    *,
    env: dict[str, str],
    timeout_seconds: float | None,
) -> dict:
    freshness_seconds = env.get("OPENOPPS_JOB_ROUTE_FRESHNESS_SECONDS", "86400")
    command = [
        sys.executable,
        "-c",
        EMBEDDED_BOUNDED_JOB_SYNC_CODE,
        str(DB_PATH),
        str(output_path),
        freshness_seconds,
        str(KAGGLE_JOB_ROUTE_LIMIT),
    ]
    print("+", sys.executable, "-c", "EMBEDDED_BOUNDED_JOB_SYNC_CODE", ">", output_path)
    completed = subprocess.run(
        command,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
    )
    if completed.stdout:
        print(completed.stdout)
    if completed.stderr:
        print(completed.stderr, file=sys.stderr)
    completed.check_returncode()
    data = json.loads(output_path.read_text())
    print(f"Wrote embedded bounded sync metrics to {output_path}")
    return data

def run_sync_metrics(
    output_path: Path,
    *,
    env: dict[str, str],
    timeout_seconds: float | None,
) -> dict:
    command = [
        "openopps",
        "jobs",
        "sync",
        "--metrics-json",
        "--freshness-seconds",
        env.get("OPENOPPS_JOB_ROUTE_FRESHNESS_SECONDS", "86400"),
        "--limit",
        str(KAGGLE_JOB_ROUTE_LIMIT),
    ]
    if not openopps_cli_supports_bounded_jobs_sync(env):
        print(
            "Installed OpenOpps CLI does not expose bounded jobs sync flags; "
            "using embedded bounded job sync."
        )
        return run_embedded_bounded_job_sync(
            output_path,
            env=env,
            timeout_seconds=timeout_seconds,
        )
    try:
        return run_json(
            command,
            output_path,
            env=env,
            timeout_seconds=timeout_seconds,
        )
    except subprocess.CalledProcessError:
        print(
            "bounded openopps jobs sync --metrics-json failed; falling back to "
            "plain bounded jobs sync and SQLite-derived metrics."
        )
        run(
            [part for part in command if part != "--metrics-json"],
            env=env,
            timeout_seconds=timeout_seconds,
        )
        data = sqlite_sync_metrics(DB_PATH)
        output_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\\n")
        print(f"Wrote compatibility sync metrics to {output_path}")
        return data

def sqlite_sync_metrics(db_path: Path) -> dict:
    def count(conn, table: str, where: str | None = None) -> int:
        try:
            query = f"SELECT count(*) FROM {table}"
            if where:
                query = f"{query} WHERE {where}"
            return int(conn.execute(query).fetchone()[0])
        except sqlite3.Error:
            return 0

    with sqlite3.connect(db_path) as conn:
        jobs = count(conn, "jobs")
        successful_runs = count(conn, "job_sync_runs", "success = 1")
        return {
            "compatibilityMode": "sqlite-derived-after-plain-sync",
            "sourcesProcessed": count(conn, "sources"),
            "boardsPersisted": count(conn, "boards"),
            "boardProviders": count(conn, "board_providers"),
            "jobsPersisted": jobs,
            "jobSyncRuns": successful_runs,
            "providerErrors": {},
            "providerErrorDetails": {},
        }

def install_openopps() -> None:
    run([sys.executable, "-m", "pip", "install", "--quiet", "--upgrade", PACKAGE_SPEC, "kaggle"])

def copy_latest_input_db() -> None:
    db_candidates = sorted(KAGGLE_INPUT_DIR.glob(INPUT_DB_GLOB))
    if db_candidates:
        source_db = max(db_candidates, key=lambda path: path.stat().st_mtime)
        shutil.copy2(source_db, DB_PATH)
        print(f"Copied prior OpenOpps DB snapshot from {source_db} to {DB_PATH}")
        restore_projected_sqlite_columns_from_input_exports()
    else:
        print("No prior OpenOpps DB snapshot found; creating a new ledger.")

def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'

def restore_projected_sqlite_table_columns(
    *,
    parquet_glob: str,
    table_name: str,
    column_names: list[str],
) -> None:
    parquet_candidates = sorted(KAGGLE_INPUT_DIR.glob(parquet_glob))
    if not parquet_candidates or not DB_PATH.exists():
        return
    source_parquet = max(parquet_candidates, key=lambda path: path.stat().st_mtime)
    table_sql = quote_identifier(table_name)
    missing_condition = " OR ".join(
        f"{quote_identifier(column)} IS NULL" for column in column_names
    )
    with sqlite3.connect(DB_PATH) as conn:
        missing_count = int(
            conn.execute(
                f"SELECT count(*) FROM {table_sql} WHERE {missing_condition}"
            ).fetchone()[0]
        )
    if missing_count == 0:
        return

    import polars as pl

    restore_csv = OUTPUT_DIR / f"_restore_{table_name}.csv"
    restore_columns = ["id", *column_names]
    pl.scan_parquet(source_parquet).select(restore_columns).sink_csv(restore_csv)
    restored_rows = 0
    csv.field_size_limit(sys.maxsize)
    with sqlite3.connect(DB_PATH) as conn, restore_csv.open(
        newline="", encoding="utf-8"
    ) as handle:
        reader = csv.DictReader(handle)
        restore_table = f"restore_{table_name}"
        restore_table_sql = quote_identifier(restore_table)
        column_defs = ", ".join(
            f"{quote_identifier(column)} TEXT" for column in restore_columns
        )
        conn.execute(f"CREATE TEMP TABLE {restore_table_sql} ({column_defs}, PRIMARY KEY (id))")
        batch = []
        for row in reader:
            batch.append(tuple(row[column] for column in restore_columns))
            if len(batch) >= 1000:
                conn.executemany(
                    f"INSERT OR REPLACE INTO {restore_table_sql} VALUES "
                    f"({', '.join('?' for _ in restore_columns)})",
                    batch,
                )
                restored_rows += len(batch)
                batch.clear()
        if batch:
            conn.executemany(
                f"INSERT OR REPLACE INTO {restore_table_sql} VALUES "
                f"({', '.join('?' for _ in restore_columns)})",
                batch,
            )
            restored_rows += len(batch)
        assignments = ", ".join(
            f"{quote_identifier(column)} = ("
            f"SELECT {restore_table_sql}.{quote_identifier(column)} "
            f"FROM {restore_table_sql} "
            f"WHERE {restore_table_sql}.id = {table_sql}.id)"
            for column in column_names
        )
        conn.execute(
            f"UPDATE {table_sql} SET {assignments} "
            f"WHERE {missing_condition} AND EXISTS ("
            f"SELECT 1 FROM {restore_table_sql} WHERE {restore_table_sql}.id = {table_sql}.id)"
        )
        conn.commit()
    restore_csv.unlink(missing_ok=True)
    print(
        "Restored projected SQLite values from prior Parquet export:",
        json.dumps(
            {
                "source": str(source_parquet),
                "table": table_name,
                "columns": column_names,
                "missingBefore": missing_count,
                "restoreRows": restored_rows,
            },
            sort_keys=True,
        ),
    )

def restore_projected_sqlite_columns_from_input_exports() -> None:
    restore_projected_sqlite_table_columns(
        parquet_glob=INPUT_JOB_VERSIONS_PARQUET_GLOB,
        table_name="job_versions",
        column_names=["description_html", "job_description"],
    )
    restore_projected_sqlite_table_columns(
        parquet_glob=INPUT_JOB_PAYLOAD_SNAPSHOTS_PARQUET_GLOB,
        table_name="job_payload_snapshots",
        column_names=["payload"],
    )

def download_dataset_assets() -> None:
    urllib.request.urlretrieve(DATASET_IMAGE_URL, OUTPUT_DIR / "dataset-cover-image.png")

def slugify(value: str) -> str:
    slug = SLUG_RE.sub("-", value.lower()).strip("-")
    return slug or hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]

def stable_id(*parts) -> str:
    visible = ":".join(
        slugify(str(part)) for part in parts if part is not None and str(part) != ""
    )
    if len(visible) <= 180:
        return visible
    digest = hashlib.sha1(visible.encode("utf-8")).hexdigest()[:16]
    return f"{visible[:120]}-{digest}"

def stable_id_from_slugs(*slugs: str) -> str:
    visible = ":".join(slug for slug in slugs if slug)
    if len(visible) <= 180:
        return visible
    digest = hashlib.sha1(visible.encode("utf-8")).hexdigest()[:16]
    return f"{visible[:120]}-{digest}"

@lru_cache(maxsize=512)
def cached_slug(value: str) -> str:
    return slugify(value)

def strip_html(value: str | None) -> str | None:
    if not value:
        return None
    with_breaks = re.sub(r"(?i)<\\s*br\\s*/?\\s*>", "\\n", value)
    with_breaks = re.sub(r"(?i)</\\s*(p|div|li|h[1-6])\\s*>", "\\n", with_breaks)
    text = re.sub(r"<[^>]+>", " ", with_breaks)
    text = unescape(text)
    text = re.sub(r"[ \\t\\r\\f\\v]+", " ", text)
    text = re.sub(r"\\n\\s+", "\\n", text)
    text = re.sub(r"\\n{3,}", "\\n\\n", text)
    text = text.strip()
    return text or None

def normalized_skill_text(values) -> str:
    raw = " ".join(str(value)[:SKILL_TEXT_VALUE_LIMIT] for value in values if value)
    raw = strip_html(raw) or raw
    normalized = re.sub(r"[^a-z0-9+#]+", " ", raw.casefold())
    normalized = re.sub(r"\\s+", " ", normalized).strip()
    return f" {normalized} "

@lru_cache(maxsize=256)
def compile_skill_aliases(aliases: tuple[str, ...]):
    normalized_aliases = tuple(
        sorted(
            {
                normalized_alias
                for alias in aliases
                if (normalized_alias := normalized_skill_text([alias]).strip())
            },
            key=len,
            reverse=True,
        )
    )
    if not normalized_aliases:
        return frozenset(), ()
    single_tokens = frozenset(
        normalized_alias
        for normalized_alias in normalized_aliases
        if " " not in normalized_alias
    )
    phrases = tuple(
        normalized_alias
        for normalized_alias in normalized_aliases
        if " " in normalized_alias
    )
    return single_tokens, phrases

@lru_cache(maxsize=1)
def compiled_skill_catalog():
    return tuple(
        (
            group_name,
            tuple(
                (
                    keyword,
                    *compile_skill_aliases(tuple(aliases)),
                )
                for keyword, aliases in keywords
            ),
        )
        for group_name, keywords in SKILL_CATALOG
    )

@lru_cache(maxsize=1)
def compiled_level_aliases():
    return tuple(
        (label, *compile_skill_aliases(aliases))
        for label, aliases in SKILL_LEVEL_ALIASES
    )

def has_compiled_skill_alias(
    normalized_text: str,
    text_tokens: frozenset[str],
    single_tokens: frozenset[str],
    phrases: tuple[str, ...],
) -> bool:
    return (not text_tokens.isdisjoint(single_tokens)) or any(
        phrase in normalized_text for phrase in phrases
    )

def json_value(value):
    if value in (None, ""):
        return None
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value

def json_list(value) -> list:
    data = json_value(value)
    return data if isinstance(data, list) else []

def string_or_none(value) -> str | None:
    if value is None:
        return None
    return str(value)

def skill_level(row) -> str | None:
    text = normalized_skill_text([row["experience"], row["title"]])
    text_tokens = frozenset(text.split())
    for label, single_tokens, phrases in compiled_level_aliases():
        if has_compiled_skill_alias(text, text_tokens, single_tokens, phrases):
            return label
    return row["experience"]

def extract_version_skills(row) -> list[dict]:
    existing = json_list(row["skills"])
    if existing:
        return existing
    description_text = row["description"] or row["description_html"]
    text = normalized_skill_text(
        [
            row["title"],
            row["department"],
            row["team"],
            row["employment_type"],
            description_text,
            *json_list(row["responsibilities"]),
            *json_list(row["qualifications"]),
        ]
    )
    if not text.strip():
        return []
    level = skill_level(row)
    text_tokens = frozenset(text.split())
    skills = []
    for group_name, keywords in compiled_skill_catalog():
        matched = [
            keyword
            for keyword, single_tokens, phrases in keywords
            if has_compiled_skill_alias(text, text_tokens, single_tokens, phrases)
        ]
        if matched:
            skills.append({"name": group_name, "level": level, "keywords": matched[:12]})
    return skills

def backfill_openopps_skill_tables(db_path: Path) -> dict[str, int]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA temp_store = MEMORY")
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        required = {
            "jobs",
            "job_versions",
            "job_version_skills",
            "job_version_skill_keywords",
        }
        if not required <= tables:
            return {
                "versionsExamined": 0,
                "versionsBackfilled": 0,
                "skillsInserted": 0,
                "skillKeywordsInserted": 0,
            }

        conn.execute(
            \"\"\"
            CREATE INDEX IF NOT EXISTS ix_job_version_skills_job_version_id
            ON job_version_skills (job_version_id)
            \"\"\"
        )
        conn.execute(
            \"\"\"
            CREATE INDEX IF NOT EXISTS ix_job_version_skill_keywords_skill_id
            ON job_version_skill_keywords (skill_id)
            \"\"\"
        )
        examined = 0
        backfilled = 0
        skills_inserted = 0
        keywords_inserted = 0
        last_rowid = 0
        chunk_size = 2000
        while True:
            rows = conn.execute(
                \"\"\"
                SELECT
                    v.rowid AS _rowid,
                    v.id,
                    v.title,
                    v.department,
                    v.team,
                    v.employment_type,
                    v.description,
                    v.description_html,
                    v.experience,
                    v.responsibilities,
                    v.qualifications,
                    v.skills
                FROM job_versions AS v
                WHERE v.rowid > ?
                  AND (
                    NOT EXISTS (
                        SELECT 1
                        FROM job_version_skills AS s
                        WHERE s.job_version_id = v.id
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM job_version_skills AS s
                        WHERE s.job_version_id = v.id
                          AND NOT EXISTS (
                            SELECT 1
                            FROM job_version_skill_keywords AS k
                            WHERE k.skill_id = s.id
                          )
                    )
                  )
                ORDER BY v.rowid
                LIMIT ?
                \"\"\",
                (last_rowid, chunk_size),
            ).fetchall()
            if not rows:
                break
            last_rowid = int(rows[-1]["_rowid"])
            version_ids = [(row["id"],) for row in rows]
            conn.executemany(
                \"\"\"
                DELETE FROM job_version_skill_keywords
                WHERE skill_id IN (
                    SELECT id
                    FROM job_version_skills
                    WHERE job_version_id = ?
                )
                \"\"\",
                version_ids,
            )
            conn.executemany(
                "DELETE FROM job_version_skills WHERE job_version_id = ?",
                version_ids,
            )
            version_updates = []
            skill_rows = []
            keyword_rows = []
            for row in rows:
                examined += 1
                skills = extract_version_skills(row)
                if not skills:
                    continue
                version_slug = slugify(str(row["id"]))
                if not json_list(row["skills"]):
                    version_updates.append(
                        (
                            json.dumps(
                                skills,
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                            row["id"],
                        )
                    )
                for ordinal, skill in enumerate(skills):
                    skill_id = stable_id_from_slugs(
                        version_slug,
                        "skill",
                        str(ordinal),
                    )
                    skill_slug = slugify(skill_id)
                    skill_rows.append(
                        (
                            skill_id,
                            row["id"],
                            ordinal,
                            string_or_none(skill.get("name")),
                            string_or_none(skill.get("level")),
                        )
                    )
                    for keyword_ordinal, keyword in enumerate(skill.get("keywords") or []):
                        keyword_text = str(keyword)
                        keyword_rows.append(
                            (
                                stable_id_from_slugs(
                                    skill_slug,
                                    "keyword",
                                    str(keyword_ordinal),
                                    cached_slug(keyword_text),
                                ),
                                skill_id,
                                keyword_ordinal,
                                keyword_text,
                            )
                        )
                backfilled += 1
            if version_updates:
                conn.executemany(
                    "UPDATE job_versions SET skills = ? WHERE id = ?",
                    version_updates,
                )
            if skill_rows:
                cursor = conn.executemany(
                    \"\"\"
                    INSERT INTO job_version_skills (
                        id,
                        job_version_id,
                        ordinal,
                        name,
                        level
                    ) VALUES (?, ?, ?, ?, ?)
                    \"\"\",
                    skill_rows,
                )
                if cursor.rowcount and cursor.rowcount > 0:
                    skills_inserted += cursor.rowcount
            if keyword_rows:
                cursor = conn.executemany(
                    \"\"\"
                    INSERT INTO job_version_skill_keywords (
                        id,
                        skill_id,
                        ordinal,
                        keyword
                    ) VALUES (?, ?, ?, ?)
                    \"\"\",
                    keyword_rows,
                )
                if cursor.rowcount and cursor.rowcount > 0:
                    keywords_inserted += cursor.rowcount
            conn.commit()
        conn.commit()
    return {
        "versionsExamined": examined,
        "versionsBackfilled": backfilled,
        "skillsInserted": skills_inserted,
        "skillKeywordsInserted": keywords_inserted,
    }

def write_json(path: Path, data: dict | list) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\\n")
    print(f"Wrote {path}")

def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())

def checkpoint_sqlite(db_path: Path) -> None:
    if db_path.exists():
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
    for suffix in ("-journal", "-shm", "-wal"):
        sidecar = db_path.with_name(f"{db_path.name}{suffix}")
        if sidecar.exists():
            sidecar.unlink()

def sqlite_header_read_write_versions(db_path: Path) -> tuple[int, int]:
    header = db_path.read_bytes()[:20]
    if len(header) < 20 or not header.startswith(b"SQLite format 3\\x00"):
        raise RuntimeError(f"Not a SQLite database file: {db_path}")
    return header[18], header[19]

def assert_portable_sqlite_upload(db_path: Path) -> None:
    versions = sqlite_header_read_write_versions(db_path)
    if versions != (1, 1):
        raise RuntimeError(
            "SQLite upload copy is not in portable rollback-journal format: "
            f"header read/write versions are {versions}"
        )
    with sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True) as conn:
        quick_check = str(conn.execute("PRAGMA quick_check").fetchone()[0])
        if quick_check.lower() != "ok":
            raise RuntimeError(f"SQLite upload copy failed quick_check: {quick_check}")
        table_count = int(
            conn.execute(
                "SELECT count(*) FROM sqlite_master WHERE type = 'table'"
            ).fetchone()[0]
        )
    if table_count == 0:
        raise RuntimeError("SQLite upload copy has no readable tables.")

def finalize_sqlite_for_upload(db_path: Path) -> None:
    if not db_path.exists():
        return
    portable_db = db_path.with_name(f".{db_path.name}.portable")
    for suffix in ("-journal", "-shm", "-wal"):
        sidecar = portable_db.with_name(f"{portable_db.name}{suffix}")
        if sidecar.exists():
            sidecar.unlink()
    if portable_db.exists():
        portable_db.unlink()
    with sqlite3.connect(db_path) as conn:
        checkpoint = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint and int(checkpoint[0]) != 0:
            raise RuntimeError(f"SQLite upload copy has busy WAL readers: {checkpoint}")
        literal = "'" + portable_db.as_posix().replace("'", "''") + "'"
        conn.execute(f"VACUUM INTO {literal}")
    with sqlite3.connect(portable_db) as conn:
        journal_mode = str(conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0])
    assert_portable_sqlite_upload(portable_db)
    portable_db.replace(db_path)
    checkpoint_sqlite(db_path)
    if journal_mode.lower() != "delete":
        raise RuntimeError(
            f"SQLite upload copy did not switch to DELETE journal mode: {journal_mode}"
        )
    assert_portable_sqlite_upload(db_path)

def write_dataset_metadata() -> None:
    write_json(OUTPUT_DIR / "dataset-metadata.json", DATASET_METADATA)

def write_sqlite_metadata(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            \"\"\"
            CREATE TABLE IF NOT EXISTS openopps_tables (
                table_name TEXT PRIMARY KEY,
                table_title TEXT NOT NULL,
                table_description TEXT NOT NULL,
                csv_path TEXT NOT NULL,
                parquet_path TEXT NOT NULL
            )
            \"\"\"
        )
        conn.execute(
            \"\"\"
            CREATE TABLE IF NOT EXISTS openopps_columns (
                table_name TEXT NOT NULL,
                column_name TEXT NOT NULL,
                column_title TEXT NOT NULL,
                column_description TEXT NOT NULL,
                logical_type TEXT NOT NULL,
                json_schema_type TEXT NOT NULL,
                required INTEGER NOT NULL,
                source_name TEXT,
                format TEXT,
                enum_json TEXT,
                examples_json TEXT,
                default_json TEXT,
                PRIMARY KEY (table_name, column_name)
            )
            \"\"\"
        )
        conn.execute("DELETE FROM openopps_columns")
        conn.execute("DELETE FROM openopps_tables")
        conn.executemany(
            \"\"\"
            INSERT INTO openopps_tables (
                table_name,
                table_title,
                table_description,
                csv_path,
                parquet_path
            ) VALUES (
                :table_name,
                :table_title,
                :table_description,
                :csv_path,
                :parquet_path
            )
            \"\"\",
            OPENOPPS_TABLE_ROWS,
        )
        conn.executemany(
            \"\"\"
            INSERT INTO openopps_columns (
                table_name,
                column_name,
                column_title,
                column_description,
                logical_type,
                json_schema_type,
                required,
                source_name,
                format,
                enum_json,
                examples_json,
                default_json
            ) VALUES (
                :table_name,
                :column_name,
                :column_title,
                :column_description,
                :logical_type,
                :json_schema_type,
                :required,
                :source_name,
                :format,
                :enum_json,
                :examples_json,
                :default_json
            )
            \"\"\",
            OPENOPPS_COLUMN_ROWS,
        )

def write_table_csv(conn: sqlite3.Connection, table_name: str, csv_path: Path) -> None:
    cursor = conn.execute(f'SELECT * FROM "{table_name}"')
    headers = [column[0] for column in cursor.description]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\\n")
        writer.writerow(headers)
        while rows := cursor.fetchmany(10_000):
            writer.writerows(rows)

def write_full_table_exports(db_path: Path) -> None:
    import polars as pl

    csv_dir = OUTPUT_DIR / CSV_DIR
    parquet_dir = OUTPUT_DIR / PARQUET_DIR
    csv_dir.mkdir(parents=True, exist_ok=True)
    parquet_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        for table in OPENOPPS_TABLE_ROWS:
            table_name = table["table_name"]
            csv_path = csv_dir / f"{table_name}.csv"
            parquet_path = parquet_dir / f"{table_name}.parquet"
            print(f"Exporting {table_name}...", flush=True)
            write_table_csv(conn, table_name, csv_path)
            pl.scan_csv(
                csv_path,
                infer_schema_length=1000,
                low_memory=True,
            ).sink_parquet(parquet_path)

def project_sqlite_for_kaggle_indexer(db_path: Path) -> dict:
    projection_columns = (
        ("job_versions", "description_html"),
        ("job_versions", "job_description"),
        ("job_payload_snapshots", "payload"),
    )
    total_rows = 0
    total_bytes = 0
    nulled_columns = []
    with sqlite3.connect(db_path) as conn:
        for table_name, column_name in projection_columns:
            row = conn.execute(
                f\"\"\"
                SELECT COUNT(*), COALESCE(SUM(length(CAST("{column_name}" AS blob))), 0)
                FROM "{table_name}"
                WHERE "{column_name}" IS NOT NULL
                \"\"\"
            ).fetchone()
            rows = int(row[0] or 0)
            bytes_removed = int(row[1] or 0)
            if rows:
                conn.execute(
                    f'UPDATE "{table_name}" SET "{column_name}" = NULL '
                    f'WHERE "{column_name}" IS NOT NULL'
                )
                nulled_columns.append(f"{table_name}.{column_name}")
                total_rows += rows
                total_bytes += bytes_removed
        conn.commit()
    if nulled_columns:
        print(
            "Prepared SQLite upload projection for Kaggle indexer:",
            json.dumps(
                {
                    "nulledColumns": nulled_columns,
                    "rows": total_rows,
                    "estimatedBytesRemoved": total_bytes,
                },
                sort_keys=True,
            ),
            flush=True,
        )
    return {"projected_rows": total_rows, "estimated_bytes_removed": total_bytes}

def normalize_sqlite_schema_for_kaggle_indexer(db_path: Path) -> int:
    replacements = (
        (re.compile(r"\\bVARCHAR(?:\\(\\d+\\))?\\b"), "TEXT"),
        (re.compile(r"\\bJSON\\b"), "TEXT"),
        (re.compile(r"\\bDATETIME\\b"), "TEXT"),
        (re.compile(r"\\bBOOLEAN\\b"), "INTEGER"),
        (re.compile(r"\\bFLOAT\\b"), "REAL"),
    )
    updated = 0
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT rowid, sql FROM sqlite_schema WHERE type = 'table' AND sql IS NOT NULL"
        ).fetchall()
        conn.execute("PRAGMA writable_schema = ON")
        try:
            for rowid, sql in rows:
                normalized = str(sql)
                for pattern, replacement in replacements:
                    normalized = pattern.sub(replacement, normalized)
                if normalized != sql:
                    conn.execute(
                        "UPDATE sqlite_schema SET sql = ? WHERE rowid = ?",
                        (normalized, rowid),
                    )
                    updated += 1
            if updated:
                schema_version = int(conn.execute("PRAGMA schema_version").fetchone()[0])
                conn.execute(f"PRAGMA schema_version = {schema_version + 1}")
        finally:
            conn.execute("PRAGMA writable_schema = OFF")
        conn.commit()
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
    if integrity.lower() != "ok":
        raise RuntimeError(
            f"SQLite schema normalization failed integrity_check: {integrity}"
        )
    if updated:
        print(
            "Normalized SQLite upload schema for Kaggle indexer:",
            json.dumps({"tables": updated}, sort_keys=True),
            flush=True,
        )
    return updated

def table_count(conn: sqlite3.Connection, table_name: str) -> int:
    try:
        return int(conn.execute(f'SELECT count(*) FROM "{table_name}"').fetchone()[0])
    except sqlite3.Error:
        return 0

def snapshot_quality_report() -> dict:
    hard_blockers = []
    counts = {}
    with sqlite3.connect(DB_PATH) as conn:
        for table in OPENOPPS_TABLE_ROWS:
            table_name = table["table_name"]
            counts[table_name] = table_count(conn, table_name)

    required_paths = [
        "dataset-cover-image.png",
        "dataset-metadata.json",
        *PUBLIC_UPLOAD_DATA_FILES,
    ]
    required_files = []
    for relative_path in required_paths:
        path = OUTPUT_DIR / relative_path
        item = {
            "path": relative_path,
            "exists": path.exists(),
            "sizeBytes": path.stat().st_size if path.exists() else 0,
        }
        required_files.append(item)
        if not item["exists"]:
            hard_blockers.append(f"missing_required_file:{relative_path}")
        elif item["sizeBytes"] == 0:
            hard_blockers.append(f"empty_required_file:{relative_path}")

    if counts.get("jobs", 0) == 0 and not os.environ.get("OPENOPPS_EMPTY_SNAPSHOT_EXPLANATION"):
        hard_blockers.append("missing_current_job_evidence")
    if counts.get("job_versions", 0) > 0:
        if counts.get("job_version_skills", 0) == 0:
            hard_blockers.append("missing_job_version_skill_rows")
        if counts.get("job_version_skill_keywords", 0) == 0:
            hard_blockers.append("missing_job_version_skill_keyword_rows")
    if counts.get("openopps_tables") != len(OPENOPPS_TABLE_ROWS):
        hard_blockers.append("missing_openopps_table_metadata")
    if counts.get("openopps_columns", 0) <= 0:
        hard_blockers.append("missing_openopps_column_metadata")

    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "status": "fail" if hard_blockers else "pass",
        "hardBlockers": hard_blockers,
        "warnings": [],
        "counts": counts,
        "requiredFiles": required_files,
        "syncMetrics": read_json(OUTPUT_DIR / "sync_metrics.json"),
        "statusSummary": read_json(OUTPUT_DIR / "status.json"),
        "coverageSummary": read_json(OUTPUT_DIR / "coverage.json"),
    }

def prune_private_upload_files() -> None:
    for relative_path in (
        "sync_metrics.json",
        "status.json",
        "coverage.json",
        "snapshot-quality.json",
        "sync_stderr.txt",
        "generate_kaggle_metadata.py",
    ):
        path = OUTPUT_DIR / relative_path
        if path.exists():
            path.unlink()
    shutil.rmtree(OUTPUT_DIR / "_manager-unused", ignore_errors=True)
    project_sqlite_for_kaggle_indexer(DB_PATH)
    normalize_sqlite_schema_for_kaggle_indexer(DB_PATH)
    finalize_sqlite_for_upload(DB_PATH)

def write_public_bundle() -> dict:
    write_dataset_metadata()
    write_sqlite_metadata(DB_PATH)
    checkpoint_sqlite(DB_PATH)
    write_full_table_exports(DB_PATH)
    project_sqlite_for_kaggle_indexer(DB_PATH)
    normalize_sqlite_schema_for_kaggle_indexer(DB_PATH)
    finalize_sqlite_for_upload(DB_PATH)
    quality = snapshot_quality_report()
    write_json(OUTPUT_DIR / "snapshot-quality.json", quality)
    if quality["status"] != "pass":
        blockers = "; ".join(quality["hardBlockers"]) or "unknown quality failure"
        raise RuntimeError(f"Snapshot quality gate failed: {blockers}")
    prune_private_upload_files()
    return quality

def update_kaggle_dataset_file_metadata(dataset_basics: dict | None = None) -> None:
    from kaggle.api.kaggle_api_extended import KaggleApi
    from kagglesdk.datasets.types.dataset_api_service import (
        ApiUpdateDatasetMetadataRequest,
    )
    from kagglesdk.datasets.types.dataset_types import (
        DatasetSettings,
        DatasetSettingsFile,
        DatasetSettingsFileColumn,
    )

    metadata_path = OUTPUT_DIR / "dataset-metadata.json"
    metadata = json.loads(metadata_path.read_text())
    resources = metadata.get("resources") or []
    if not resources:
        raise RuntimeError(f"No Kaggle resources found in {metadata_path}")

    api = KaggleApi()
    api.authenticate()

    settings = DatasetSettings()
    settings.title = str(metadata.get("title") or "")
    settings.subtitle = str(metadata.get("subtitle") or "")
    settings.description = str(metadata.get("description") or "")
    settings.is_private = bool(metadata.get("isPrivate", False))
    settings.licenses = [
        api._new_license(str(license_data["name"]))
        for license_data in metadata.get("licenses", [])
        if license_data.get("name")
    ]
    settings.keywords = [str(keyword) for keyword in metadata.get("keywords", [])]
    settings.expected_update_frequency = str(
        metadata.get("expectedUpdateFrequency") or "not specified"
    )
    settings.user_specified_sources = str(metadata.get("userSpecifiedSources") or "")
    settings.data = [
        _dataset_settings_file(
            resource,
            DatasetSettingsFile,
            DatasetSettingsFileColumn,
            base_dir=OUTPUT_DIR,
        )
        for resource in resources
    ]

    owner_slug, dataset_slug = str(metadata.get("id") or DATASET_ID).split("/", 1)
    request = ApiUpdateDatasetMetadataRequest()
    request.owner_slug = owner_slug
    request.dataset_slug = dataset_slug
    request.settings = settings

    try:
        with api.build_kaggle_client() as kaggle:
            response = kaggle.datasets.dataset_api_client.update_dataset_metadata(request)
        errors = getattr(response, "errors", None) or []
        if errors:
            raise RuntimeError(f"Kaggle dataset metadata update failed: {errors}")
        print(f"Updated Kaggle public dataset metadata for {len(settings.data or [])} public files.")
    except Exception as exc:
        print(
            "Kaggle public dataset metadata update failed; continuing with "
            f"live databundle metadata repair: {type(exc).__name__}"
        )

    if dataset_basics is None:
        session, headers = kaggle_internal_metadata_session()
        dataset_basics = kaggle_dataset_basics(session, headers)
    update_kaggle_databundle_metadata_external(metadata, dataset_basics)

def _dataset_settings_file(
    resource,
    dataset_settings_file_cls,
    dataset_settings_file_column_cls,
    *,
    base_dir=None,
):
    file_metadata = dataset_settings_file_cls()
    file_metadata.name = str(resource["path"])
    file_metadata.description = str(resource.get("description") or "")
    if base_dir is not None:
        file_path = Path(base_dir) / str(resource["path"])
        if file_path.exists():
            file_metadata.total_bytes = file_path.stat().st_size
    columns = []
    for field in resource.get("schema", {}).get("fields", []):
        column = dataset_settings_file_column_cls()
        column.name = str(field["name"])
        column.description = str(field.get("description") or "")
        column.type = str(field.get("type") or "")
        columns.append(column)
    file_metadata.columns = columns
    return file_metadata

def kaggle_basic_auth_header() -> str:
    username = os.environ.get("KAGGLE_USERNAME", "").strip()
    key = os.environ.get("KAGGLE_KEY", "").strip()
    token = os.environ.get("KAGGLE_API_TOKEN", "").strip()
    if (not username or not key) and token:
        try:
            token_data = json.loads(token)
        except json.JSONDecodeError:
            token_data = {}
        username = username or str(token_data.get("username") or "").strip()
        key = key or str(token_data.get("key") or "").strip()
    if not username or not key:
        raise RuntimeError("Kaggle username/key credentials are required for metadata repair.")
    encoded = base64.b64encode(f"{username}:{key}".encode()).decode()
    return f"Basic {encoded}"

def kaggle_internal_metadata_session():
    import requests

    owner_slug, dataset_slug = DATASET_ID.split("/", 1)
    session = requests.Session()
    response = session.get(
        f"https://www.kaggle.com/datasets/{owner_slug}/{dataset_slug}",
        timeout=60,
    )
    response.raise_for_status()
    xsrf_token = session.cookies.get("XSRF-TOKEN")
    if not xsrf_token:
        raise RuntimeError("Kaggle XSRF token cookie was not returned for metadata repair.")
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": kaggle_basic_auth_header(),
        "X-XSRF-TOKEN": xsrf_token,
    }
    return session, headers

def kaggle_internal_post(session, headers: dict[str, str], route: str, body: dict) -> dict:
    response = session.post(
        f"https://www.kaggle.com/api/i/{route}",
        headers=headers,
        json=body,
        timeout=120,
    )
    if not response.ok:
        raise RuntimeError(
            f"Kaggle internal metadata API failed for {route}: "
            f"{response.status_code} {response.text[:500]}"
        )
    return response.json()

def kaggle_dataset_basics(
    session,
    headers: dict[str, str],
    *,
    dataset_version_number: int | None = None,
) -> dict:
    owner_slug, dataset_slug = DATASET_ID.split("/", 1)
    body = {
        "ownerSlug": owner_slug,
        "datasetSlug": dataset_slug,
    }
    if dataset_version_number is not None:
        body["datasetVersionNumber"] = dataset_version_number
    return kaggle_internal_post(
        session,
        headers,
        "datasets.DatasetDetailService/GetDatasetBasics",
        body,
    )

def wait_for_new_live_dataset_version(previous_version: int | None) -> dict:
    session, headers = kaggle_internal_metadata_session()
    deadline = time.time() + float(os.environ.get("OPENOPPS_KAGGLE_METADATA_WAIT_SECONDS", "900"))
    while True:
        basics = kaggle_dataset_basics(session, headers)
        current_version = int(basics.get("datasetVersionNumber") or 0)
        data = basics.get("data") or {}
        if (
            data.get("firestorePath")
            and data.get("versionId")
            and (previous_version is None or current_version > previous_version)
        ):
            print(
                "Kaggle live dataset version ready for metadata repair:",
                json.dumps(
                    {
                        "datasetVersionNumber": current_version,
                        "datasetVersionId": basics.get("datasetVersionId"),
                        "databundleVersionId": data.get("versionId"),
                    },
                    sort_keys=True,
                ),
            )
            return basics
        if time.time() >= deadline:
            raise TimeoutError(
                "Timed out waiting for Kaggle to expose the newly published dataset version."
            )
        print(
            "Waiting for new Kaggle dataset version before metadata repair:",
            json.dumps(
                {
                    "previousVersionNumber": previous_version,
                    "currentVersionNumber": current_version,
                },
                sort_keys=True,
            ),
        )
        time.sleep(15)

def kaggle_databundle_column_type(field_type: str) -> tuple[str, str]:
    normalized = (field_type or "string").lower()
    if normalized in {"datetime", "date", "time"}:
        return "DATE_TIME", "EXTENDED_DATA_TYPE_UNSPECIFIED"
    if normalized in {"integer", "int"}:
        return "NUMERIC", "INTEGER"
    if normalized in {"numeric", "number", "float", "decimal"}:
        return "NUMERIC", "DECIMAL"
    if normalized == "boolean":
        return "BOOLEAN", "EXTENDED_DATA_TYPE_UNSPECIFIED"
    if normalized == "url":
        return "STRING", "URL"
    if normalized == "uuid":
        return "STRING", "UUID"
    if normalized == "id":
        return "STRING", "ID"
    return "STRING", "EXTENDED_DATA_TYPE_UNSPECIFIED"

def kaggle_column_type_from_field(field: dict) -> str:
    field_type = str(field.get("type") or "").lower()
    field_name = str(field.get("name") or "")
    field_format = str(field.get("format") or "")
    if field_format in {"date-time", "date"}:
        return "datetime"
    if field_format in {"uri", "url"} or field_name.endswith("_url"):
        return "url"
    if field_name == "id" or field_name.endswith("_id") or field_name.endswith("_key"):
        return "id"
    if field_type in {"boolean", "datetime", "id", "integer", "numeric", "number", "url", "uuid"}:
        return field_type
    if field_type == "string":
        return "string"
    schema_types = {
        item.strip()
        for item in str(field.get("jsonSchemaType") or "").split("|")
        if item.strip() and item.strip() != "null"
    }
    if "boolean" in schema_types:
        return "boolean"
    if "integer" in schema_types:
        return "integer"
    if "number" in schema_types:
        return "numeric"
    return "string"

def update_databundle_entity_metadata(
    post,
    verification_info: dict,
    *,
    firestore_path: str,
    description: str,
    fields: list[dict],
) -> tuple[dict, int]:
    columns = []
    fields_by_name = {str(field["name"]): field for field in fields}
    if fields_by_name:
        live_columns = post(
            "datasets.databundles.DatabundleService/GetDatabundleExternalColumns",
            {
                "verificationInfo": verification_info,
                "firestorePath": firestore_path,
            },
        ).get("columns") or []
        for live_column in live_columns:
            field = fields_by_name.get(str(live_column.get("name") or ""))
            column_type, extended_type = kaggle_databundle_column_type(
                kaggle_column_type_from_field(field or {})
            )
            column = dict(live_column)
            column.update(
                {
                    "description": str((field or {}).get("description") or ""),
                    "type": column_type,
                    "extendedType": extended_type,
                }
            )
            columns.append(column)
    response = post(
        "datasets.databundles.DatabundleService/UpdateDatabundleMetadataExternal",
        {
            "verificationInfo": verification_info,
            "firestorePath": firestore_path,
            "description": description,
            "columns": columns,
        },
    )
    return response, len(columns)

def update_sqlite_table_metadata_external(
    post,
    verification_info: dict,
    sqlite_file_info: dict,
) -> tuple[int, int, dict]:
    sqlite_info = sqlite_file_info.get("sqliteInfo") or {}
    table_count = int((sqlite_info.get("tables") or {}).get("totalChildren") or 0)
    if table_count == 0:
        raise RuntimeError(
            "Kaggle SQLite indexer did not index openoppsdb.sqlite; "
            "no sqliteInfo.tables were exposed for live table metadata repair."
        )
    children = post(
        "datasets.databundles.DatabundleService/GetDatabundleExternalChildren",
        {
            "verificationInfo": verification_info,
            "firestorePath": sqlite_file_info["path"],
            "offset": 0,
            "count": max(table_count, len(SQLITE_TABLE_METADATA), 200),
            "depth": 1,
            "enforceMaxDepthConstraint": False,
        },
    )
    live_tables = {
        str(table_info.get("name") or ""): table_info
        for table_info in children.get("tables") or []
    }
    expected_tables = {str(table["name"]): table for table in SQLITE_TABLE_METADATA}
    missing_tables = sorted(set(expected_tables) - set(live_tables))
    if missing_tables:
        raise RuntimeError(
            "Kaggle SQLite indexer omitted expected openoppsdb tables: "
            + ", ".join(missing_tables)
        )
    updated_tables = 0
    updated_columns = 0
    rating = {}
    for table_name, table_metadata in expected_tables.items():
        live_table = live_tables[table_name]
        response, column_count = update_databundle_entity_metadata(
            post,
            verification_info,
            firestore_path=str(live_table["path"]),
            description=str(table_metadata.get("description") or ""),
            fields=list(table_metadata.get("schema", {}).get("fields", [])),
        )
        rating = response.get("usabilityRating") or rating
        updated_tables += 1
        updated_columns += column_count
    return updated_tables, updated_columns, rating

def kaggle_databundle_files(session, headers: dict[str, str], basics: dict) -> dict[str, dict]:
    data = basics.get("data") or {}
    root_path = data.get("firestorePath")
    version_id = data.get("versionId")
    dataset_id = basics.get("datasetId")
    if not root_path or not version_id or not dataset_id:
        raise RuntimeError(f"Missing Kaggle databundle identity in dataset basics: {basics}")
    verification_info = {
        "databundleVersionId": version_id,
        "datasetId": dataset_id,
    }
    paths = [
        root_path,
        f"{root_path}/directories/exports/directories/csv",
        f"{root_path}/directories/exports/directories/parquet",
    ]
    files: dict[str, dict] = {}
    for firestore_path in paths:
        children = kaggle_internal_post(
            session,
            headers,
            "datasets.databundles.DatabundleService/GetDatabundleExternalChildren",
            {
                "verificationInfo": verification_info,
                "firestorePath": firestore_path,
                "offset": 0,
                "count": 200,
                "depth": 1,
                "enforceMaxDepthConstraint": False,
            },
        )
        for file_info in children.get("files") or []:
            relative_url = file_info.get("relativeUrl")
            if relative_url:
                files[str(relative_url)] = file_info
    return files

def update_kaggle_databundle_metadata_external(metadata: dict, basics: dict) -> None:
    session, headers = kaggle_internal_metadata_session()
    def post(route: str, body: dict) -> dict:
        return kaggle_internal_post(session, headers, route, body)

    data = basics.get("data") or {}
    verification_info = {
        "databundleVersionId": data.get("versionId"),
        "datasetId": basics.get("datasetId"),
    }
    files = kaggle_databundle_files(session, headers, basics)
    updated_files = 0
    updated_columns = 0
    updated_sqlite_tables = 0
    rating = {}
    for resource in metadata.get("resources") or []:
        resource_path = str(resource["path"])
        file_info = files.get(resource_path)
        if not file_info:
            raise RuntimeError(f"Kaggle live databundle file not found: {resource_path}")
        response, column_count = update_databundle_entity_metadata(
            post,
            verification_info,
            firestore_path=str(file_info["path"]),
            description=str(resource.get("description") or ""),
            fields=list(resource.get("schema", {}).get("fields", [])),
        )
        rating = response.get("usabilityRating") or {}
        updated_files += 1
        updated_columns += column_count
        if resource_path == "openoppsdb.sqlite":
            sqlite_deadline = time.time() + float(
                os.environ.get("OPENOPPS_KAGGLE_SQLITE_INDEX_WAIT_SECONDS", "1200")
            )
            while True:
                try:
                    table_count, table_column_count, table_rating = (
                        update_sqlite_table_metadata_external(
                            post,
                            verification_info,
                            file_info,
                        )
                    )
                    break
                except RuntimeError as exc:
                    if "Kaggle SQLite indexer did not index" not in str(exc):
                        raise
                    if time.time() >= sqlite_deadline:
                        raise
                    print(
                        "Waiting for Kaggle SQLite indexer metadata:",
                        json.dumps(
                            {
                                "path": resource_path,
                                "reason": str(exc),
                            },
                            sort_keys=True,
                        ),
                    )
                    time.sleep(30)
                    files = kaggle_databundle_files(session, headers, basics)
                    file_info = files.get(resource_path)
                    if not file_info:
                        raise RuntimeError(
                            f"Kaggle live databundle file not found: {resource_path}"
                        )
            updated_sqlite_tables += table_count
            updated_columns += table_column_count
            rating = table_rating or rating
    print(
        "Updated Kaggle live databundle metadata:",
        json.dumps(
            {
                "files": updated_files,
                "sqliteTables": updated_sqlite_tables,
                "columns": updated_columns,
                "usabilityScore": rating.get("score"),
                "columnDescriptionScore": rating.get("columnDescriptionScore"),
                "fileDescriptionScore": rating.get("fileDescriptionScore"),
            },
            sort_keys=True,
        ),
    )

require_kaggle_credentials()
install_openopps()
copy_latest_input_db()
download_dataset_assets()
""".replace("__OPENOPPS_SYNC_ENV_DEFAULTS__", sync_env_defaults).replace(
        "__SKILL_CATALOG__",
        skill_catalog,
    ).replace(
        "__DATASET_METADATA__",
        notebook_dataset_metadata,
    ).replace(
        "__SQLITE_TABLE_METADATA__",
        sqlite_table_metadata,
    ).replace(
        "__OPENOPPS_TABLE_ROWS__",
        table_rows,
    ).replace(
        "__OPENOPPS_COLUMN_ROWS__",
        column_rows,
    ).replace(
        "__PUBLIC_UPLOAD_DATA_FILES__",
        public_upload_data_files,
    ).replace(
        "__OPENOPPS_KAGGLE_SYNC_TIMEOUT_SECONDS__",
        str(NOTEBOOK_SYNC_TIMEOUT_SECONDS),
    ).replace(
        "__OPENOPPS_KAGGLE_JOB_ROUTE_LIMIT__",
        str(NOTEBOOK_JOB_ROUTE_LIMIT),
    )


def _notebook_table_rows() -> list[dict[str, str]]:
    return [
        {
            "table_name": table.name,
            "table_title": _title_from_name(table.name),
            "table_description": table.description,
            "csv_path": f"{CSV_DIR}/{table.name}.csv",
            "parquet_path": f"{PARQUET_DIR}/{table.name}.parquet",
        }
        for table in TABLES
    ]


def _notebook_column_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for table in TABLES:
        for field in _model_schema_metadata(table.model)["fields"]:
            rows.append(
                {
                    "table_name": table.name,
                    "column_name": field["name"],
                    "column_title": field["title"],
                    "column_description": field["description"],
                    "logical_type": field.get("logicalType", field["type"]),
                    "json_schema_type": field["jsonSchemaType"],
                    "required": int(field["required"]),
                    "source_name": field.get("sourceName"),
                    "format": field.get("format"),
                    "enum_json": _json_or_none(field.get("enum")),
                    "examples_json": _json_or_none(field.get("examples")),
                    "default_json": _json_or_none(field.get("default")),
                }
            )
    return rows


def _notebook_sync_source() -> str:
    return """openopps_env = os.environ.copy()
openopps_env["OPENOPPS_DB_URL"] = f"sqlite:///{DB_PATH}"
openopps_env["OPENOPPS_CACHE_ENABLED"] = "false"
for key, value in OPENOPPS_SYNC_ENV_DEFAULTS.items():
    openopps_env.setdefault(key, value)

run(["openopps", "admin", "db", "init"], env=openopps_env)
print(f"OpenOpps bounded jobs sync timeout: {KAGGLE_SYNC_TIMEOUT_SECONDS:g}s")
print(f"OpenOpps bounded jobs sync route limit: {KAGGLE_JOB_ROUTE_LIMIT}")
sync_metrics = run_sync_metrics(
    OUTPUT_DIR / "sync_metrics.json",
    env=openopps_env,
    timeout_seconds=KAGGLE_SYNC_TIMEOUT_SECONDS,
)
skill_backfill = backfill_openopps_skill_tables(DB_PATH)
print("OpenOpps skill backfill:", json.dumps(skill_backfill, sort_keys=True))
status = run_json(
    ["openopps", "status", "--json"],
    OUTPUT_DIR / "status.json",
    env=openopps_env,
)
coverage = run_json(
    ["openopps", "providers", "coverage", "--json"],
    OUTPUT_DIR / "coverage.json",
    env=openopps_env,
)
"""


def _notebook_export_source() -> str:
    return """quality = write_public_bundle()
print("OpenOpps snapshot quality:", json.dumps({
    "status": quality["status"],
    "hardBlockers": quality["hardBlockers"],
    "warnings": quality["warnings"],
    "counts": {
        "jobs": quality["counts"].get("jobs"),
        "job_versions": quality["counts"].get("job_versions"),
        "job_version_skills": quality["counts"].get("job_version_skills"),
        "job_version_skill_keywords": quality["counts"].get("job_version_skill_keywords"),
        "openopps_tables": quality["counts"].get("openopps_tables"),
        "openopps_columns": quality["counts"].get("openopps_columns"),
    },
}, sort_keys=True))

for path in sorted(OUTPUT_DIR.iterdir()):
    print(path.name, path.stat().st_size)
"""


def _notebook_publish_source() -> str:
    return """message = f"Scheduled OpenOpps active-job snapshot {datetime.now(UTC).isoformat()}"
require_kaggle_credentials()
metadata_session, metadata_headers = kaggle_internal_metadata_session()
previous_basics = kaggle_dataset_basics(metadata_session, metadata_headers)
previous_version = int(previous_basics.get("datasetVersionNumber") or 0)

run([
    "kaggle",
    "datasets",
    "version",
    "-p",
    str(OUTPUT_DIR),
    "-m",
    message,
    "-q",
    "-t",
    "-r",
    "zip",
])
published_basics = wait_for_new_live_dataset_version(previous_version)
update_kaggle_dataset_file_metadata(published_basics)
run(["kaggle", "datasets", "status", DATASET_ID, "--format", "json"])
run(["kaggle", "datasets", "files", DATASET_ID, "--page-size", "200"])
"""


def _resource_metadata(resource: Resource) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "profile": (
            "tabular-data-resource"
            if resource.format == "csv"
            else "data-resource"
        ),
        "name": resource.name,
        "path": resource.path,
        "title": _title_from_name(resource.name),
        "description": resource.description,
        "format": resource.format,
        "mediatype": resource.mediatype,
    }
    if resource.model is not None:
        metadata["title"] = resource.model.__name__
        metadata["schema"] = _model_schema_metadata(resource.model)
    if resource.tables:
        metadata["tables"] = [_table_metadata(table) for table in resource.tables]
    return metadata


def _kaggle_resource_metadata(resource: Resource) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "name": resource.name,
        "path": resource.path,
        "title": _title_from_name(resource.name),
        "description": resource.description,
    }
    if resource.model is not None:
        metadata["schema"] = {
            "fields": [
                _kaggle_field_metadata(field)
                for field in _model_schema_metadata(resource.model)["fields"]
            ]
        }
    if resource.tables:
        metadata["tables"] = [_kaggle_table_metadata(table) for table in resource.tables]
    return metadata


def _kaggle_file_metadata(
    resource: Resource, *, base_dir: Path | None = None
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "name": resource.path,
        "description": resource.description,
        "columns": [],
    }
    if base_dir is not None:
        file_path = base_dir / resource.path
        if file_path.exists():
            metadata["totalBytes"] = file_path.stat().st_size
    if resource.model is not None:
        metadata["columns"] = [
            {
                "name": field["name"],
                "description": str(field["description"]),
                "type": _kaggle_field_type(field),
            }
            for field in _model_schema_metadata(resource.model)["fields"]
        ]
    return metadata


def _kaggle_dataset_status(dataset_id: str) -> dict[str, Any]:
    completed = subprocess.run(
        ["kaggle", "datasets", "status", dataset_id, "--format", "json"],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _wait_live_dataset_ready(
    dataset_id: str,
    *,
    min_version: int | None,
    timeout_seconds: float,
    poll_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_status: dict[str, Any] = {}
    while True:
        last_status = _kaggle_dataset_status(dataset_id)
        status = str(last_status.get("status") or "").lower()
        version = int(last_status.get("current_version_number") or 0)
        version_ok = min_version is None or version >= min_version
        if status == "ready" and version_ok:
            print(
                "Kaggle dataset is ready: "
                + json.dumps(
                    {
                        "dataset": dataset_id,
                        "status": status,
                        "version": version,
                    },
                    sort_keys=True,
                )
            )
            return last_status
        if time.monotonic() >= deadline:
            raise RuntimeError(
                "Timed out waiting for Kaggle dataset to become ready: "
                + json.dumps(
                    {
                        "dataset": dataset_id,
                        "minVersion": min_version,
                        "lastStatus": last_status,
                    },
                    sort_keys=True,
                )
            )
        print(
            "Waiting for Kaggle dataset readiness: "
            + json.dumps(
                {
                    "dataset": dataset_id,
                    "minVersion": min_version,
                    "status": status,
                    "version": version,
                },
                sort_keys=True,
            )
        )
        time.sleep(max(poll_seconds, 1.0))


def _update_live_file_metadata(
    metadata_path: Path,
    *,
    use_browser_cookies: bool = False,
    sqlite_index_timeout_seconds: float = 1200.0,
    sqlite_index_poll_seconds: float = 30.0,
) -> None:
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
        from kagglesdk.datasets.types.dataset_api_service import (
            ApiUpdateDatasetMetadataRequest,
        )
        from kagglesdk.datasets.types.dataset_types import (
            DatasetSettings,
            DatasetSettingsFile,
            DatasetSettingsFileColumn,
        )
    except Exception as exc:  # pragma: no cover - exercised in Kaggle runtime.
        raise RuntimeError(
            "Updating live Kaggle file metadata requires the kaggle package. "
            "Run with `uv run --with kaggle python scripts/generate_kaggle_metadata.py "
            "--update-live-file-metadata` or from the Kaggle manager notebook."
        ) from exc

    metadata = _read_json(metadata_path)
    resources = metadata.get("resources") or []
    if not resources:
        raise ValueError(f"No resources found in {metadata_path}")

    api = KaggleApi()
    api.authenticate()

    settings = DatasetSettings()
    settings.title = str(metadata.get("title") or "")
    settings.subtitle = str(metadata.get("subtitle") or "")
    settings.description = str(metadata.get("description") or "")
    settings.is_private = bool(metadata.get("isPrivate", False))
    settings.licenses = [
        api._new_license(str(license_data["name"]))  # noqa: SLF001
        for license_data in metadata.get("licenses", [])
        if license_data.get("name")
    ]
    settings.keywords = [str(keyword) for keyword in metadata.get("keywords", [])]
    settings.expected_update_frequency = str(
        metadata.get("expectedUpdateFrequency") or "not specified"
    )
    settings.user_specified_sources = str(metadata.get("userSpecifiedSources") or "")
    settings.data = [
        _dataset_settings_file(
            resource,
            DatasetSettingsFile,
            DatasetSettingsFileColumn,
            base_dir=metadata_path.parent,
        )
        for resource in resources
    ]

    owner_slug, dataset_slug = str(metadata.get("id") or DATASET_ID).split("/", 1)
    request = ApiUpdateDatasetMetadataRequest()
    request.owner_slug = owner_slug
    request.dataset_slug = dataset_slug
    request.settings = settings

    try:
        with api.build_kaggle_client() as kaggle:
            response = kaggle.datasets.dataset_api_client.update_dataset_metadata(request)
        errors = getattr(response, "errors", None) or []
        if errors:
            raise RuntimeError(f"Kaggle dataset metadata update failed: {errors}")
        print(f"Updated Kaggle file metadata for {len(settings.data or [])} public files.")
    except Exception as exc:
        if not use_browser_cookies:
            raise
        print(
            "Kaggle file metadata update failed; continuing with "
            f"browser-cookie databundle metadata repair: {type(exc).__name__}"
        )
    if use_browser_cookies:
        _update_live_databundle_metadata_with_browser_cookies(
            metadata,
            sqlite_index_timeout_seconds=sqlite_index_timeout_seconds,
            sqlite_index_poll_seconds=sqlite_index_poll_seconds,
        )


def _dataset_settings_file(
    resource: dict[str, Any],
    dataset_settings_file_cls: type,
    dataset_settings_file_column_cls: type,
    *,
    base_dir: Path | None = None,
) -> Any:
    file_metadata = dataset_settings_file_cls()
    file_metadata.name = str(resource["path"])
    file_metadata.description = str(resource.get("description") or "")
    if base_dir is not None:
        file_path = base_dir / str(resource["path"])
        if file_path.exists():
            file_metadata.total_bytes = file_path.stat().st_size
    columns = []
    for field in resource.get("schema", {}).get("fields", []):
        column = dataset_settings_file_column_cls()
        column.name = str(field["name"])
        column.description = str(field.get("description") or "")
        column.type = str(field.get("type") or "")
        columns.append(column)
    file_metadata.columns = columns
    return file_metadata


def _kaggle_databundle_column_type(field_type: str) -> tuple[str, str]:
    normalized = (field_type or "string").lower()
    if normalized in {"datetime", "date", "time"}:
        return "DATE_TIME", "EXTENDED_DATA_TYPE_UNSPECIFIED"
    if normalized in {"integer", "int"}:
        return "NUMERIC", "INTEGER"
    if normalized in {"numeric", "number", "float", "decimal"}:
        return "NUMERIC", "DECIMAL"
    if normalized == "boolean":
        return "BOOLEAN", "EXTENDED_DATA_TYPE_UNSPECIFIED"
    if normalized == "url":
        return "STRING", "URL"
    if normalized == "uuid":
        return "STRING", "UUID"
    if normalized == "id":
        return "STRING", "ID"
    return "STRING", "EXTENDED_DATA_TYPE_UNSPECIFIED"


def _kaggle_column_type_from_field(field: dict[str, Any]) -> str:
    field_type = str(field.get("type") or "").lower()
    field_name = str(field.get("name") or "")
    field_format = str(field.get("format") or "")
    if field_format in {"date-time", "date"}:
        return "datetime"
    if field_format in {"uri", "url"} or field_name.endswith("_url"):
        return "url"
    if field_name == "id" or field_name.endswith("_id") or field_name.endswith("_key"):
        return "id"
    if field_type in {"boolean", "datetime", "id", "integer", "numeric", "number", "url", "uuid"}:
        return field_type
    if field_type == "string":
        return "string"
    return _kaggle_field_type(field)


def _sqlite_table_metadata_by_name() -> dict[str, dict[str, Any]]:
    return {table.name: _table_metadata(table) for table in TABLES}


def _update_databundle_entity_metadata(
    post,
    verification_info: dict[str, Any],
    *,
    firestore_path: str,
    description: str,
    fields: list[dict[str, Any]],
) -> tuple[dict[str, Any], int]:
    columns = []
    fields_by_name = {str(field["name"]): field for field in fields}
    if fields_by_name:
        live_columns = post(
            "datasets.databundles.DatabundleService/GetDatabundleExternalColumns",
            {
                "verificationInfo": verification_info,
                "firestorePath": firestore_path,
            },
        ).get("columns") or []
        for live_column in live_columns:
            field = fields_by_name.get(str(live_column.get("name") or ""))
            column_type, extended_type = _kaggle_databundle_column_type(
                _kaggle_column_type_from_field(field or {})
            )
            column = dict(live_column)
            column.update(
                {
                    "description": str((field or {}).get("description") or ""),
                    "type": column_type,
                    "extendedType": extended_type,
                }
            )
            columns.append(column)
    response = post(
        "datasets.databundles.DatabundleService/UpdateDatabundleMetadataExternal",
        {
            "verificationInfo": verification_info,
            "firestorePath": firestore_path,
            "description": description,
            "columns": columns,
        },
    )
    return response, len(columns)


def _update_sqlite_table_metadata_external(
    post,
    verification_info: dict[str, Any],
    sqlite_file_info: dict[str, Any],
) -> tuple[int, int, dict[str, Any]]:
    sqlite_info = sqlite_file_info.get("sqliteInfo") or {}
    table_count = int((sqlite_info.get("tables") or {}).get("totalChildren") or 0)
    if table_count == 0:
        raise RuntimeError(
            "Kaggle SQLite indexer did not index openoppsdb.sqlite; "
            "no sqliteInfo.tables were exposed for live table metadata repair."
        )
    children = post(
        "datasets.databundles.DatabundleService/GetDatabundleExternalChildren",
        {
            "verificationInfo": verification_info,
            "firestorePath": sqlite_file_info["path"],
            "offset": 0,
            "count": max(table_count, len(TABLES), 200),
            "depth": 1,
            "enforceMaxDepthConstraint": False,
        },
    )
    live_tables = {
        str(table_info.get("name") or ""): table_info
        for table_info in children.get("tables") or []
    }
    expected_tables = _sqlite_table_metadata_by_name()
    missing_tables = sorted(set(expected_tables) - set(live_tables))
    if missing_tables:
        raise RuntimeError(
            "Kaggle SQLite indexer omitted expected openoppsdb tables: "
            + ", ".join(missing_tables)
        )
    updated_tables = 0
    updated_columns = 0
    rating: dict[str, Any] = {}
    for table_name, table_metadata in expected_tables.items():
        live_table = live_tables[table_name]
        response, column_count = _update_databundle_entity_metadata(
            post,
            verification_info,
            firestore_path=str(live_table["path"]),
            description=str(table_metadata.get("description") or ""),
            fields=list(table_metadata.get("schema", {}).get("fields", [])),
        )
        rating = response.get("usabilityRating") or rating
        updated_tables += 1
        updated_columns += column_count
    return updated_tables, updated_columns, rating


def _update_live_databundle_metadata_with_browser_cookies(
    metadata: dict[str, Any],
    *,
    sqlite_index_timeout_seconds: float = 1200.0,
    sqlite_index_poll_seconds: float = 30.0,
) -> None:
    try:
        import browser_cookie3
        import requests
    except Exception as exc:  # pragma: no cover - local publish helper only.
        raise RuntimeError(
            "Browser-cookie metadata repair requires `browser-cookie3` and "
            "`requests`. Run via `just kaggle-live-file-metadata`."
        ) from exc

    owner_slug, dataset_slug = str(metadata.get("id") or DATASET_ID).split("/", 1)
    dataset_url = f"https://www.kaggle.com/datasets/{owner_slug}/{dataset_slug}"
    session = requests.Session()
    session.cookies.update(browser_cookie3.chrome(domain_name="kaggle.com"))
    response = session.get(dataset_url, timeout=60)
    response.raise_for_status()
    xsrf_token = session.cookies.get("XSRF-TOKEN") or session.cookies.get("CSRF-TOKEN")
    if not xsrf_token:
        raise RuntimeError(
            "Kaggle browser session did not expose an XSRF token for metadata repair."
        )
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://www.kaggle.com",
        "Referer": dataset_url,
        "X-XSRF-TOKEN": xsrf_token,
    }

    def post(route: str, body: dict[str, Any]) -> dict[str, Any]:
        api_response = session.post(
            f"https://www.kaggle.com/api/i/{route}",
            headers=headers,
            json=body,
            timeout=120,
        )
        if not api_response.ok:
            raise RuntimeError(
                f"Kaggle internal metadata API failed for {route}: "
                f"{api_response.status_code} {api_response.text[:500]}"
            )
        return api_response.json()

    basics = post(
        "datasets.DatasetDetailService/GetDatasetBasics",
        {"ownerSlug": owner_slug, "datasetSlug": dataset_slug},
    )
    data = basics.get("data") or {}
    verification_info = {
        "databundleVersionId": data.get("versionId"),
        "datasetId": basics.get("datasetId"),
    }
    root_path = data.get("firestorePath")
    if (
        not root_path
        or not verification_info["databundleVersionId"]
        or not verification_info["datasetId"]
    ):
        raise RuntimeError(f"Missing Kaggle databundle identity: {basics}")

    def fetch_files() -> dict[str, dict[str, Any]]:
        files: dict[str, dict[str, Any]] = {}
        for firestore_path in (
            root_path,
            f"{root_path}/directories/exports/directories/csv",
            f"{root_path}/directories/exports/directories/parquet",
        ):
            children = post(
                "datasets.databundles.DatabundleService/GetDatabundleExternalChildren",
                {
                    "verificationInfo": verification_info,
                    "firestorePath": firestore_path,
                    "offset": 0,
                    "count": 200,
                    "depth": 1,
                    "enforceMaxDepthConstraint": False,
                },
            )
            for file_info in children.get("files") or []:
                relative_url = file_info.get("relativeUrl")
                if relative_url:
                    files[str(relative_url)] = file_info
        return files

    files = fetch_files()

    updated_files = 0
    updated_columns = 0
    updated_sqlite_tables = 0
    rating: dict[str, Any] = {}
    for resource in metadata.get("resources") or []:
        resource_path = str(resource["path"])
        file_info = files.get(resource_path)
        if not file_info:
            raise RuntimeError(f"Kaggle live databundle file not found: {resource_path}")
        update_response, column_count = _update_databundle_entity_metadata(
            post,
            verification_info,
            firestore_path=str(file_info["path"]),
            description=str(resource.get("description") or ""),
            fields=list(resource.get("schema", {}).get("fields", [])),
        )
        rating = update_response.get("usabilityRating") or rating
        updated_files += 1
        updated_columns += column_count
        if resource_path == DB_FILE:
            sqlite_deadline = time.monotonic() + sqlite_index_timeout_seconds
            while True:
                try:
                    table_count, table_column_count, table_rating = (
                        _update_sqlite_table_metadata_external(
                            post,
                            verification_info,
                            file_info,
                        )
                    )
                    break
                except RuntimeError as exc:
                    if "Kaggle SQLite indexer did not index" not in str(exc):
                        raise
                    if time.monotonic() >= sqlite_deadline:
                        raise
                    print(
                        "Waiting for Kaggle SQLite indexer metadata: "
                        + json.dumps(
                            {
                                "path": DB_FILE,
                                "reason": str(exc),
                            },
                            sort_keys=True,
                        )
                    )
                    time.sleep(max(sqlite_index_poll_seconds, 1.0))
                    files = fetch_files()
                    file_info = files.get(resource_path)
                    if not file_info:
                        raise RuntimeError(
                            f"Kaggle live databundle file not found: {resource_path}"
                        )
            updated_sqlite_tables += table_count
            updated_columns += table_column_count
            rating = table_rating or rating
    print(
        "Updated Kaggle live databundle metadata: "
        + json.dumps(
            {
                "files": updated_files,
                "sqliteTables": updated_sqlite_tables,
                "columns": updated_columns,
                "usabilityScore": rating.get("score"),
                "columnDescriptionScore": rating.get("columnDescriptionScore"),
                "fileDescriptionScore": rating.get("fileDescriptionScore"),
            },
            sort_keys=True,
        )
    )


def _kaggle_field_metadata(field: dict[str, Any]) -> dict[str, Any]:
    description = str(field["description"])
    return {
        "name": field["name"],
        "description": description,
        "type": _kaggle_field_type(field),
    }


def _kaggle_field_type(field: dict[str, Any]) -> str:
    field_name = str(field["name"])
    field_format = str(field.get("format") or "")
    logical_type = str(field.get("type") or "")
    schema_types = {
        item.strip()
        for item in str(field.get("jsonSchemaType") or "").split("|")
        if item.strip() and item.strip() != "null"
    }
    if field_format in {"date-time", "date"} or "datetime" in logical_type:
        return "datetime"
    if field_format in {"uri", "url"} or field_name.endswith("_url"):
        return "url"
    if field_name == "id" or field_name.endswith("_id") or field_name.endswith("_key"):
        return "id"
    if "boolean" in schema_types:
        return "boolean"
    if "integer" in schema_types:
        return "integer"
    if "number" in schema_types:
        return "numeric"
    return "string"


def _table_metadata(table: Table) -> dict[str, Any]:
    return {
        "name": table.name,
        "title": _title_from_name(table.name),
        "description": table.description,
        "schema": _model_schema_metadata(table.model),
    }


def _kaggle_table_metadata(table: Table) -> dict[str, Any]:
    return {
        "name": table.name,
        "title": _title_from_name(table.name),
        "description": table.description,
        "schema": {
            "fields": [
                _kaggle_field_metadata(field)
                for field in _model_schema_metadata(table.model)["fields"]
            ]
        },
    }


def _model_schema_metadata(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema(by_alias=False, mode="serialization")
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    return {
        "fields": [
            _field_metadata(
                field_name=field_name,
                field_schema=properties.get(field_name, {}),
                field_info=field_info,
                required=field_name in required,
            )
            for field_name, field_info in model.model_fields.items()
        ]
    }


def _field_metadata(
    *,
    field_name: str,
    field_schema: dict[str, Any],
    field_info: Any,
    required: bool,
) -> dict[str, Any]:
    description = _field_description(
        field_name=field_name,
        field_info=field_info,
        field_schema=field_schema,
    )
    constraints: dict[str, Any] = {}
    if required:
        constraints["required"] = True
    metadata: dict[str, Any] = {
        "name": field_name,
        "title": field_schema.get("title", _title_from_name(field_name)),
        "description": description,
        "type": _frictionless_field_type(
            field_name=field_name,
            field_schema=field_schema,
            field_info=field_info,
        ),
        "logicalType": _annotation_type(field_info.annotation),
        "jsonSchemaType": _json_schema_type(field_schema),
        "required": required,
    }
    if constraints:
        metadata["constraints"] = constraints
    alias = field_info.alias
    if alias and alias != field_name:
        metadata["sourceName"] = alias
    if field_schema.get("format"):
        metadata["format"] = field_schema["format"]
    if enum := _enum_values(field_schema):
        metadata["enum"] = enum
    if field_info.examples:
        metadata["examples"] = field_info.examples
    if field_info.default is not PydanticUndefined:
        metadata["default"] = field_info.default
    return metadata


def _frictionless_field_type(
    *,
    field_name: str,
    field_schema: dict[str, Any],
    field_info: Any,
) -> str:
    field_format = str(field_schema.get("format") or "")
    if field_format in {"date-time", "datetime"}:
        return "datetime"
    if field_format == "date":
        return "date"
    if field_format in {"uri", "url"} or field_name.endswith("_url"):
        return "string"

    schema_type = _json_schema_type(field_schema)
    schema_types = {
        item.strip()
        for item in schema_type.split("|")
        if item.strip() and item.strip() != "null"
    }
    for candidate in ("boolean", "integer", "number", "array", "object", "string"):
        if candidate in schema_types:
            return candidate

    logical_type = _annotation_type(field_info.annotation)
    if logical_type.startswith("array<"):
        return "array"
    if logical_type.startswith("object<"):
        return "object"
    if logical_type in {"bool", "boolean"}:
        return "boolean"
    if logical_type in {"int", "integer"}:
        return "integer"
    if logical_type in {"float", "number", "decimal"}:
        return "number"
    return "string"


def _field_description(
    *,
    field_name: str,
    field_info: Any,
    field_schema: dict[str, Any],
) -> str:
    description = " ".join(
        str(field_info.description or field_schema.get("description") or "").split()
    )
    if not description:
        raise ValueError(f"Missing data-model field description: {field_name}")
    if len(description) > MAX_COLUMN_DESCRIPTION_LENGTH:
        raise ValueError(
            "Data-model field description is too long for Kaggle column metadata: "
            f"{field_name} ({len(description)} > {MAX_COLUMN_DESCRIPTION_LENGTH})"
        )
    return description


def _annotation_type(annotation: Any) -> str:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is None:
        return _type_name(annotation)
    if origin is Annotated:
        return _annotation_type(args[0]) if args else "any"
    if origin is list:
        item_type = _annotation_type(args[0]) if args else "any"
        return f"array<{item_type}>"
    if origin is dict:
        key_type = _annotation_type(args[0]) if args else "string"
        value_type = _annotation_type(args[1]) if len(args) > 1 else "any"
        return f"object<{key_type}, {value_type}>"
    if origin in (Union, types.UnionType):
        return " | ".join(_annotation_type(arg) for arg in args)
    if origin is Literal:
        return "enum<" + ", ".join(repr(arg) for arg in args) + ">"
    return str(annotation).replace("typing.", "")


def _type_name(annotation: Any) -> str:
    if annotation is Any:
        return "any"
    if annotation is None or annotation is types.NoneType:
        return "null"
    if isinstance(annotation, type):
        return annotation.__name__
    return str(annotation).replace("typing.", "")


def _json_schema_type(field_schema: dict[str, Any]) -> str:
    if "type" in field_schema:
        raw_type = field_schema["type"]
        if isinstance(raw_type, list):
            return " | ".join(str(item) for item in raw_type)
        return str(raw_type)
    if "anyOf" in field_schema:
        return " | ".join(
            _json_schema_type(option)
            for option in field_schema["anyOf"]
            if isinstance(option, dict)
        )
    if "$ref" in field_schema:
        return "object"
    return "any"


def _enum_values(field_schema: dict[str, Any]) -> list[Any]:
    if "enum" in field_schema and isinstance(field_schema["enum"], list):
        return field_schema["enum"]
    values: list[Any] = []
    for option in field_schema.get("anyOf", []):
        if isinstance(option, dict) and isinstance(option.get("enum"), list):
            values.extend(option["enum"])
    return values


def _title_from_name(field_name: str) -> str:
    return field_name.replace("_", " ").title()


if __name__ == "__main__":
    main()
