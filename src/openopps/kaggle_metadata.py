from __future__ import annotations

from dataclasses import dataclass
import types
from typing import Annotated, Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel
from pydantic_core import PydanticUndefined
from sqlmodel import SQLModel

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
class KaggleTable:
    name: str
    model: type[SQLModel]
    description: str


@dataclass(frozen=True)
class KaggleResource:
    name: str
    path: str
    description: str
    format: str
    mediatype: str
    model: type[BaseModel] | None = None
    tables: tuple[KaggleTable, ...] = ()


KAGGLE_SQLITE_TABLES: tuple[KaggleTable, ...] = (
    KaggleTable(
        name="sources",
        model=SourceRow,
        description="Durable source catalogs that discover company boards.",
    ),
    KaggleTable(
        name="boards",
        model=BoardRow,
        description="Durable normalized company or organization hiring boards.",
    ),
    KaggleTable(
        name="board_providers",
        model=BoardProviderRow,
        description="Durable provider routes that connect boards to upstream systems.",
    ),
    KaggleTable(
        name="jobs",
        model=JobRow,
        description="Stable job identities and lifecycle state.",
    ),
    KaggleTable(
        name="job_versions",
        model=JobVersionRow,
        description="Versioned normalized job content snapshots.",
    ),
    KaggleTable(
        name="job_version_locations",
        model=JobVersionLocationRow,
        description="Indexed location labels for each normalized job version.",
    ),
    KaggleTable(
        name="job_version_skills",
        model=JobVersionSkillRow,
        description="Indexed skill groups for each normalized job version.",
    ),
    KaggleTable(
        name="job_version_skill_keywords",
        model=JobVersionSkillKeywordRow,
        description="Indexed skill keywords for each normalized job version skill.",
    ),
    KaggleTable(
        name="job_version_bullets",
        model=JobVersionBulletRow,
        description="Indexed responsibility and qualification bullets for each job version.",
    ),
    KaggleTable(
        name="job_payload_snapshots",
        model=JobPayloadSnapshotRow,
        description="Raw upstream payload snapshots for audit and replay.",
    ),
    KaggleTable(
        name="job_sync_runs",
        model=JobSyncRunRow,
        description="Provider route sync attempts and aggregate change counts.",
    ),
    KaggleTable(
        name="job_sync_observations",
        model=JobSyncObservationRow,
        description="Per-job observations recorded during provider route syncs.",
    ),
)


KAGGLE_DATASET_ID = "wyattowalsh/openoppsdb"
KAGGLE_SQLITE_FILE = "openopps.sqlite"
KAGGLE_EXPORT_CSV_DIR = "exports/csv"
KAGGLE_EXPORT_PARQUET_DIR = "exports/parquet"
KAGGLE_NOTEBOOK_FILE = "snapshot-openoppsdb.ipynb"
KAGGLE_NOTEBOOK_ID = "wyattowalsh/snapshot-openoppsdb"


KAGGLE_RESOURCES: tuple[KaggleResource, ...] = (
    (
        KaggleResource(
            name="openopps_database",
            path=KAGGLE_SQLITE_FILE,
            description=(
                "Full SQLite ledger with source, board, provider route, job lifecycle, "
                "version history, raw payload snapshot, and sync observation tables."
            ),
            format="sqlite",
            mediatype="application/vnd.sqlite3",
            tables=KAGGLE_SQLITE_TABLES,
        ),
    )
    + tuple(
        KaggleResource(
            name=f"{table.name}_csv",
            path=f"{KAGGLE_EXPORT_CSV_DIR}/{table.name}.csv",
            description=f"Full CSV table export for {table.description}",
            format="csv",
            mediatype="text/csv",
            model=table.model,
        )
        for table in KAGGLE_SQLITE_TABLES
    )
    + tuple(
        KaggleResource(
            name=f"{table.name}_parquet",
            path=f"{KAGGLE_EXPORT_PARQUET_DIR}/{table.name}.parquet",
            description=f"Full Parquet table export for {table.description}",
            format="parquet",
            mediatype="application/vnd.apache.parquet",
            model=table.model,
        )
        for table in KAGGLE_SQLITE_TABLES
    )
)


def build_kaggle_dataset_metadata() -> dict[str, Any]:
    """Build Kaggle CLI-compatible dataset metadata."""

    return {
        "id": KAGGLE_DATASET_ID,
        "title": "openoppsdb",
        "subtitle": "Normalized public startup and portfolio company job data.",
        "description": (
            "OpenOpps exports the full openopps.sqlite SQLite ledger plus full "
            "CSV and Parquet table exports generated from the accumulated snapshot "
            "database. The companion datapackage.json file is generated from the "
            "OpenOpps package models and contains resource, table, and field-level "
            "descriptions, types, examples, and required flags."
        ),
        "licenses": [{"name": "unknown"}],
        "keywords": [
            "jobs",
            "startups",
            "hiring",
            "venture-capital",
            "public-data",
            "openopps",
        ],
        "isPrivate": False,
    }


