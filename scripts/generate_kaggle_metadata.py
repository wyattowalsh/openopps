from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
import sqlite3
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
)


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
NOTEBOOK_SYNC_ENV_DEFAULTS: dict[str, str] = {
    "OPENOPPS_SOURCE_FRESHNESS_SECONDS": "86400",
    "OPENOPPS_SOURCE_CONCURRENCY": "40",
    "OPENOPPS_PROVIDER_CONCURRENCY": "80",
    "OPENOPPS_BOARD_CONCURRENCY": "80",
    "OPENOPPS_JOB_ROUTE_TIMEOUT_SECONDS": "180",
    "OPENOPPS_MAX_CONNECTIONS": "120",
    "OPENOPPS_SOURCE_TIMEOUT_SECONDS": "120",
    "OPENOPPS_HTTP_TIMEOUT": "20",
    "OPENOPPS_RETRY_ATTEMPTS": "2",
}
NOTEBOOK_SYNC_TIMEOUT_SECONDS = 3300


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
                "table and column metadata tables."
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
    if args.update_live_file_metadata:
        _update_live_file_metadata(output_dir / "dataset-metadata.json")


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

- `openoppsdb.sqlite`: the complete SQLite ledger, including metadata tables named `openopps_tables` and `openopps_columns`.
- `exports/csv/*.csv`: full table exports for spreadsheet and lightweight analysis workflows.
- `exports/parquet/*.parquet`: full table exports for Python, DuckDB, Polars, Spark, and warehouse workflows.

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
                "Parquet artifacts, prunes private evidence from the upload "
                "directory, and deploys a new dataset version only after the "
                "quality gate passes.",
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
    _clean_data_artifacts(output_dir, preserve=source_db)
    _checkpoint_sqlite(source_db)
    if source_db != target_db.resolve():
        shutil.copy2(source_db, target_db)
        if source_db.parent == output_dir.resolve():
            source_db.unlink()
    _drop_cache_tables(target_db)
    _write_sqlite_metadata(target_db)
    _checkpoint_sqlite(target_db)

    _write_full_table_exports(output_dir, target_db)
    _checkpoint_sqlite(target_db)


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
        conn.row_factory = sqlite3.Row
        for table in TABLES:
            rows = [dict(row) for row in conn.execute(f'SELECT * FROM "{table.name}"')]
            frame = _table_export_frame(table, rows)
            frame.write_csv(csv_dir / f"{table.name}.csv")
            frame.write_parquet(parquet_dir / f"{table.name}.parquet")


def _table_export_frame(table: Table, rows: list[dict[str, object]]) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame({field: [] for field in table.model.model_fields})
    return pl.DataFrame(rows, infer_schema_length=None)


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
                        field["type"],
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
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    _remove_sqlite_sidecars(path)


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
    return """#@title Initialize
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
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
GENERATOR_SCRIPT_URL = os.environ.get(
    "OPENOPPS_GENERATOR_SCRIPT_URL",
    "https://raw.githubusercontent.com/wyattowalsh/openopps/main/scripts/generate_kaggle_metadata.py",
)
DATASET_IMAGE_URL = os.environ.get(
    "OPENOPPS_DATASET_IMAGE_URL",
    "https://raw.githubusercontent.com/wyattowalsh/openopps/main/docs/public/social/openoppsdb.png",
)
OPENOPPS_SYNC_ENV_DEFAULTS = __OPENOPPS_SYNC_ENV_DEFAULTS__
KAGGLE_SYNC_TIMEOUT_SECONDS = float(
    os.environ.get(
        "OPENOPPS_KAGGLE_SYNC_TIMEOUT_SECONDS",
        "__OPENOPPS_KAGGLE_SYNC_TIMEOUT_SECONDS__",
    )
)
KAGGLE_CREDENTIALS_ERROR = (
    "Kaggle API credentials are required to publish openoppsdb. "
    "Configure KAGGLE_USERNAME and KAGGLE_KEY as Kaggle notebook secrets "
    "before running the manager."
)
KAGGLE_SECRET_LOOKUP_ERRORS: dict[str, str] = {}

if OUTPUT_DIR.exists():
    shutil.rmtree(OUTPUT_DIR)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def load_kaggle_notebook_secrets() -> None:
    try:
        from kaggle_secrets import UserSecretsClient
    except Exception as exc:
        KAGGLE_SECRET_LOOKUP_ERRORS["kaggle_secrets"] = type(exc).__name__
        print(f"Kaggle notebook secrets client unavailable: {type(exc).__name__}")
        return

    client = UserSecretsClient()

    if os.environ.get("KAGGLE_USERNAME"):
        print("KAGGLE_USERNAME already present in environment.")
    else:
        try:
            username = client.get_secret("KAGGLE_USERNAME")
        except Exception as exc:
            KAGGLE_SECRET_LOOKUP_ERRORS["KAGGLE_USERNAME"] = type(exc).__name__
            print(
                "KAGGLE_USERNAME notebook secret lookup failed: "
                f"{type(exc).__name__}"
            )
        else:
            if isinstance(username, str) and username.strip():
                os.environ["KAGGLE_USERNAME"] = username.strip()
                print("KAGGLE_USERNAME loaded from Kaggle notebook secrets.")
            else:
                print("KAGGLE_USERNAME not found in Kaggle notebook secrets.")

    if os.environ.get("KAGGLE_KEY"):
        print("KAGGLE_KEY already present in environment.")
    else:
        try:
            key = client.get_secret("KAGGLE_KEY")
        except Exception as exc:
            KAGGLE_SECRET_LOOKUP_ERRORS["KAGGLE_KEY"] = type(exc).__name__
            print(
                "KAGGLE_KEY notebook secret lookup failed: "
                f"{type(exc).__name__}"
            )
        else:
            if isinstance(key, str) and key.strip():
                os.environ["KAGGLE_KEY"] = key.strip()
                print("KAGGLE_KEY loaded from Kaggle notebook secrets.")
            else:
                print("KAGGLE_KEY not found in Kaggle notebook secrets.")

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

def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(command))
    subprocess.run(command, check=True, env=env)

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

def install_openopps() -> None:
    run([sys.executable, "-m", "pip", "install", "--quiet", "--upgrade", PACKAGE_SPEC, "kaggle"])

def copy_latest_input_db() -> None:
    db_candidates = sorted(KAGGLE_INPUT_DIR.glob(INPUT_DB_GLOB))
    if db_candidates:
        source_db = max(db_candidates, key=lambda path: path.stat().st_mtime)
        shutil.copy2(source_db, DB_PATH)
        print(f"Copied prior OpenOpps DB snapshot from {source_db} to {DB_PATH}")
    else:
        print("No prior OpenOpps DB snapshot found; creating a new ledger.")

def download_dataset_assets() -> None:
    urllib.request.urlretrieve(GENERATOR_SCRIPT_URL, GENERATOR_SCRIPT)
    urllib.request.urlretrieve(DATASET_IMAGE_URL, OUTPUT_DIR / "dataset-cover-image.png")

def update_kaggle_dataset_file_metadata() -> None:
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

    with api.build_kaggle_client() as kaggle:
        response = kaggle.datasets.dataset_api_client.update_dataset_metadata(request)
    errors = getattr(response, "errors", None) or []
    if errors:
        raise RuntimeError(f"Kaggle dataset metadata update failed: {errors}")
    print(f"Updated Kaggle file metadata for {len(settings.data or [])} public files.")

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

require_kaggle_credentials()
install_openopps()
copy_latest_input_db()
download_dataset_assets()
""".replace("__OPENOPPS_SYNC_ENV_DEFAULTS__", sync_env_defaults).replace(
        "__OPENOPPS_KAGGLE_SYNC_TIMEOUT_SECONDS__",
        str(NOTEBOOK_SYNC_TIMEOUT_SECONDS),
    )


