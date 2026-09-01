"""OpenOpps Kaggle constants and schema tables."""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from pydantic import BaseModel, Field
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


@dataclass(frozen=True)
class PublicNotebookSpec:
    slug: str
    notebook_id: str
    title: str
    code_file: str
    notebook_factory: Callable[[], dict[str, Any]]
    enable_internet: bool = False
    keywords: tuple[str, ...] = ()
    kernel_sources: tuple[str, ...] = ()


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
        description="Whether the Pydantic boundary model marks the field as required."
    )
    operational_nullable: bool = Field(
        description="Whether the operational SQLite schema allows NULL for this column."
    )
    public_sqlite_value_status: str = Field(
        description=(
            "How the public SQLite value is represented: full, projected_null, "
            "preview_truncated_when_long, or generated_metadata."
        )
    )
    full_export_paths_json: str | None = Field(
        default=None,
        description="JSON array of CSV/Parquet export paths containing full column values.",
    )
    relationship_json: str | None = Field(
        default=None,
        description="JSON object describing primary-key and join relationships, when known.",
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
RUNTIME_GENERATOR_DATASET_ID = "wyattowalsh/openoppsdb-manager-runtime"
RUNTIME_GENERATOR_DATASET_SLUG = "openoppsdb-manager-runtime"
RUNTIME_GENERATOR_PACKAGE_DIR = "openopps_kaggle"
RUNTIME_MANIFEST_FILE = "runtime-manifest.json"
RUNTIME_GENERATOR_SCRIPT_FILE = RUNTIME_GENERATOR_PACKAGE_DIR
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
ADVANCED_NB_FILE = "openoppsdb-advanced-usage.ipynb"
ADVANCED_NB_ID = "wyattowalsh/openoppsdb-advanced-usage"
HIRING_MARKET_NB_FILE = "openoppsdb-hiring-market-map.ipynb"
HIRING_MARKET_NB_ID = "wyattowalsh/openoppsdb-hiring-market-map"
SKILLS_RADAR_NB_FILE = "openoppsdb-skills-radar.ipynb"
SKILLS_RADAR_NB_ID = "wyattowalsh/openoppsdb-skills-radar"
SQL_PLAYGROUND_NB_FILE = "openoppsdb-sql-playground.ipynb"
SQL_PLAYGROUND_NB_ID = "wyattowalsh/openoppsdb-sql-playground"
EXPLORER_NB_FILE = "openoppsdb-explorer.ipynb"
EXPLORER_NB_ID = "wyattowalsh/openoppsdb-explorer"
SNAPSHOT_HEALTH_NB_FILE = "openoppsdb-snapshot-health.ipynb"
SNAPSHOT_HEALTH_NB_ID = "wyattowalsh/openoppsdb-snapshot-health"
NOTEBOOK_GRADIO_VERSION = "6.26.0"
NOTEBOOK_JUPYSQL_VERSION = "0.11.1"
NOTEBOOK_DUCKDB_VERSION = "1.5.5"
NOTEBOOK_DUCKDB_ENGINE_VERSION = "0.17.0"
NOTEBOOK_PLOTLY_VERSION = "7.0.0"
ROUTE_LEDGER_PINE = "#2f6f50"
ROUTE_LEDGER_PAPER = "#f7f1df"
ROUTE_LEDGER_BRASS = "#d99629"
ROUTE_LEDGER_INK = "#1d281f"
ROUTE_LEDGER_INFO = "#336d8f"
PUBLIC_KERNEL_KEYWORDS: tuple[str, ...] = ()
DATASET_MARKETPLACE_KEYWORDS = (
    "business",
    "internet",
    "tabular",
    "jobs and career",
    "data visualization",
)


def public_notebook_ids() -> tuple[str, ...]:
    return (
        STARTER_NB_ID,
        ADVANCED_NB_ID,
        HIRING_MARKET_NB_ID,
        SKILLS_RADAR_NB_ID,
        SQL_PLAYGROUND_NB_ID,
        EXPLORER_NB_ID,
        SNAPSHOT_HEALTH_NB_ID,
    )


def sibling_kernel_sources(notebook_id: str) -> tuple[str, ...]:
    # Kaggle rejects kernel_sources that do not already exist as public kernels.
    established = (
        ADVANCED_NB_ID,
        HIRING_MARKET_NB_ID,
        SKILLS_RADAR_NB_ID,
    )
    return tuple(
        item for item in established if item != notebook_id
    )


DATASET_IMAGE_FILE = "dataset-cover-image.png"
DATASET_IMAGE_SOURCE = Path("web/public/social/openoppsdb.png")
DEFAULT_DATASET_DIR = Path(__file__).resolve().parents[2] / "kaggle"
DEFAULT_MANAGER_DIR = DEFAULT_DATASET_DIR
DEFAULT_STARTER_DIR = DEFAULT_DATASET_DIR / "starter"
DEFAULT_EXAMPLES_DIR = DEFAULT_DATASET_DIR / "examples"
GENERATOR_SCRIPT_URL = (
    f"file:///kaggle/input/{RUNTIME_GENERATOR_DATASET_SLUG}/"
    f"{RUNTIME_GENERATOR_PACKAGE_DIR}/"
)
DATASET_IMAGE_URL = (
    "https://raw.githubusercontent.com/wyattowalsh/openopps/main/"
    "web/public/social/openoppsdb.png"
)
SQLITE_SIDECAR_SUFFIXES = ("-journal", "-shm", "-wal")
SQLITE_PREVIEW_TEXT_MAX_CHARS = 512
SQLITE_PREVIEW_TEXT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("boards", "description"),
    ("boards", "locations"),
    ("boards", "markets"),
    ("boards", "source_board_keys"),
    ("job_version_bullets", "text"),
    ("job_version_locations", "label"),
    ("job_versions", "locations"),
    ("sources", "raw_metadata"),
)
# Public Kaggle SQLite mirrors the operational database. Large text columns stay
# in SQLite; CSV/Parquet exports remain the tabular mirror for Kaggle UI.
SQLITE_UPLOAD_PROJECTED_COLUMNS: tuple[tuple[str, str], ...] = ()
SQLITE_UPLOAD_PROJECTED_COLUMN_SET = frozenset(SQLITE_UPLOAD_PROJECTED_COLUMNS)
SQLITE_PREVIEW_TEXT_COLUMN_SET = frozenset(SQLITE_PREVIEW_TEXT_COLUMNS)
SQLITE_DERIVED_CHILD_TABLES: tuple[str, ...] = (
    "job_version_locations",
    "job_version_skills",
    "job_version_skill_keywords",
    "job_version_bullets",
)
PUBLIC_SQLITE_VALUE_STATUSES = frozenset(
    {"full", "projected_null", "preview_truncated_when_long", "generated_metadata"}
)
APP_PRIMARY_KEY_COLUMNS: dict[str, tuple[str, ...]] = {
    "sources": ("key",),
    "boards": ("key",),
    "board_providers": ("id",),
    "jobs": ("id",),
    "job_versions": ("id",),
    "job_version_locations": ("id",),
    "job_version_skills": ("id",),
    "job_version_skill_keywords": ("id",),
    "job_version_bullets": ("id",),
    "job_payload_snapshots": ("id",),
    "job_sync_runs": ("id",),
    "job_sync_observations": ("id",),
    "openopps_tables": ("table_name",),
    "openopps_columns": ("table_name", "column_name"),
}
RELATIONSHIP_REFERENCES: dict[tuple[str, str], tuple[dict[str, object], ...]] = {
    ("boards", "source_key"): (
        {"table": "sources", "column": "key", "nullable": False, "onDelete": "CASCADE"},
    ),
    ("board_providers", "source_key"): (
        {"table": "sources", "column": "key", "nullable": False, "onDelete": "CASCADE"},
    ),
    ("board_providers", "board_key"): (
        {"table": "boards", "column": "key", "nullable": False, "onDelete": "CASCADE"},
    ),
    ("jobs", "board_key"): (
        {"table": "boards", "column": "key", "nullable": False, "onDelete": "CASCADE"},
    ),
    ("jobs", "current_version_id"): (
        {"table": "job_versions", "column": "id", "nullable": True, "onDelete": None},
    ),
    ("job_versions", "job_id"): (
        {"table": "jobs", "column": "id", "nullable": False, "onDelete": "CASCADE"},
    ),
    ("job_version_locations", "job_version_id"): (
        {
            "table": "job_versions",
            "column": "id",
            "nullable": False,
            "onDelete": "CASCADE",
        },
    ),
    ("job_version_skills", "job_version_id"): (
        {
            "table": "job_versions",
            "column": "id",
            "nullable": False,
            "onDelete": "CASCADE",
        },
    ),
    ("job_version_skill_keywords", "skill_id"): (
        {
            "table": "job_version_skills",
            "column": "id",
            "nullable": False,
            "onDelete": "CASCADE",
        },
    ),
    ("job_version_bullets", "job_version_id"): (
        {
            "table": "job_versions",
            "column": "id",
            "nullable": False,
            "onDelete": "CASCADE",
        },
    ),
    ("job_payload_snapshots", "job_id"): (
        {"table": "jobs", "column": "id", "nullable": False, "onDelete": "CASCADE"},
    ),
    ("job_sync_runs", "board_key"): (
        {"table": "boards", "column": "key", "nullable": False, "onDelete": "CASCADE"},
    ),
    ("job_sync_observations", "sync_run_id"): (
        {
            "table": "job_sync_runs",
            "column": "id",
            "nullable": False,
            "onDelete": "CASCADE",
        },
    ),
    ("job_sync_observations", "job_id"): (
        {"table": "jobs", "column": "id", "nullable": False, "onDelete": "CASCADE"},
    ),
    ("job_sync_observations", "job_version_id"): (
        {
            "table": "job_versions",
            "column": "id",
            "nullable": True,
            "onDelete": "SET NULL",
        },
    ),
    ("openopps_columns", "table_name"): (
        {
            "table": "openopps_tables",
            "column": "table_name",
            "nullable": False,
            "onDelete": "CASCADE",
        },
    ),
}
ENUM_VALUES_BY_COLUMN: dict[tuple[str, str], tuple[str, ...]] = {
    ("board_providers", "support_level"): ("detect", "jobs", "unsupported"),
    ("jobs", "status"): ("open", "closed"),
    ("job_payload_snapshots", "payload_kind"): ("listing", "detail"),
    ("job_sync_observations", "observation_kind"): (
        "new",
        "unchanged",
        "changed",
        "reopened",
        "closed",
    ),
    ("job_versions", "remote"): ("Full", "Hybrid", "None"),
    ("job_version_bullets", "kind"): ("responsibility", "qualification"),
}
JOIN_HINTS_BY_COLUMN: dict[tuple[str, str], str] = {
    (
        "jobs",
        "current_version_id",
    ): "Join jobs.current_version_id to job_versions.id for the current content snapshot.",
    (
        "job_versions",
        "job_id",
    ): "Join job_versions.job_id to jobs.id for all content versions of a job.",
    (
        "job_sync_observations",
        "sync_run_id",
    ): "Join job_sync_observations.sync_run_id to job_sync_runs.id for route run context.",
    (
        "job_sync_observations",
        "job_version_id",
    ): "Join non-null job_version_id values to job_versions.id for observed content.",
}
MAX_COLUMN_DESCRIPTION_LENGTH = 160
NOTEBOOK_SYNC_ENV_DEFAULTS: dict[str, str] = {
    "OPENOPPS_SOURCE_FRESHNESS_SECONDS": "86400",
    "OPENOPPS_SOURCE_CONCURRENCY": "40",
    "OPENOPPS_PROVIDER_CONCURRENCY": "80",
    "OPENOPPS_BOARD_CONCURRENCY": "80",
    "OPENOPPS_JOB_ROUTE_TIMEOUT_SECONDS": "180",
    "OPENOPPS_JOB_ROUTE_FRESHNESS_SECONDS": "86400",
    "OPENOPPS_MAX_CONNECTIONS": "120",
    "OPENOPPS_SOURCE_TIMEOUT_SECONDS": "45",
    "OPENOPPS_HTTP_TIMEOUT": "20",
    "OPENOPPS_RETRY_ATTEMPTS": "2",
}
NOTEBOOK_SYNC_TIMEOUT_SECONDS = 6000