def build_kaggle_kernel_metadata() -> dict[str, Any]:
    """Build Kaggle CLI-compatible notebook metadata."""

    return {
        "id": KAGGLE_NOTEBOOK_ID,
        "title": "Snapshot openoppsdb",
        "code_file": KAGGLE_NOTEBOOK_FILE,
        "language": "python",
        "kernel_type": "notebook",
        "is_private": "true",
        "enable_gpu": "false",
        "enable_internet": "true",
        "dataset_sources": [KAGGLE_DATASET_ID],
        "competition_sources": [],
        "kernel_sources": [],
        "model_sources": [],
    }


def build_kaggle_update_notebook() -> dict[str, Any]:
    """Build a scheduled Kaggle notebook that snapshots active jobs into the DB."""

    return {
        "cells": [
            _markdown_cell(
                "overview",
                "# Snapshot Active Jobs into openoppsdb\n\n"
                "Schedule this Kaggle notebook with a cron cadence such as "
                "`0 */6 * * *`. Each scheduled run restores the previous "
                "openopps.sqlite from the Kaggle input dataset, installs the "
                "OpenOpps CLI, records active-job observations and version "
                "snapshots into that SQLite ledger, exports full CSV and Parquet "
                "table dumps, writes "
                "metadata, and versions the Kaggle dataset. Keep the notebook "
                "private when Kaggle API credentials are attached as secrets.",
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


def build_kaggle_datapackage() -> dict[str, Any]:
    """Build a Frictionless-style data dictionary from package models."""

    return {
        "profile": "data-package",
        "name": "openoppsdb",
        "title": "OpenOpps DB",
        "description": (
            "Package-derived Kaggle data dictionary for the full OpenOpps SQLite "
            "ledger and full table exports. Do not edit by hand; regenerate "
            "with scripts/generate_kaggle_metadata.py."
        ),
        "resources": [_resource_metadata(resource) for resource in KAGGLE_RESOURCES],
    }


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
    return """from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import UTC, datetime

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
DB_PATH = OUTPUT_DIR / "openopps.sqlite"
KAGGLE_INPUT_DIR = Path("/kaggle/input")

if OUTPUT_DIR.exists():
    shutil.rmtree(OUTPUT_DIR)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(command))
    subprocess.run(command, check=True, env=env)

db_candidates = sorted(KAGGLE_INPUT_DIR.glob("**/openopps.sqlite"))
if db_candidates:
    source_db = max(db_candidates, key=lambda path: path.stat().st_mtime)
    shutil.copy2(source_db, DB_PATH)
    print(f"Copied prior OpenOpps DB snapshot from {source_db} to {DB_PATH}")
else:
    print("No prior OpenOpps DB snapshot found; creating a new ledger.")

run([sys.executable, "-m", "pip", "install", "--quiet", "--upgrade", PACKAGE_SPEC, "kaggle"])
"""


def _notebook_sync_source() -> str:
    return """openopps_env = os.environ.copy()
openopps_env["OPENOPPS_DB_URL"] = f"sqlite:///{DB_PATH}"
openopps_env["OPENOPPS_CACHE_ENABLED"] = "false"

run(["openopps", "admin", "db", "init"], env=openopps_env)
run(["openopps", "sync", "--metrics-json"], env=openopps_env)
"""


def _notebook_export_source() -> str:
    return """import sqlite3

import polars as pl

from openopps.kaggle_metadata import KAGGLE_EXPORT_CSV_DIR, KAGGLE_EXPORT_PARQUET_DIR, KAGGLE_SQLITE_TABLES
from openopps.kaggle_metadata import build_kaggle_datapackage, build_kaggle_dataset_metadata

csv_dir = OUTPUT_DIR / KAGGLE_EXPORT_CSV_DIR
parquet_dir = OUTPUT_DIR / KAGGLE_EXPORT_PARQUET_DIR
csv_dir.mkdir(parents=True, exist_ok=True)
parquet_dir.mkdir(parents=True, exist_ok=True)

with sqlite3.connect(DB_PATH) as conn:
    conn.row_factory = sqlite3.Row
    for table in KAGGLE_SQLITE_TABLES:
        rows = [dict(row) for row in conn.execute(f'SELECT * FROM "{table.name}"')]
        frame = pl.DataFrame(rows or {field: [] for field in table.model.model_fields})
        frame.write_csv(csv_dir / f"{table.name}.csv")
        frame.write_parquet(parquet_dir / f"{table.name}.parquet")

(OUTPUT_DIR / "dataset-metadata.json").write_text(
    json.dumps(build_kaggle_dataset_metadata(), indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
(OUTPUT_DIR / "datapackage.json").write_text(
    json.dumps(build_kaggle_datapackage(), indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)

for path in sorted(OUTPUT_DIR.iterdir()):
    if path.name.endswith(".cache.db"):
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
        "skip",
    ])
else:
    print("Skipping dataset version upload because Kaggle API credentials are unavailable.")
"""


def _resource_metadata(resource: KaggleResource) -> dict[str, Any]:
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


def _table_metadata(table: KaggleTable) -> dict[str, Any]:
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
    enum_values = _enum_values(field_schema)
    if enum_values:
        metadata["enum"] = enum_values
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