def _notebook_sync_source() -> str:
    return """openopps_env = os.environ.copy()
openopps_env["OPENOPPS_DB_URL"] = f"sqlite:///{DB_PATH}"
openopps_env["OPENOPPS_CACHE_ENABLED"] = "false"
for key, value in OPENOPPS_SYNC_ENV_DEFAULTS.items():
    openopps_env.setdefault(key, value)

run(["openopps", "admin", "db", "init"], env=openopps_env)
print(f"OpenOpps sync timeout: {KAGGLE_SYNC_TIMEOUT_SECONDS:g}s")
sync_metrics = run_json(
    ["openopps", "sync", "--metrics-json"],
    OUTPUT_DIR / "sync_metrics.json",
    env=openopps_env,
    timeout_seconds=KAGGLE_SYNC_TIMEOUT_SECONDS,
)
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
    return """quality_command = [
    sys.executable,
    str(GENERATOR_SCRIPT),
    "--output-dir",
    str(OUTPUT_DIR),
    "--data-db",
    str(DB_PATH),
    "--manager-dir",
    str(OUTPUT_DIR / "_manager-unused"),
    "--sync-metrics",
    str(OUTPUT_DIR / "sync_metrics.json"),
    "--status-json",
    str(OUTPUT_DIR / "status.json"),
    "--coverage-json",
    str(OUTPUT_DIR / "coverage.json"),
    "--quality-report",
    str(OUTPUT_DIR / "snapshot-quality.json"),
    "--prune-private-upload-files",
]
empty_snapshot_explanation = os.environ.get("OPENOPPS_EMPTY_SNAPSHOT_EXPLANATION")
if empty_snapshot_explanation:
    quality_command.extend([
        "--empty-snapshot-explanation",
        empty_snapshot_explanation,
    ])
run(quality_command)
shutil.rmtree(OUTPUT_DIR / "_manager-unused", ignore_errors=True)

for path in sorted(OUTPUT_DIR.iterdir()):
    if path.name == "generate_kaggle_metadata.py":
        path.unlink()
        continue
    print(path.name, path.stat().st_size)
"""


def _notebook_publish_source() -> str:
    return """message = f"Scheduled OpenOpps active-job snapshot {datetime.now(UTC).isoformat()}"
require_kaggle_credentials()

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
update_kaggle_dataset_file_metadata()
run(["kaggle", "datasets", "status", DATASET_ID, "--format", "json"])
run(["kaggle", "datasets", "files", DATASET_ID, "--page-size", "200"])
"""


def _resource_metadata(resource: Resource) -> dict[str, Any]:
    metadata: dict[str, Any] = {
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


def _update_live_file_metadata(metadata_path: Path) -> None:
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

    with api.build_kaggle_client() as kaggle:
        response = kaggle.datasets.dataset_api_client.update_dataset_metadata(request)
    errors = getattr(response, "errors", None) or []
    if errors:
        raise RuntimeError(f"Kaggle dataset metadata update failed: {errors}")
    print(f"Updated Kaggle file metadata for {len(settings.data or [])} public files.")


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


def _kaggle_field_metadata(field: dict[str, Any]) -> dict[str, Any]:
    description = str(field["description"])
    return {
        "name": field["name"],
        "title": str(field["title"]),
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
    description = field_info.description or field_schema.get("description")
    metadata: dict[str, Any] = {
        "name": field_name,
        "title": field_schema.get("title", _title_from_name(field_name)),
        "description": description,
        "type": _annotation_type(field_info.annotation),
        "jsonSchemaType": _json_schema_type(field_schema),
        "required": required,
    }
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