# Public snapshot size budgets for quality gate (manager + local publish).
# Full payload SQLite + dual exports are disk-heavy on Kaggle; fail closed above these.
PUBLIC_SQLITE_MAX_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB
PUBLIC_EXPORTS_MAX_BYTES = 4 * 1024 * 1024 * 1024  # 4 GiB combined csv+parquet


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
PUBLIC_SQLITE_TABLE_NAMES: tuple[str, ...] = tuple(table.name for table in TABLES)
PUBLIC_SQLITE_TABLE_NAME_SET = frozenset(PUBLIC_SQLITE_TABLE_NAMES)
EXPORT_ORDER_COLUMNS: dict[str, tuple[str, ...]] = {
    "sources": ("key",),
    "boards": ("key",),
    "board_providers": ("source_key", "board_key", "provider_id", "id"),
    "jobs": ("board_key", "provider_id", "remote_id", "id"),
    "job_versions": ("job_id", "version", "id"),
    "job_version_locations": ("job_version_id", "ordinal", "label", "id"),
    "job_version_skills": ("job_version_id", "ordinal", "id"),
    "job_version_skill_keywords": ("skill_id", "ordinal", "keyword", "id"),
    "job_version_bullets": ("job_version_id", "kind", "ordinal", "text", "id"),
    "job_payload_snapshots": ("job_id", "payload_kind", "payload_hash", "id"),
    "job_sync_runs": ("synced_at", "board_key", "provider_id", "id"),
    "job_sync_observations": ("observed_at", "sync_run_id", "job_id", "id"),
    "openopps_tables": ("table_name",),
    "openopps_columns": ("table_name", "column_name"),
}


DATA_RESOURCES: tuple[Resource, ...] = (
    (
        Resource(
            name="openopps_database",
            path=DB_FILE,
            description=(
                "OpenOppsDB SQLite database file with source, board, provider "
                "route, job lifecycle, version history, sync observations, and "
                "in-database openopps_tables/openopps_columns metadata. Kaggle "
                "column metadata is attached to the CSV and Parquet exports."
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
            "JSON metrics emitted by the full manager command "
            "`openopps sync --metrics-json`, including post-launch fresh-window "
            "provider errors and explicit partial-timeout evidence when the "
            "bounded notebook runtime expires after fresh authoritative work."
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
PRIVATE_UPLOAD_RUNTIME_FILES: tuple[str, ...] = (
    NB_FILE,
    STARTER_NB_FILE,
    "kernel-metadata.json",
    RUNTIME_MANIFEST_FILE,
)
PRIVATE_UPLOAD_RUNTIME_DIRS: tuple[str, ...] = (
    ".ipynb_checkpoints",
    "examples",
    "notebooks",
    "starter",
    "public-upload",
    RUNTIME_GENERATOR_PACKAGE_DIR,
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
