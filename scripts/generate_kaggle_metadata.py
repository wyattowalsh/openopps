from __future__ import annotations

import argparse
from dataclasses import dataclass
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
DB_FILE = "openoppsdb.sqlite"
CSV_DIR = "exports/csv"
PARQUET_DIR = "exports/parquet"
NB_FILE = "openoppsdb-manager.ipynb"
NB_ID = "wyattowalsh/openoppsdb-manager"
DATASET_IMAGE_FILE = "dataset-cover-image.png"
DATASET_IMAGE_SOURCE = Path("docs/public/social/openoppsdb.png")
DEFAULT_DATASET_DIR = Path(__file__).resolve().parents[1] / "kaggle"
DEFAULT_MANAGER_DIR = DEFAULT_DATASET_DIR
GENERATOR_SCRIPT_URL = (
    "https://raw.githubusercontent.com/wyattowalsh/openopps/main/"
    "scripts/generate_kaggle_metadata.py"
)
DATASET_IMAGE_URL = (
    "https://raw.githubusercontent.com/wyattowalsh/openopps/main/"
    "docs/public/social/openoppsdb.png"
)


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


RESOURCES: tuple[Resource, ...] = (
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
        "--data-db",
        type=Path,
        default=None,
        help=f"Existing SQLite DB to copy as {DB_FILE} and export alongside tables.",
    )
    args = parser.parse_args()

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.data_db is not None:
        _write_data_artifacts(output_dir, args.data_db)
    _write_dataset_image(output_dir)
    _remove_dataset_notebooks(output_dir)

    _write_json(output_dir / "dataset-metadata.json", dataset_metadata())
    _write_json(output_dir / "datapackage.json", datapackage())

    manager_dir: Path = args.manager_dir
    _write_manager_notebook(manager_dir)


def dataset_metadata() -> dict[str, Any]:
    return {
        "id": DATASET_ID,
        "title": "openoppsdb",
        "subtitle": "Daily SQLite, CSV, and Parquet public startup hiring-board ledger.",
        "description": _dataset_description(),
        "licenses": [{"name": "unknown"}],
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
- `datapackage.json`: a richer generated data dictionary with table metadata, field descriptions, logical types, examples, and required flags.

## How updates work

The connected Kaggle notebook `openoppsdb-manager` is intended to run on a Kaggle cron schedule. Each run installs OpenOpps from GitHub, copies the current `openoppsdb.sqlite` from this dataset, runs `openopps sync --metrics-json`, exports every SQLite table to CSV and Parquet, regenerates metadata, and publishes a new dataset version.

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
    resources = [_kaggle_resource_metadata(resource) for resource in RESOURCES]
    resources.append(
        {
            "name": "datapackage",
            "path": "datapackage.json",
            "title": "Companion data dictionary",
            "description": (
                "Package-derived companion data dictionary with resource, table, "
                "field, example, and required-flag metadata beyond Kaggle's native "
                "resource schema."
            ),
        }
    )
    return resources


def kernel_metadata() -> dict[str, Any]:
    return {
        "id": NB_ID,
        "id_no": 120479527,
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


def notebook() -> dict[str, Any]:
    return {
        "cells": [
            _markdown_cell(
                "overview",
                "# openoppsdb manager\n\n"
                "This notebook is connected to `wyattowalsh/openoppsdb`. Schedule "
                "it with a Kaggle cron "
                "cadence such as `0 */6 * * *`. Each run installs OpenOpps from "
                "GitHub, copies the newest `/kaggle/input/**/openoppsdb.sqlite` "
                "snapshot into `/kaggle/working/openoppsdb/openoppsdb.sqlite`, "
                "runs `openopps sync --metrics-json`, prepares SQLite/CSV/Parquet "
                "artifacts, and deploys a new dataset version.",
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
            frame = pl.DataFrame(
                rows or {field: [] for field in table.model.model_fields}
            )
            frame.write_csv(csv_dir / f"{table.name}.csv")
            frame.write_parquet(parquet_dir / f"{table.name}.parquet")


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

if OUTPUT_DIR.exists():
    shutil.rmtree(OUTPUT_DIR)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(command))
    subprocess.run(command, check=True, env=env)

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

install_openopps()
copy_latest_input_db()
download_dataset_assets()
"""


def _notebook_sync_source() -> str:
    return """openopps_env = os.environ.copy()
openopps_env["OPENOPPS_DB_URL"] = f"sqlite:///{DB_PATH}"
openopps_env["OPENOPPS_CACHE_ENABLED"] = "false"

run(["openopps", "admin", "db", "init"], env=openopps_env)
run(["openopps", "sync", "--metrics-json"], env=openopps_env)
"""


def _notebook_export_source() -> str:
    return """run([
    sys.executable,
    str(GENERATOR_SCRIPT),
    "--output-dir",
    str(OUTPUT_DIR),
    "--data-db",
    str(DB_PATH),
    "--manager-dir",
    str(OUTPUT_DIR / "_manager-unused"),
])
shutil.rmtree(OUTPUT_DIR / "_manager-unused", ignore_errors=True)

for path in sorted(OUTPUT_DIR.iterdir()):
    if path.name == "generate_kaggle_metadata.py":
        path.unlink()
        continue
    print(path.name, path.stat().st_size)
"""


def _notebook_publish_source() -> str:
    return """message = f"Scheduled OpenOpps active-job snapshot {datetime.now(UTC).isoformat()}"
kaggle_json = Path.home() / ".kaggle" / "kaggle.json"
token_path = os.environ.get("KAGGLE_API_V1_TOKEN_PATH")
has_kaggle_credentials = bool(
    os.environ.get("KAGGLE_API_TOKEN")
    or (token_path and Path(token_path).exists())
    or (os.environ.get("KAGGLE_USERNAME") and os.environ.get("KAGGLE_KEY"))
    or kaggle_json.exists()
)

if has_kaggle_credentials:
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
else:
    print("Skipping dataset version upload because Kaggle API credentials are unavailable.")
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


def _kaggle_field_metadata(field: dict[str, Any]) -> dict[str, Any]:
    description = str(field["description"])
    return {
        "name": field["name"],
        "title": description,
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
