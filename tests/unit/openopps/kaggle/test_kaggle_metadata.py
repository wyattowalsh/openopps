from __future__ import annotations

import inspect
import csv
import hashlib
import json
import shutil
from pathlib import Path
import sqlite3
import struct
import sys
import types
from typing import Any

import pytest

from openopps.settings import OpenOppsSettings
from openopps.storage import OpenOppsStore

import openopps_kaggle._core as core  # ty: ignore[unresolved-import]
import openopps_kaggle.generator as gen  # ty: ignore[unresolved-import]
import openopps_kaggle.verify_notebooks as pullback  # ty: ignore[unresolved-import]

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = REPO_ROOT / "scripts" / "openopps_kaggle" / "_core.py"


def test_kaggle_dataset_metadata_has_required_kaggle_fields() -> None:
    metadata = gen.dataset_metadata()
    resources = {resource["path"]: resource for resource in metadata["resources"]}

    assert metadata["id"]
    assert metadata["title"]
    assert metadata["licenses"]
    assert metadata["licenses"] == [{"name": gen.DATASET_LICENSE}]
    assert gen.DATASET_LICENSE == "CC0-1.0"
    assert metadata["description"]
    assert metadata["id"] == "wyattowalsh/openoppsdb"
    assert metadata["id"] == gen.DATASET_ID
    assert metadata["title"] == "openoppsdb"
    assert metadata["image"] == gen.DATASET_IMAGE_FILE
    assert metadata["expectedUpdateFrequency"] == "daily"
    assert metadata["userSpecifiedSources"]
    assert metadata["keywords"]
    assert "datapackage.json" not in metadata["description"]
    assert "snapshot-quality.json" not in metadata["description"]
    assert "public file surface is intentionally limited" in metadata["description"]
    assert "openoppsdb-manager" in metadata["description"]
    assert "`openopps sync --metrics-json`" in metadata["description"]
    assert "Quick start" in metadata["description"]
    assert gen.DB_FILE in metadata["description"]
    assert "Parquet" in metadata["description"]
    assert "Kaggle renders CSV and Parquet exports" in metadata["description"]
    assert "sqliteInfo" not in metadata["description"]
    assert set(resources) == {resource.path for resource in gen.RESOURCES}
    assert set(resources) == {resource.path for resource in gen.DATA_RESOURCES}
    assert resources[gen.DB_FILE]["description"]
    assert resources[gen.DB_FILE]["name"] == "SQLite Database"
    assert "CSV and Parquet exports" in resources[gen.DB_FILE]["description"]
    assert set(resources[gen.DB_FILE]) == {"path", "name", "description"}
    assert "schema" not in resources[gen.DB_FILE]
    assert "tables" not in resources[gen.DB_FILE]
    assert "title" not in resources[gen.DB_FILE]
    assert gen.SYNC_METRICS_FILE not in resources
    assert gen.STATUS_FILE not in resources
    assert gen.COVERAGE_FILE not in resources
    assert gen.SNAPSHOT_QUALITY_FILE not in resources
    assert gen.DATAPACKAGE_FILE not in resources
    assert gen.EXPOSED_DATAPACKAGE_FILE not in resources


def test_kaggle_dataset_metadata_has_supported_resource_schemas() -> None:
    metadata = gen.dataset_metadata()
    resources = {resource["path"]: resource for resource in metadata["resources"]}
    supported_types = {
        "boolean",
        "datetime",
        "id",
        "integer",
        "numeric",
        "string",
        "url",
    }

    sqlite_resource = resources[gen.DB_FILE]
    assert set(sqlite_resource) == {"path", "name", "description"}
    assert sqlite_resource["name"] == "SQLite Database"
    assert "schema" not in sqlite_resource
    assert "tables" not in sqlite_resource

    for table in gen.TABLES:
        expected_fields = list(table.model.model_fields)
        sqlite_table = gen._kaggle_table_metadata(table)
        assert sqlite_table["description"] == table.description
        sqlite_fields = sqlite_table["schema"]["fields"]
        assert [field["name"] for field in sqlite_fields] == expected_fields
        for path in (
            f"{gen.CSV_DIR}/{table.name}.csv",
            f"{gen.PARQUET_DIR}/{table.name}.parquet",
        ):
            resource = resources[path]
            assert set(resource) == {"path", "description", "schema"}
            fields = resource["schema"]["fields"]
            assert [field["name"] for field in fields] == expected_fields
            assert fields == sqlite_fields
            for field in fields:
                assert set(field) == {"name", "description", "type"}
                assert field["description"], field["name"]
                assert len(field["description"]) <= gen.MAX_COLUMN_DESCRIPTION_LENGTH
                assert field["type"] in supported_types
                assert field["type"] != "str"
                assert field["type"] != "bool"
                assert "object<" not in field["type"]
                assert "array<" not in field["type"]
                assert "Annotated" not in field["type"]
                assert "typing." not in field["type"]
                assert "| null" not in field["type"]
    jobs_fields = {
        field["name"]: field
        for field in resources[f"{gen.CSV_DIR}/jobs.csv"]["schema"]["fields"]
    }
    assert "title" not in jobs_fields["board_key"]
    assert jobs_fields["board_key"]["description"] == "Board key this job belongs to."
    assert jobs_fields["board_key"]["type"] == "id"


def test_kaggle_upload_resources_use_nbadb_style_subset() -> None:
    metadata = gen.dataset_metadata()
    allowed_resource_keys = {"path", "name", "description", "schema"}
    allowed_schema_keys = {"fields"}
    allowed_field_keys = {"name", "description", "type"}

    assert len(metadata["resources"]) == len(gen.DATA_RESOURCES)
    for resource in metadata["resources"]:
        assert set(resource) <= allowed_resource_keys, resource["path"]
        assert resource["path"]
        assert resource["description"]
        if resource["path"] == gen.DB_FILE:
            assert resource["name"] == "SQLite Database"
        else:
            assert "name" not in resource
        assert "title" not in resource
        assert "tables" not in resource
        if "schema" in resource:
            assert set(resource["schema"]) == allowed_schema_keys
            assert resource["schema"]["fields"]
            for field in resource["schema"]["fields"]:
                assert set(field) == allowed_field_keys


def test_kaggle_workflow_docs_align_runtime_and_sync_commands() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    operations = (repo_root / "web/content/docs/operations.mdx").read_text(
        encoding="utf-8"
    )
    spec = (
        repo_root / "openspec/specs/release-workflows/spec.md"
    ).read_text(encoding="utf-8")

    # Manager/Kaggle contract is single-sourced as bounded jobs sync.
    assert (
        "openopps jobs sync --metrics-json --freshness-seconds 86400 --limit 120"
        in readme
    )
    assert (
        "openopps jobs sync --metrics-json --freshness-seconds 86400 --limit 120"
        in operations
        or "openopps jobs sync --metrics-json --freshness-seconds --limit" in operations
    )
    assert "db=" in readme and "allow_stale" in readme
    assert "kaggle-dataset-version" in operations
    assert "just kaggle-runtime-generator-version" in readme
    assert "just kaggle-runtime-generator-version" in operations
    assert "kaggle-runtime-generator-create" in readme
    assert "kaggle-runtime-generator-create" in operations
    assert "openopps sync --metrics-json" in readme
    assert "openopps sync --metrics-json" in operations
    assert "kaggle auth print-access-token" not in spec
    assert "kaggle auth login" in spec
    assert "runtime generator create/version recipe" in spec


def test_kaggle_file_metadata_covers_public_files_for_live_update() -> None:
    metadata = gen.dataset_metadata()
    resources = {resource["path"]: resource for resource in metadata["resources"]}
    files = {
        file_metadata["name"]: file_metadata
        for file_metadata in gen.dataset_file_metadata()
    }

    assert set(files) == set(resources)
    assert set(files) == {resource.path for resource in gen.DATA_RESOURCES}
    assert gen.SYNC_METRICS_FILE not in files
    assert gen.STATUS_FILE not in files
    assert gen.COVERAGE_FILE not in files
    assert gen.SNAPSHOT_QUALITY_FILE not in files

    sqlite_file = files[gen.DB_FILE]
    assert sqlite_file["description"] == resources[gen.DB_FILE]["description"]
    assert sqlite_file["columns"] == []

    jobs_file = files[f"{gen.CSV_DIR}/jobs.csv"]
    jobs_resource = resources[f"{gen.CSV_DIR}/jobs.csv"]
    assert jobs_file["description"] == jobs_resource["description"]
    assert jobs_file["columns"] == [
        {
            "name": field["name"],
            "description": field["description"],
            "type": field["type"],
        }
        for field in jobs_resource["schema"]["fields"]
    ]
    assert {
        "name": "board_key",
        "description": "Board key this job belongs to.",
        "type": "id",
    } in jobs_file["columns"]


def test_column_descriptions_are_model_annotations() -> None:
    for table in gen.TABLES:
        schema = gen._model_schema_metadata(table.model)
        fields = {field["name"]: field for field in schema["fields"]}
        for field_name, field_info in table.model.model_fields.items():
            expected = " ".join(str(field_info.description or "").split())

            assert expected
            assert len(expected) <= gen.MAX_COLUMN_DESCRIPTION_LENGTH
            assert fields[field_name]["description"] == expected


def test_kaggle_datapackage_annotates_all_resource_fields() -> None:
    data = gen.datapackage()
    resources = {resource["name"]: resource for resource in data["resources"]}

    assert set(resources) == {resource.name for resource in gen.RESOURCES}
    sqlite_resource = resources["openopps_database"]
    assert sqlite_resource["path"] == gen.DB_FILE
    assert sqlite_resource["profile"] == "data-resource"
    assert sqlite_resource["format"] == "sqlite"
    assert {table["name"] for table in sqlite_resource["tables"]} == {
        table.name for table in gen.TABLES
    }
    assert {"openopps_tables", "openopps_columns"} <= {
        table["name"] for table in sqlite_resource["tables"]
    }
    for table in gen.TABLES:
        csv_resource = resources[f"{table.name}_csv"]
        parquet_resource = resources[f"{table.name}_parquet"]
        assert csv_resource["path"] == f"{gen.CSV_DIR}/{table.name}.csv"
        assert csv_resource["profile"] == "tabular-data-resource"
        assert csv_resource["format"] == "csv"
        assert parquet_resource["path"] == f"{gen.PARQUET_DIR}/{table.name}.parquet"
        assert parquet_resource["profile"] == "data-resource"
        assert parquet_resource["format"] == "parquet"
    for resource in resources.values():
        schemas = []
        if "schema" in resource:
            schemas.append(resource["schema"])
        schemas.extend(table["schema"] for table in resource.get("tables", []))
        if not schemas:
            assert resource["description"]
            assert resource["format"] == "json"
            continue
        for schema in schemas:
            fields = schema["fields"]
            assert fields
            for field in fields:
                assert field["name"]
                assert field["title"]
                assert field["description"], field["name"]
                assert field["type"]
                assert "Annotated[" not in field["type"]
                assert "object<" not in field["type"]
                assert "array<" not in field["type"]
                assert field["logicalType"]
                assert field["jsonSchemaType"]
                assert isinstance(field["required"], bool)
                if field["required"]:
                    assert field["constraints"]["required"] is True


def test_kaggle_notebook_metadata_runs_public_scheduled_snapshot() -> None:
    metadata = gen.kernel_metadata()
    data = gen.notebook()
    source = "\n".join(
        line for cell in data["cells"] for line in cell.get("source", [])
    )
    for index, cell in enumerate(data["cells"]):
        if cell.get("cell_type") == "code":
            compile("".join(cell.get("source", [])), f"cell-{index}", "exec")

    assert metadata["kernel_type"] == "notebook"
    assert metadata["enable_internet"] is True
    assert metadata["is_private"] is True
    assert metadata["id"] == "wyattowalsh/openoppsdb-manager"
    assert metadata["id"] == gen.NB_ID
    assert "id_no" not in metadata
    assert metadata["title"] == "openoppsdb manager"
    assert metadata["dataset_sources"] == [
        gen.DATASET_ID,
        gen.RUNTIME_GENERATOR_DATASET_ID,
    ]
    assert metadata["code_file"] == gen.NB_FILE
    assert metadata["code_file"] == "openoppsdb-manager.ipynb"
    assert metadata["code_file"].endswith(".ipynb")

    assert "0 6 * * *" in source
    assert "0 */6 * * *" not in source
    assert "openopps sync --metrics-json" in source
    assert gen.DATASET_ID in source
    assert "git+https://github.com/wyattowalsh/openopps.git@main" not in source
    assert "__OPENOPPS_IMMUTABLE_PACKAGE_SPEC_REQUIRED__" in source
    assert "OPENOPPS_PACKAGE_SPEC" in source
    assert "def require_immutable_openopps_package_spec()" in source
    assert "kaggle==2.2.4" in source
    assert "/kaggle/input" in source
    assert "openopps-*.whl" not in source
    assert "**/openoppsdb.sqlite" in source
    assert "/kaggle/working/openoppsdb" in source
    assert "Copied prior OpenOpps DB snapshot" in source
    assert "OPENOPPS_RUNTIME_PACKAGE_SHA256" in source
    runtime_generator_sha = gen.runtime_generator_script_sha256()
    assert runtime_generator_sha in source
    assert "__RUNTIME_PACKAGE_SHA256__" not in source
    assert gen.GENERATOR_SCRIPT_URL in source
    assert "openopps_kaggle" in source
    assert "RUNTIME_PACKAGE_VERIFIED_SHA256" in source
    assert "def required_runtime_package_sha256()" in source
    assert "def verify_runtime_package_manifest()" in source
    assert "def runtime_probe_env()" in source
    assert 'key.startswith("KAGGLE_")' in source
    assert "KAGGLE_CREDENTIAL_ENV_NAMES" in source
    assert "runtime_probe_env()" in source
    assert "OPENOPPS_RUNTIME_PACKAGE_SHA256 is required before downloading" in source
    assert "Downloaded OpenOpps Kaggle runtime package is incompatible" in source
    assert "openopps.kaggle_metadata" not in source
    assert "rehydrates the public SQLite snapshot" in source
    assert "`openopps sync --metrics-json`" in source

    assert "OPENOPPS_SYNC_ENV_DEFAULTS" in source
    assert "openopps_env.setdefault(key, value)" in source
    assert "OPENOPPS_KAGGLE_SYNC_TIMEOUT_SECONDS" in source
    assert f'"{gen.NOTEBOOK_SYNC_TIMEOUT_SECONDS}"' in source
    assert "timeout_seconds=KAGGLE_SYNC_TIMEOUT_SECONDS" in source
    assert "Command exceeded" in source
    assert "stdout=subprocess.PIPE" in source
    assert "stderr=subprocess.PIPE" in source
    assert "capture_output=True" not in source
    for key, value in gen.NOTEBOOK_SYNC_ENV_DEFAULTS.items():
        assert f'"{key}": "{value}"' in source

    assert "run_json" in source
    assert "sync_metrics.json" in source
    assert "status.json" in source
    assert "coverage.json" in source
    assert "snapshot-quality.json" in source
    assert '"providers", "coverage", "--json"' in source
    assert "OPENOPPS_EMPTY_SNAPSHOT_EXPLANATION" in source
    assert "KAGGLE_API_TOKEN" in source
    assert "KAGGLE_API_V1_TOKEN_PATH" in source
    assert "UserSecretsClient" in source
    assert "user_secrets = UserSecretsClient()" in source
    assert 'secret_value_0 = user_secrets.get_secret("KAGGLE_KEY")' in source
    assert 'secret_value_1 = user_secrets.get_secret("KAGGLE_USERNAME")' in source
    assert 'UserSecretsClient().get_secret("OPENOPPS_PACKAGE_SPEC")' in source
    assert "def load_openopps_package_spec_secret()" in source
    assert "PUBLIC_SNAPSHOT_COLUMN_BACKFILLS" in source
    assert "def public_snapshot_select_expressions(" in source
    assert 'client.get_secret("KAGGLE_API_TOKEN")' not in source
    assert "def load_kaggle_notebook_secrets()" in source
    assert "def read_kaggle_notebook_secrets" in source
    assert "OPENOPPS_KAGGLE_SECRET_RETRIES" in source
    assert "OPENOPPS_KAGGLE_SECRET_URL_BASE" in source
    assert '"https://www.kaggle.com"' in source
    assert 'os.environ["KAGGLE_URL_BASE"] = KAGGLE_SECRET_URL_BASE' in source
    assert 'os.environ["KAGGLE_URL_BASE"] = runtime_url_base' in source
    assert "time.sleep(KAGGLE_SECRET_RETRY_SECONDS)" in source
    assert "Kaggle API credentials are required" in source

    assert "INPUT_BOARDS_PARQUET_GLOB" in source
    assert "INPUT_JOB_VERSIONS_PARQUET_GLOB" in source
    assert "INPUT_JOB_PAYLOAD_SNAPSHOTS_PARQUET_GLOB" in source
    assert "def restore_projected_sqlite_columns_from_input_exports()" in source
    assert "restore_projected_sqlite_columns_from_input_exports()" in source
    assert "def rehydrate_public_snapshot_for_openopps(" in source
    assert "Rehydrating public OpenOppsDB snapshot" in source
    assert "Rehydrated public OpenOppsDB snapshot:" in source
    assert "PUBLIC_SNAPSHOT_JSON_DEFAULTS" in source
    assert "sanitize_public_snapshot_json_columns(snapshot_path)" in source
    assert "Sanitized invalid public snapshot JSON before rehydrate" in source
    assert "PUBLIC_METADATA_TABLES" in source
    assert "APP_TABLE_NAMES" in source
    assert '"description_html",' in source
    assert '"job_description",' in source
    assert '"responsibilities",' in source
    assert 'key_column="key"' in source
    assert 'column_names=["payload"]' in source
    assert "csv.field_size_limit(sys.maxsize)" in source
    assert "INPUT_SOURCES_PARQUET_GLOB" in source
    assert "restore_invalid_json=True" in source
    assert "json_valid" in source
    assert "--mutate-data-db-for-upload" in source
    assert "KAGGLE_USERNAME" in source
    assert "KAGGLE_KEY" in source

    assert "def download_runtime_package()" in source
    assert "def run_openopps_kaggle(" in source
    assert "def try_run_openopps_kaggle(" in source
    assert "def emit_disk_usage(" in source
    assert "PUBLIC_UPLOAD_DIR" in source
    assert "openoppsdb-public-upload" in source
    for flag in (
        "--data-db",
        "--sync-metrics",
        "--status-json",
        "--coverage-json",
        "--quality-report",
        "--prune-private-upload-files",
        "--stage-public-upload-dir",
        "--skip-notebooks",
        "--existing-stage",
        "--expected-current-version",
        "--execute",
    ):
        assert flag in source

    for removed in (
        "DATASET_METADATA =",
        "SQLITE_TABLE_METADATA =",
        "OPENOPPS_TABLE_ROWS =",
        "OPENOPPS_COLUMN_ROWS =",
        "PUBLIC_UPLOAD_DATA_FILES =",
        "SQLITE_PREVIEW_TEXT_MAX_CHARS",
        "SQLITE_PREVIEW_TEXT_COLUMNS",
        "def write_public_bundle()",
        "def write_full_table_exports",
        "def project_sqlite_for_public_upload",
        "def truncate_sqlite_text_for_public_upload",
        "def normalize_sqlite_schema_for_public_upload",
        "def rebuild_sqlite_tables_for_public_upload",
        "def update_kaggle_dataset_file_metadata(",
        "def try_update_kaggle_dataset_file_metadata(",
        "ApiUpdateDatasetMetadataRequest",
        "DatasetSettingsFile",
        "datasets.databundles.DatabundleService/UpdateDatabundleMetadataExternal",
        "def update_sqlite_table_metadata_external(",
        "def backfill_openopps_skill_tables",
        "OpenOpps skill backfill:",
        "EMBEDDED_BOUNDED_JOB_SYNC_CODE",
        "sqlite-derived-after-plain-sync",
        "bounded openopps jobs sync --metrics-json failed",
        "VACUUM INTO",
        "X-XSRF-TOKEN",
    ):
        assert removed not in source

    compact_source = "\n".join(
        line.strip() for line in source.splitlines() if line.strip()
    )
    assert (
        "require_kaggle_credentials()\ninstall_openopps()\ndownload_runtime_package()\ncopy_latest_input_db()"
    ) in compact_source
    assert "def kaggle_dataset_status()" in source
    assert "previous_status = kaggle_dataset_status()" in source
    assert "current_version_number" in source
    assert "expected_version = previous_version + 1" in source
    assert '"openopps",' in source
    assert '"sync",' in source
    assert '"--metrics-json",' in source
    assert "Running full OpenOpps snapshot" in source
    assert "OPENOPPS_KAGGLE_JOB_ROUTE_LIMIT" in source
    assert "def require_kaggle_credentials()" in source
    assert gen.DB_FILE in source

    setup_db_init = compact_source.rindex('run(["openopps", "admin", "db", "init"]')
    setup_calls = compact_source[
        compact_source.index(
            "require_kaggle_credentials()\ninstall_openopps()\ndownload_runtime_package()"
        ) : setup_db_init
    ]
    assert setup_calls.index("require_kaggle_credentials()") < setup_calls.index(
        "install_openopps()"
    )
    assert setup_calls.index("install_openopps()") < setup_calls.index(
        "download_runtime_package()"
    )
    assert setup_calls.index("download_runtime_package()") < setup_calls.index(
        "copy_latest_input_db()"
    )
    assert (
        compact_source.rindex("rehydrate_public_snapshot_for_openopps(openopps_env)")
        < setup_db_init
    )
    download_fn = source[
        source.index("def download_runtime_package()") : source.index(
            "\ndef run_openopps_kaggle(", source.index("def download_runtime_package()")
        )
    ]
    assert download_fn.index("required_runtime_package_sha256()") < download_fn.index(
        "shutil.copytree"
    )
    assert download_fn.index("digest = verify_runtime_package_manifest()") < download_fn.index(
        '"-m", "openopps_kaggle", "--help"'
    )
    assert "runtime_probe_env()" in download_fn
    run_fn = source[
        source.index("def run_openopps_kaggle(") : source.index(
            "\ndef try_run_openopps_kaggle(", source.index("def run_openopps_kaggle(")
        )
    ]
    assert run_fn.index("verify_runtime_package_manifest()") < run_fn.index(
        '"-m", "openopps_kaggle", *args'
    )
    generator_call = source.index("run_openopps_kaggle(generator_args)")
    publish_call = source.index('"publication"', generator_call)
    assert generator_call < publish_call
    publication_args = source[publish_call : source.index("])\n", publish_call)]
    assert '"--kind"' in publication_args
    assert '"public"' in publication_args
    assert '"--action"' in publication_args
    assert '"version"' in publication_args
    assert '"--stage-dir"' in publication_args
    assert "str(PUBLIC_UPLOAD_DIR)" in publication_args
    assert '"--existing-stage"' in publication_args
    assert '"--ledger"' in publication_args
    assert '"--expected-current-version"' in publication_args
    assert '"--execute"' in publication_args
    assert 'run([\n    "kaggle",\n    "datasets",\n    "version"' not in source
    assert "OpenOpps exact publication/readback ledger:" in source
    assert '"metadataRepair": "separate-maintainer-action"' in source
    assert 'emit_disk_usage("before_artifact_export")' in source
    assert 'emit_disk_usage("after_artifact_export")' in source
    assert 'emit_disk_usage("before_dataset_publish")' in source
    export_disk_call = source.index('emit_disk_usage("before_artifact_export")')
    export_generator_call = source.index("run_openopps_kaggle(generator_args)")
    assert export_disk_call < export_generator_call
    publish_disk_call = source.index('emit_disk_usage("before_dataset_publish")')
    publish_command = source.index('"publication"', export_generator_call)
    assert publish_disk_call < publish_command
    assert gen.DATASET_IMAGE_SOURCE.as_posix() == "web/public/social/openoppsdb.png"


def test_manager_notebook_rehydrates_public_sqlite_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENOPPS_KAGGLE_OUTPUT_DIR", str(tmp_path / "openoppsdb"))
    namespace = _notebook_setup_namespace()
    db_path: Path = namespace["DB_PATH"]
    assert namespace["APP_TABLE_NAMES"] == tuple(
        table.name for table in gen.DATA_TABLES
    )
    schema_db = tmp_path / "operational-schema.sqlite"
    store = OpenOppsStore(OpenOppsSettings(db_url=f"sqlite:///{schema_db}"))
    store.init_db()
    _insert_representative_app_rows(schema_db)
    _copy_plain_public_snapshot(
        schema_db,
        db_path,
        app_table_names=namespace["APP_TABLE_NAMES"],
    )
    with sqlite3.connect(db_path) as conn:
        for table_name in namespace["PARQUET_RESTORE_TABLES"]:
            conn.execute(f"DELETE FROM {_quote_identifier(table_name)}")
        conn.commit()
    input_dir = tmp_path / "input"
    parquet_dir = input_dir / "dataset" / "exports" / "parquet"
    parquet_dir.mkdir(parents=True)
    gen.pl.DataFrame(
        {
            "key": ["source-1"],
            "raw_metadata": ['{"catalog":"fixture","restored":true}'],
        }
    ).write_parquet(parquet_dir / "sources.parquet")
    gen.pl.DataFrame(
        {
            "key": ["board-1"],
            "source_board_keys": ['{"source-1":"source-1:board-1"}'],
            "markets": ['["SaaS","AI"]'],
            "locations": ['["New York","Remote"]'],
            "raw_payload": ['{"board":true}'],
        }
    ).write_parquet(parquet_dir / "boards.parquet")
    gen.pl.DataFrame(
        {
            "id": ["version-1"],
            "locations": ['["New York","Remote"]'],
            "description": ["Build products."],
            "description_html": ["<p>Build products.</p>"],
            "job_description": ['{"title":"Software Engineer"}'],
            "responsibilities": ['["Build"]'],
            "qualifications": ['["Python"]'],
            "skills": ['[{"name":"Python"}]'],
            "compensation": ['{"currency":"USD"}'],
        }
    ).write_parquet(parquet_dir / "job_versions.parquet")
    gen.pl.DataFrame({"id": ["payload-1"], "payload": ['{"raw":true}']}).write_parquet(
        parquet_dir / "job_payload_snapshots.parquet"
    )
    gen.pl.DataFrame(
        {
            "id": ["location-1"],
            "job_version_id": ["version-1"],
            "ordinal": [0],
            "label": ["New York"],
        }
    ).write_parquet(parquet_dir / "job_version_locations.parquet")
    gen.pl.DataFrame(
        {
            "id": ["skill-1"],
            "job_version_id": ["version-1"],
            "ordinal": [0],
            "name": ["Python"],
            "level": ["mid"],
        }
    ).write_parquet(parquet_dir / "job_version_skills.parquet")
    gen.pl.DataFrame(
        {
            "id": ["keyword-1"],
            "skill_id": ["skill-1"],
            "ordinal": [0],
            "keyword": ["python"],
        }
    ).write_parquet(parquet_dir / "job_version_skill_keywords.parquet")
    gen.pl.DataFrame(
        {
            "id": ["bullet-1"],
            "job_version_id": ["version-1"],
            "kind": ["responsibility"],
            "ordinal": [0],
            "text": ["Build products."],
        }
    ).write_parquet(parquet_dir / "job_version_bullets.parquet")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE sources SET raw_metadata = ? WHERE key = ?", ('{"bad":', "source-1")
        )
        conn.execute(
            """
            UPDATE boards
            SET source_board_keys = ?, markets = ?, locations = ?, raw_payload = NULL
            WHERE key = ?
            """,
            ('{"bad":', '["AI"', '["Remote"', "board-1"),
        )
        conn.execute(
            """
            UPDATE job_versions
            SET locations = ?, description = NULL, description_html = NULL,
                job_description = NULL, responsibilities = NULL,
                qualifications = NULL, skills = NULL, compensation = NULL
            WHERE id = ?
            """,
            ('["Remote"', "version-1"),
        )
        conn.execute(
            "UPDATE job_payload_snapshots SET payload = NULL WHERE id = ?",
            ("payload-1",),
        )
        conn.commit()
    namespace["KAGGLE_INPUT_DIR"] = input_dir
    namespace["restore_projected_sqlite_columns_from_input_exports"]()

    assert namespace["is_public_snapshot_db"](db_path) is True

    def run_locally(command, *, env=None, timeout_seconds=None) -> None:
        del timeout_seconds
        if command == ["openopps", "admin", "db", "init"]:
            assert env is not None
            OpenOppsStore(OpenOppsSettings(db_url=env["OPENOPPS_DB_URL"])).init_db()
            return
        raise AssertionError(f"Unexpected command during rehydrate test: {command}")

    namespace["run"] = run_locally
    env = {
        "OPENOPPS_DB_URL": f"sqlite:///{db_path}",
        "OPENOPPS_CACHE_ENABLED": "false",
    }

    assert namespace["rehydrate_public_snapshot_for_openopps"](env) is True
    assert namespace["rehydrate_public_snapshot_for_openopps"](env) is False

    snapshot_path = db_path.with_name("openoppsdb-public-snapshot.sqlite")
    assert snapshot_path.exists()
    with sqlite3.connect(db_path) as conn:
        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        counts = {
            table_name: conn.execute(
                f"SELECT count(*) FROM {_quote_identifier(table_name)}"
            ).fetchone()[0]
            for table_name in namespace["APP_TABLE_NAMES"]
        }

        assert version == ("0004_job_sync_run_lifecycle",)
        assert "openopps_tables" not in tables
        assert "openopps_columns" not in tables
        assert all(count == 1 for count in counts.values())
        assert _has_sqlite_index(
            conn, "boards", ("source_key", "remote_id"), unique=True
        )
        assert _has_sqlite_index(
            conn, "jobs", ("board_key", "provider_id", "remote_id"), unique=True
        )
        assert _has_sqlite_index(
            conn, "job_version_skills", ("job_version_id", "ordinal"), unique=True
        )
        assert conn.execute(
            "SELECT json_valid(raw_metadata) FROM sources WHERE key = 'source-1'"
        ).fetchone() == (1,)
        assert conn.execute(
            "SELECT json_valid(source_board_keys), json_valid(markets), "
            "json_valid(locations), json_valid(raw_payload) "
            "FROM boards WHERE key = 'board-1'"
        ).fetchone() == (1, 1, 1, 1)
        assert conn.execute(
            "SELECT json_valid(locations), json_valid(job_description), "
            "json_valid(responsibilities), json_valid(qualifications), "
            "json_valid(skills), json_valid(compensation) "
            "FROM job_versions WHERE id = 'version-1'"
        ).fetchone() == (1, 1, 1, 1, 1, 1)

    assert OpenOppsStore(OpenOppsSettings(db_url=f"sqlite:///{db_path}")).status() == {
        "sources": 1,
        "boards": 1,
        "boardProviders": 1,
        "jobs": 1,
    }


_PRE_0004_JOB_SYNC_RUN_COLUMNS = (
    "id",
    "board_key",
    "provider_id",
    "synced_at",
    "success",
    "error",
    "job_count",
    "new_count",
    "unchanged_count",
    "changed_count",
    "reopened_count",
    "closed_count",
)


def _strip_job_sync_run_columns(db_path: Path, keep: tuple[str, ...]) -> None:
    column_sql = ", ".join(_quote_identifier(column) for column in keep)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"CREATE TABLE job_sync_runs_legacy AS SELECT {column_sql} FROM job_sync_runs"
        )
        conn.execute("DROP TABLE job_sync_runs")
        conn.execute("ALTER TABLE job_sync_runs_legacy RENAME TO job_sync_runs")
        conn.commit()


def test_manager_notebook_rehydrates_pre_0004_job_sync_runs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENOPPS_KAGGLE_OUTPUT_DIR", str(tmp_path / "openoppsdb"))
    namespace = _notebook_setup_namespace()
    db_path: Path = namespace["DB_PATH"]
    schema_db = tmp_path / "operational-schema.sqlite"
    store = OpenOppsStore(OpenOppsSettings(db_url=f"sqlite:///{schema_db}"))
    store.init_db()
    _insert_representative_app_rows(schema_db)
    _copy_plain_public_snapshot(
        schema_db,
        db_path,
        app_table_names=namespace["APP_TABLE_NAMES"],
    )
    _strip_job_sync_run_columns(db_path, _PRE_0004_JOB_SYNC_RUN_COLUMNS)
    observed_at = "2026-06-16 12:00:00"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO job_sync_runs (
                id, board_key, provider_id, synced_at, success, error, job_count,
                new_count, unchanged_count, changed_count, reopened_count,
                closed_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "sync-run-legacy-failed",
                "board-1",
                "greenhouse",
                observed_at,
                0,
                "legacy failure",
                0,
                0,
                0,
                0,
                0,
                0,
            ),
        )
        conn.execute(
            """
            INSERT INTO job_sync_runs (
                id, board_key, provider_id, synced_at, success, error, job_count,
                new_count, unchanged_count, changed_count, reopened_count,
                closed_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "sync-run-legacy-unknown",
                "board-1",
                "greenhouse",
                observed_at,
                0,
                None,
                0,
                0,
                0,
                0,
                0,
                0,
            ),
        )
        conn.commit()

    def run_locally(command, *, env=None, timeout_seconds=None) -> None:
        del timeout_seconds
        if command == ["openopps", "admin", "db", "init"]:
            assert env is not None
            OpenOppsStore(OpenOppsSettings(db_url=env["OPENOPPS_DB_URL"])).init_db()
            return
        raise AssertionError(f"Unexpected command during rehydrate test: {command}")

    namespace["run"] = run_locally
    env = {
        "OPENOPPS_DB_URL": f"sqlite:///{db_path}",
        "OPENOPPS_CACHE_ENABLED": "false",
    }

    assert namespace["rehydrate_public_snapshot_for_openopps"](env) is True

    with sqlite3.connect(db_path) as conn:
        rows = {
            row[0]: row[1:]
            for row in conn.execute(
                """
                SELECT id, status, started_at, finished_at, error_kind,
                       committed_batch_count, authoritative, success
                FROM job_sync_runs
                ORDER BY id
                """
            )
        }
    assert rows["sync-run-1"] == (
        "succeeded",
        observed_at,
        observed_at,
        None,
        0,
        1,
        1,
    )
    assert rows["sync-run-legacy-failed"] == (
        "failed",
        observed_at,
        observed_at,
        "legacy_failure",
        0,
        0,
        0,
    )
    assert rows["sync-run-legacy-unknown"] == (
        "failed",
        observed_at,
        observed_at,
        "unknown",
        0,
        0,
        0,
    )


def test_manager_notebook_rehydrate_rejects_unmapped_missing_column(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENOPPS_KAGGLE_OUTPUT_DIR", str(tmp_path / "openoppsdb"))
    namespace = _notebook_setup_namespace()
    db_path: Path = namespace["DB_PATH"]
    schema_db = tmp_path / "operational-schema.sqlite"
    OpenOppsStore(OpenOppsSettings(db_url=f"sqlite:///{schema_db}")).init_db()
    _insert_representative_app_rows(schema_db)
    _copy_plain_public_snapshot(
        schema_db,
        db_path,
        app_table_names=namespace["APP_TABLE_NAMES"],
    )
    keep = tuple(
        column
        for column in _PRE_0004_JOB_SYNC_RUN_COLUMNS
        if column != "job_count"
    )
    _strip_job_sync_run_columns(db_path, keep)

    def run_locally(command, *, env=None, timeout_seconds=None) -> None:
        del timeout_seconds
        if command == ["openopps", "admin", "db", "init"]:
            assert env is not None
            OpenOppsStore(OpenOppsSettings(db_url=env["OPENOPPS_DB_URL"])).init_db()
            return
        raise AssertionError(f"Unexpected command during rehydrate test: {command}")

    namespace["run"] = run_locally
    env = {
        "OPENOPPS_DB_URL": f"sqlite:///{db_path}",
        "OPENOPPS_CACHE_ENABLED": "false",
    }

    with pytest.raises(RuntimeError, match="missing required columns: job_count"):
        namespace["rehydrate_public_snapshot_for_openopps"](env)


def test_manager_loads_package_spec_from_notebook_secret(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENOPPS_KAGGLE_OUTPUT_DIR", str(tmp_path / "openoppsdb"))
    monkeypatch.delenv("OPENOPPS_PACKAGE_SPEC", raising=False)
    namespace = _notebook_setup_namespace()
    assert namespace["PACKAGE_SPEC"] == "__OPENOPPS_IMMUTABLE_PACKAGE_SPEC_REQUIRED__"

    package_spec = (
        "git+https://github.com/wyattowalsh/openopps.git@"
        "0123456789abcdef0123456789abcdef01234567"
    )

    class FakeSecrets:
        def get_secret(self, name: str) -> str:
            if name == "OPENOPPS_PACKAGE_SPEC":
                return package_spec
            raise RuntimeError(f"missing secret {name}")

    fake_module: Any = types.ModuleType("kaggle_secrets")
    fake_module.UserSecretsClient = lambda: FakeSecrets()
    monkeypatch.setitem(sys.modules, "kaggle_secrets", fake_module)

    namespace["load_openopps_package_spec_secret"]()
    assert namespace["PACKAGE_SPEC"] == package_spec


def test_manager_runs_full_openopps_sync_for_synthetic_example_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENOPPS_KAGGLE_OUTPUT_DIR", str(tmp_path / "openoppsdb"))
    namespace = _notebook_setup_namespace()
    db_path: Path = namespace["DB_PATH"]
    OpenOppsStore(OpenOppsSettings(db_url=f"sqlite:///{db_path}")).init_db()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO sources (key, url, provider_id)
            VALUES ('example', 'example://openopps/synthetic', 'example')
            """
        )
        conn.commit()
    calls = _record_sync_calls(namespace)
    namespace["run_sync_metrics"](
        tmp_path / "sync_metrics.json",
        env={"OPENOPPS_JOB_ROUTE_FRESHNESS_SECONDS": "86400"},
        timeout_seconds=1,
    )
    assert calls
    assert calls[0][:3] == ["openopps", "sync", "--metrics-json"]


def _record_sync_calls(namespace: dict[str, Any]) -> list[list[str]]:
    calls: list[list[str]] = []

    def capture_run_json(command, *args, **kwargs):
        del args, kwargs
        calls.append(list(command))
        return {"name": "jobs.sync", "jobSyncRuns": 0, "jobsPersisted": 0}

    namespace["run"] = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("run() must not be used when jobs sync is delegated to run_json")
    )
    namespace["run_json"] = capture_run_json
    return calls


def test_manager_runs_jobs_sync_for_real_https_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENOPPS_KAGGLE_OUTPUT_DIR", str(tmp_path / "openoppsdb"))
    namespace = _notebook_setup_namespace()
    db_path: Path = namespace["DB_PATH"]
    OpenOppsStore(OpenOppsSettings(db_url=f"sqlite:///{db_path}")).init_db()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO sources (key, url, provider_id)
            VALUES ('acme', 'https://jobs.example.com', 'greenhouse')
            """
        )
        conn.commit()
    calls = _record_sync_calls(namespace)
    namespace["run_sync_metrics"](
        tmp_path / "sync_metrics.json",
        env={"OPENOPPS_JOB_ROUTE_FRESHNESS_SECONDS": "86400"},
        timeout_seconds=1,
    )
    assert calls
    assert calls[0][:3] == ["openopps", "sync", "--metrics-json"]


def test_manager_runs_jobs_sync_for_mixed_example_and_real_sources(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENOPPS_KAGGLE_OUTPUT_DIR", str(tmp_path / "openoppsdb"))
    namespace = _notebook_setup_namespace()
    db_path: Path = namespace["DB_PATH"]
    OpenOppsStore(OpenOppsSettings(db_url=f"sqlite:///{db_path}")).init_db()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO sources (key, url, provider_id)
            VALUES
                ('example', 'example://openopps/synthetic', 'example'),
                ('acme', 'https://jobs.example.com', 'greenhouse')
            """
        )
        conn.commit()
    calls = _record_sync_calls(namespace)
    namespace["run_sync_metrics"](
        tmp_path / "sync_metrics.json",
        env={"OPENOPPS_JOB_ROUTE_FRESHNESS_SECONDS": "86400"},
        timeout_seconds=1,
    )
    assert calls
    assert calls[0][:3] == ["openopps", "sync", "--metrics-json"]


def test_manager_does_not_skip_jobs_sync_when_sources_are_empty(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENOPPS_KAGGLE_OUTPUT_DIR", str(tmp_path / "openoppsdb"))
    namespace = _notebook_setup_namespace()
    db_path: Path = namespace["DB_PATH"]
    OpenOppsStore(OpenOppsSettings(db_url=f"sqlite:///{db_path}")).init_db()
    calls = _record_sync_calls(namespace)
    namespace["run_sync_metrics"](
        tmp_path / "sync_metrics.json",
        env={"OPENOPPS_JOB_ROUTE_FRESHNESS_SECONDS": "86400"},
        timeout_seconds=1,
    )
    assert calls
    assert calls[0][:3] == ["openopps", "sync", "--metrics-json"]


def test_kaggle_starter_notebook_is_public_read_only_example() -> None:
    metadata = gen.starter_kernel_metadata()
    data = gen.starter_notebook()
    source = "\n".join(
        line for cell in data["cells"] for line in cell.get("source", [])
    )

    assert metadata["kernel_type"] == "notebook"
    assert metadata["enable_internet"] is False
    assert metadata["is_private"] is False
    assert metadata["id"] == gen.STARTER_NB_ID
    assert metadata["title"] == "OpenOppsDB starter notebook"
    assert metadata["dataset_sources"] == [gen.DATASET_ID]
    assert metadata["code_file"] == gen.STARTER_NB_FILE
    assert metadata["code_file"].endswith(".ipynb")
    assert "/kaggle/input" in source
    assert "**/openoppsdb.sqlite" in source
    assert "mode=ro&immutable=1" in source
    assert gen.DB_FILE in source
    assert "openopps_tables" in source
    assert "job_versions" in source
    assert "KAGGLE_KEY" not in source
    assert "KAGGLE_USERNAME" not in source
    assert "kaggle datasets version" not in source


def test_public_example_notebooks_are_read_only_and_compile() -> None:
    expected = {
        gen.ADVANCED_NB_ID: {
            "title": "OpenOppsDB advanced usage",
            "code_file": gen.ADVANCED_NB_FILE,
            "required_terms": (
                "job_sync_observations",
                "pd.read_parquet",
                "mode=ro&immutable=1",
            ),
        },
        gen.HIRING_MARKET_NB_ID: {
            "title": "OpenOppsDB hiring market map",
            "code_file": gen.HIRING_MARKET_NB_FILE,
            "required_terms": (
                "job_version_locations",
                "provider_mix",
                "plt.subplots",
            ),
        },
        gen.SKILLS_RADAR_NB_ID: {
            "title": "OpenOppsDB skills radar",
            "code_file": gen.SKILLS_RADAR_NB_FILE,
            "required_terms": (
                "job_version_skills",
                "job_version_skill_keywords",
                "skill_pairs",
            ),
        },
    }

    assert {spec.notebook_id for spec in gen.PUBLIC_EXAMPLE_NOTEBOOKS} == set(expected)

    for spec in gen.PUBLIC_EXAMPLE_NOTEBOOKS:
        metadata = gen.public_notebook_kernel_metadata(
            notebook_id=spec.notebook_id,
            title=spec.title,
            code_file=spec.code_file,
        )
        data = spec.notebook_factory()
        source = "\n".join(
            line for cell in data["cells"] for line in cell.get("source", [])
        )
        for index, cell in enumerate(data["cells"]):
            if cell.get("cell_type") == "code":
                compile("".join(cell.get("source", [])), f"{spec.slug}-{index}", "exec")

        assert metadata["kernel_type"] == "notebook"
        assert metadata["enable_internet"] is False
        assert metadata["is_private"] is False
        assert metadata["id"] == spec.notebook_id
        assert metadata["title"] == expected[spec.notebook_id]["title"]
        assert metadata["dataset_sources"] == [gen.DATASET_ID]
        assert metadata["code_file"] == expected[spec.notebook_id]["code_file"]
        assert metadata["code_file"].endswith(".ipynb")
        assert "/kaggle/input" in source
        assert "**/openoppsdb.sqlite" in source
        assert "mode=ro&immutable=1" in source
        assert "KAGGLE_KEY" not in source
        assert "KAGGLE_USERNAME" not in source
        assert "kaggle datasets version" not in source
        assert "pip install" not in source
        for term in expected[spec.notebook_id]["required_terms"]:
            assert term in source


def test_kaggle_notebook_pullback_verifier_accepts_expected_bundles(
    tmp_path: Path,
) -> None:
    _write_pullback_expected_bundles(
        tmp_path,
        starter_alias=True,
        kaggle_pull_metadata=True,
    )

    assert pullback.main([str(tmp_path)]) == 0


def test_kaggle_notebook_pullback_verifier_rejects_stale_source(
    tmp_path: Path,
    capsys,
) -> None:
    def mutate(expected, metadata, notebook):
        if expected.kernel_id == gen.ADVANCED_NB_ID:
            notebook["cells"][0]["source"][0] = "# stale notebook\n"

    _write_pullback_expected_bundles(tmp_path, mutate=mutate)

    assert pullback.main([str(tmp_path)]) == 1
    assert "notebook does not match generated source" in capsys.readouterr().err


def test_kaggle_notebook_pullback_verifier_rejects_missing_generated_cell(
    tmp_path: Path,
    capsys,
) -> None:
    def mutate(expected, metadata, notebook):
        if expected.kernel_id == gen.SKILLS_RADAR_NB_ID:
            notebook["cells"].pop()

    _write_pullback_expected_bundles(tmp_path, mutate=mutate)

    assert pullback.main([str(tmp_path)]) == 1
    assert "notebook does not match generated source" in capsys.readouterr().err


def test_kaggle_notebook_pullback_verifier_rejects_metadata_drift(
    tmp_path: Path,
    capsys,
) -> None:
    def mutate(expected, metadata, notebook):
        if expected.kernel_id == gen.HIRING_MARKET_NB_ID:
            metadata["enable_internet"] = True

    _write_pullback_expected_bundles(tmp_path, mutate=mutate)

    assert pullback.main([str(tmp_path)]) == 1
    assert (
        "kernel-metadata.json does not match generated metadata"
        in capsys.readouterr().err
    )


def test_kaggle_notebook_pullback_verifier_rejects_wrong_dataset_source(
    tmp_path: Path,
    capsys,
) -> None:
    def mutate(expected, metadata, notebook):
        if expected.kernel_id == gen.ADVANCED_NB_ID:
            metadata["dataset_sources"] = ["wyattowalsh/not-openoppsdb"]

    _write_pullback_expected_bundles(tmp_path, mutate=mutate)

    assert pullback.main([str(tmp_path)]) == 1
    assert "dataset_sources" in capsys.readouterr().err


def test_kaggle_notebook_pullback_verifier_rejects_credential_terms(
    tmp_path: Path,
    capsys,
) -> None:
    def mutate(expected, metadata, notebook):
        if expected.kernel_id == gen.SKILLS_RADAR_NB_ID:
            notebook["cells"][1]["source"].append('print("KAGGLE_API_TOKEN")\n')

    _write_pullback_expected_bundles(tmp_path, mutate=mutate)

    assert pullback.main([str(tmp_path)]) == 1
    assert "notebook source contains 'KAGGLE_API_TOKEN'" in capsys.readouterr().err


def _write_pullback_expected_bundles(
    root: Path,
    *,
    starter_alias: bool = False,
    kaggle_pull_metadata: bool = False,
    mutate=None,
) -> None:
    for expected in pullback.expected_kernels():
        metadata = _json_clone(expected.metadata)
        notebook = _json_clone(expected.notebook)
        if starter_alias and expected.kernel_id == gen.STARTER_NB_ID:
            metadata["code_file"] = pullback.STARTER_PULL_CODE_FILE_ALIAS
        if kaggle_pull_metadata:
            metadata["docker_image"] = (
                "gcr.io/kaggle-images/python@sha256:"
                "e5452ce6268c2e8345cfe5141f31ca7ff47032aca46a7ea532bbb87481281d0c"
            )
            metadata["id_no"] = 123456
            if expected.kernel_id == gen.STARTER_NB_ID:
                metadata["keywords"] = ["jobs and career"]
        if mutate is not None:
            mutate(expected, metadata, notebook)

        kernel_dir = root / expected.slug
        kernel_dir.mkdir()
        code_file = metadata["code_file"]
        (kernel_dir / "kernel-metadata.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (kernel_dir / code_file).write_text(
            json.dumps(notebook, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _json_clone(data):
    return json.loads(json.dumps(data))


def test_generated_kaggle_metadata_artifacts_are_current() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    kaggle_dir = repo_root / "kaggle"

    generated_dataset = json.loads(
        (kaggle_dir / "dataset-metadata.json").read_text(encoding="utf-8")
    )
    generated_kernel = json.loads(
        (kaggle_dir / "kernel-metadata.json").read_text(encoding="utf-8")
    )
    generated_notebook = json.loads(
        (kaggle_dir / gen.NB_FILE).read_text(encoding="utf-8")
    )
    starter_dir = kaggle_dir / "starter"
    generated_starter_kernel = json.loads(
        (starter_dir / "kernel-metadata.json").read_text(encoding="utf-8")
    )
    generated_starter_notebook = json.loads(
        (starter_dir / gen.STARTER_NB_FILE).read_text(encoding="utf-8")
    )
    examples_dir = kaggle_dir / "examples"
    generated_examples = {}
    for spec in gen.PUBLIC_EXAMPLE_NOTEBOOKS:
        notebook_dir = examples_dir / spec.slug
        generated_examples[spec.slug] = {
            "kernel": json.loads(
                (notebook_dir / "kernel-metadata.json").read_text(encoding="utf-8")
            ),
            "notebook": json.loads(
                (notebook_dir / spec.code_file).read_text(encoding="utf-8")
            ),
        }

    assert generated_dataset == gen.dataset_metadata()
    assert generated_kernel == gen.kernel_metadata()
    assert generated_notebook == gen.notebook()
    assert generated_starter_kernel == gen.starter_kernel_metadata()
    assert generated_starter_notebook == gen.starter_notebook()
    assert sorted(path.name for path in examples_dir.iterdir()) == sorted(
        spec.slug for spec in gen.PUBLIC_EXAMPLE_NOTEBOOKS
    )
    for spec in gen.PUBLIC_EXAMPLE_NOTEBOOKS:
        assert generated_examples[spec.slug][
            "kernel"
        ] == gen.public_notebook_kernel_metadata(
            notebook_id=spec.notebook_id,
            title=spec.title,
            code_file=spec.code_file,
        )
        assert generated_examples[spec.slug]["notebook"] == spec.notebook_factory()
    assert not (kaggle_dir / gen.DATAPACKAGE_FILE).exists()
    assert not (kaggle_dir / gen.EXPOSED_DATAPACKAGE_FILE).exists()
    assert not any((repo_root / "kaggle-manager").glob("*"))
    assert not (kaggle_dir / "notebooks").exists()
    assert (kaggle_dir / gen.DATASET_IMAGE_FILE).is_file()
    assert generated_dataset["image"] == gen.DATASET_IMAGE_FILE


def test_generated_kaggle_dataset_image_matches_metadata_contract() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    kaggle_dir = repo_root / "kaggle"
    source = repo_root / gen.DATASET_IMAGE_SOURCE
    image = kaggle_dir / gen.DATASET_IMAGE_FILE
    metadata = json.loads(
        (kaggle_dir / "dataset-metadata.json").read_text(encoding="utf-8")
    )

    assert metadata["image"] == gen.DATASET_IMAGE_FILE
    assert source.is_file()
    assert image.is_file()
    assert image.read_bytes() == source.read_bytes()
    assert image.suffix == ".png"
    width, height = _png_dimensions(image)
    assert width >= 560
    assert height >= 280
    assert width == 1200
    assert height == 630


def test_data_artifact_writer_adds_metadata_before_exports() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert source.index(
        "_restore_projected_sqlite_columns_from_export_dir("
    ) < source.index("_clean_data_artifacts(output_dir, preserve=source_db)")
    assert source.index("_drop_private_sqlite_tables(build_db)") < source.index(
        "_backfill_sqlite_skill_tables(build_db)"
    )
    assert source.index("_backfill_sqlite_skill_tables(build_db)") < source.index(
        "_write_sqlite_metadata(build_db)"
    )
    assert source.index("_write_sqlite_metadata(build_db)") < source.index(
        "_write_full_table_exports(output_dir, build_db)"
    )
    assert source.index(
        "_write_full_table_exports(output_dir, build_db)"
    ) < source.index("_project_sqlite_for_public_upload(build_db)")
    assert source.index("_project_sqlite_for_public_upload(build_db)") < source.index(
        "_truncate_sqlite_text_for_public_upload(build_db)"
    )
    assert "_empty_sqlite_tables_for_public_upload(build_db)" not in source
    assert source.index(
        "_truncate_sqlite_text_for_public_upload(build_db)"
    ) < source.index("_normalize_sqlite_schema_for_public_upload(build_db)")
    assert source.index(
        "_normalize_sqlite_schema_for_public_upload(build_db)"
    ) < source.index("_rebuild_sqlite_tables_for_public_upload(build_db)")
    assert source.index(
        "_rebuild_sqlite_tables_for_public_upload(build_db)"
    ) < source.index("_finalize_sqlite_for_upload(build_db)")


def test_table_csv_export_serializes_sources_for_polars(
    tmp_path: Path,
) -> None:
    db_path = _write_quality_bundle(tmp_path)
    csv_path = tmp_path / "sources.csv"
    sources_table = next(table for table in gen.TABLES if table.name == "sources")

    with sqlite3.connect(db_path) as conn:
        gen._write_table_csv(conn, sources_table, csv_path)

    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))

    assert "enabled" not in rows[0]
    gen.pl.scan_csv(
        csv_path,
        schema_overrides=gen._polars_schema_overrides(sources_table),
        infer_schema_length=0,
        low_memory=True,
        try_parse_dates=True,
    ).sink_parquet(tmp_path / "sources.parquet")


def test_sqlite_upload_projection_preserves_operational_columns(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "projection.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE job_versions (
                id TEXT PRIMARY KEY,
                description TEXT,
                description_html TEXT,
                job_description TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE job_payload_snapshots (
                id TEXT PRIMARY KEY,
                payload TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO job_versions VALUES (?, ?, ?, ?)",
            (
                "version-1",
                "plain text",
                "<p>plain text</p>",
                '{"title":"Engineer"}',
            ),
        )
        conn.execute(
            "INSERT INTO job_versions VALUES (?, ?, ?, ?)",
            ("version-2", "already compact", None, None),
        )
        conn.execute(
            "INSERT INTO job_payload_snapshots VALUES (?, ?)",
            ("payload-1", '{"raw":true}'),
        )

    result = gen._project_sqlite_for_public_upload(db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, description, description_html, job_description "
            "FROM job_versions ORDER BY id"
        ).fetchall()
        payload_rows = conn.execute(
            "SELECT id, payload FROM job_payload_snapshots ORDER BY id"
        ).fetchall()

    assert result == {"projected_columns": 0, "projected_rows": 0}
    assert rows == [
        ("version-1", "plain text", "<p>plain text</p>", '{"title":"Engineer"}'),
        ("version-2", "already compact", None, None),
    ]
    assert payload_rows == [("payload-1", '{"raw":true}')]

    rebuild_result = gen._rebuild_sqlite_tables_for_public_upload(db_path)

    with sqlite3.connect(db_path) as conn:
        rebuilt_rows = conn.execute(
            "SELECT id, description, description_html, job_description "
            "FROM job_versions ORDER BY id"
        ).fetchall()
        rebuilt_payload_rows = conn.execute(
            "SELECT id, payload FROM job_payload_snapshots ORDER BY id"
        ).fetchall()

    assert rebuild_result == {"tables": 2, "rows": 3}
    assert rebuilt_rows == [
        ("version-1", "plain text", "<p>plain text</p>", '{"title":"Engineer"}'),
        ("version-2", "already compact", None, None),
    ]
    assert rebuilt_payload_rows == [("payload-1", '{"raw":true}')]


def test_sqlite_upload_truncates_residual_long_text_cells(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "preview.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE sample (
                id TEXT PRIMARY KEY,
                short_text TEXT,
                long_text TEXT,
                payload JSON,
                score REAL
            )
            """
        )
        conn.execute(
            "INSERT INTO sample VALUES (?, ?, ?, ?, ?)",
            ("one", "short", "abcdef", '{"abcdef": true}', 1.5),
        )

    result = gen._truncate_sqlite_text_for_public_upload(
        db_path,
        max_chars=5,
        columns=(
            ("sample", "short_text"),
            ("sample", "long_text"),
            ("sample", "payload"),
        ),
    )

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT short_text, long_text, payload, score FROM sample"
        ).fetchone()

    assert result == {"truncated_rows": 2, "estimated_bytes_removed": 12}
    assert row == ("short", "abcde", '{"abc', 1.5)


def test_data_artifact_writer_restores_derived_child_tables_from_parquet(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "preview.sqlite"
    parquet_dir = tmp_path / gen.PARQUET_DIR
    parquet_dir.mkdir(parents=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE job_version_bullets (
                id TEXT,
                job_version_id TEXT,
                kind TEXT,
                ordinal INTEGER,
                text TEXT
            )
            """
        )
    gen.pl.DataFrame(
        {
            "id": ["bullet-1"],
            "job_version_id": ["version-1"],
            "kind": ["responsibility"],
            "ordinal": [0],
            "text": ["Build products."],
        }
    ).write_parquet(parquet_dir / "job_version_bullets.parquet")

    result = gen._restore_derived_sqlite_tables_from_export_dir(
        db_path,
        parquet_dir,
        table_names=("job_version_bullets",),
    )

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM job_version_bullets").fetchall()

    assert result == {"job_version_bullets": 1}
    assert rows == [("bullet-1", "version-1", "responsibility", 0, "Build products.")]


def test_data_artifact_writer_backfills_version_child_tables_from_json(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "preview.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE job_versions (
                id TEXT PRIMARY KEY,
                locations TEXT,
                responsibilities TEXT,
                qualifications TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE job_version_locations (
                id TEXT,
                job_version_id TEXT,
                ordinal INTEGER,
                label TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE job_version_bullets (
                id TEXT,
                job_version_id TEXT,
                kind TEXT,
                ordinal INTEGER,
                text TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO job_versions VALUES (?, ?, ?, ?)",
            (
                "version-1",
                '["New York","Remote"]',
                '["Build products."]',
                '["Write Python."]',
            ),
        )

    result = gen._backfill_sqlite_version_child_tables(db_path)

    with sqlite3.connect(db_path) as conn:
        locations = conn.execute(
            """
            SELECT id, job_version_id, ordinal, label
            FROM job_version_locations
            ORDER BY ordinal
            """
        ).fetchall()
        bullets = conn.execute(
            """
            SELECT id, job_version_id, kind, ordinal, text
            FROM job_version_bullets
            ORDER BY kind, ordinal
            """
        ).fetchall()

    assert result == {
        "versionsExamined": 1,
        "locationsInserted": 2,
        "bulletsInserted": 2,
    }
    assert locations == [
        (
            gen.stable_id("version-1", "location", "0", "New York"),
            "version-1",
            0,
            "New York",
        ),
        (
            gen.stable_id("version-1", "location", "1", "Remote"),
            "version-1",
            1,
            "Remote",
        ),
    ]
    assert bullets == [
        (
            gen.stable_id("version-1", "qualification", "0", "Write Python."),
            "version-1",
            "qualification",
            0,
            "Write Python.",
        ),
        (
            gen.stable_id("version-1", "responsibility", "0", "Build products."),
            "version-1",
            "responsibility",
            0,
            "Build products.",
        ),
    ]


def test_local_data_artifact_writer_restores_projected_columns_from_parquet(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / gen.DB_FILE
    parquet_dir = tmp_path / gen.PARQUET_DIR
    parquet_dir.mkdir(parents=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE sources (
                "key" TEXT PRIMARY KEY,
                raw_metadata TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE boards (
                "key" TEXT PRIMARY KEY,
                source_board_keys TEXT,
                markets TEXT,
                locations TEXT,
                raw_payload TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE job_versions (
                id TEXT PRIMARY KEY,
                locations TEXT,
                description TEXT,
                description_html TEXT,
                job_description TEXT,
                responsibilities TEXT,
                qualifications TEXT,
                skills TEXT,
                compensation TEXT
            )
            """
        )
        conn.execute(
            "CREATE TABLE job_payload_snapshots (id TEXT PRIMARY KEY, payload TEXT)"
        )
        conn.execute("INSERT INTO sources VALUES ('source-1', ?)", ('{"bad":',))
        conn.execute(
            "INSERT INTO boards VALUES ('board-1', ?, ?, ?, NULL)",
            ('{"bad":', '["AI"', '["Remote"'),
        )
        conn.execute(
            "INSERT INTO job_versions VALUES ('version-1', ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL)",
            ('["Remote"',),
        )
        conn.execute("INSERT INTO job_payload_snapshots VALUES ('payload-1', NULL)")
    gen.pl.DataFrame(
        {
            "key": ["source-1"],
            "raw_metadata": ['{"restored": true}'],
        }
    ).write_parquet(parquet_dir / "sources.parquet")
    gen.pl.DataFrame(
        {
            "key": ["board-1"],
            "source_board_keys": ['{"source-1": "source-1:board-1"}'],
            "markets": ['["AI", "SaaS"]'],
            "locations": ['["Remote", "New York"]'],
            "raw_payload": ['{"board": true}'],
        }
    ).write_parquet(parquet_dir / "boards.parquet")
    gen.pl.DataFrame(
        {
            "id": ["version-1"],
            "locations": ['["Remote", "New York"]'],
            "description": ["plain"],
            "description_html": ["<p>plain</p>"],
            "job_description": ['{"plain": true}'],
            "responsibilities": ["[]"],
            "qualifications": ["[]"],
            "skills": ["[]"],
            "compensation": ["salary"],
        }
    ).write_parquet(parquet_dir / "job_versions.parquet")
    gen.pl.DataFrame({"id": ["payload-1"], "payload": ['{"raw": true}']}).write_parquet(
        parquet_dir / "job_payload_snapshots.parquet"
    )

    result = gen._restore_projected_sqlite_columns_from_export_dir(
        db_path,
        parquet_dir,
    )

    with sqlite3.connect(db_path) as conn:
        source_metadata = conn.execute("SELECT raw_metadata FROM sources").fetchone()[0]
        board = conn.execute(
            "SELECT source_board_keys, markets, locations, raw_payload FROM boards"
        ).fetchone()
        version = conn.execute(
            "SELECT locations, description, description_html, job_description, compensation "
            "FROM job_versions"
        ).fetchone()
        payload = conn.execute("SELECT payload FROM job_payload_snapshots").fetchone()[
            0
        ]

    assert result == {"tables": 6, "rows": 6}
    assert source_metadata == '{"restored": true}'
    assert board == (
        '{"source-1": "source-1:board-1"}',
        '["AI", "SaaS"]',
        '["Remote", "New York"]',
        '{"board": true}',
    )
    assert version == (
        '["Remote", "New York"]',
        "plain",
        "<p>plain</p>",
        '{"plain": true}',
        "salary",
    )
    assert payload == '{"raw": true}'


def test_sqlite_schema_normalization_uses_basic_sqlite_affinities(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "schema.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE sample (
                id VARCHAR(32) PRIMARY KEY,
                payload JSON,
                active BOOLEAN,
                observed_at DATETIME,
                score FLOAT
            )
            """
        )

    updated = gen._normalize_sqlite_schema_for_public_upload(db_path)

    with sqlite3.connect(db_path) as conn:
        ddl = conn.execute(
            "SELECT sql FROM sqlite_schema WHERE type = 'table' AND name = 'sample'"
        ).fetchone()[0]
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    assert updated == 1
    assert "VARCHAR" not in ddl
    assert "JSON" not in ddl
    assert "BOOLEAN" not in ddl
    assert "DATETIME" not in ddl
    assert "FLOAT" not in ddl
    assert "TEXT" in ddl
    assert "INTEGER" in ddl
    assert "REAL" in ddl


def test_sqlite_upload_rebuilds_plain_tables_for_public_upload(
    tmp_path: Path,
    capsys,
) -> None:
    db_path = tmp_path / "plain.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """
            CREATE TABLE parent (
                id TEXT PRIMARY KEY,
                label VARCHAR(32) NOT NULL UNIQUE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE child (
                id TEXT PRIMARY KEY,
                parent_id TEXT NOT NULL,
                score FLOAT,
                payload JSON,
                FOREIGN KEY (parent_id) REFERENCES parent(id)
            )
            """
        )
        conn.execute("INSERT INTO parent VALUES ('p1', 'Parent')")
        conn.execute(
            "INSERT INTO child VALUES ('c1', 'p1', 3.5, ?)",
            (json.dumps({"ok": True}),),
        )

    result = gen._rebuild_sqlite_tables_for_public_upload(db_path)
    output = capsys.readouterr().out

    with sqlite3.connect(db_path) as conn:
        ddl = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT name, sql FROM sqlite_schema WHERE type = 'table'"
            )
        }
        child = conn.execute("SELECT * FROM child").fetchone()

    assert result == {"tables": 2, "rows": 2}
    assert '"mode": "in_place"' in output
    assert not db_path.with_name(f".{db_path.name}.plain").exists()
    assert child == ("c1", "p1", 3.5, json.dumps({"ok": True}))
    assert "PRIMARY KEY" not in ddl["parent"]
    assert "UNIQUE" not in ddl["parent"]
    assert "FOREIGN KEY" not in ddl["child"]
    assert "NOT NULL" not in ddl["child"]
    assert "FLOAT" not in ddl["child"]
    assert "JSON" not in ddl["child"]
    assert "REAL" in ddl["child"]
    assert "TEXT" in ddl["child"]


def test_skill_backfill_uses_batched_keyset_pagination() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    body = source[
        source.index("def _backfill_sqlite_skill_tables") : source.index(
            "def _extract_version_skills"
        )
    ]

    assert "LIMIT ? OFFSET ?" not in body
    assert "last_rowid" in body
    assert "chunk_size = 2000" in body
    assert "executemany" in body


def test_table_export_frame_infers_full_sqlite_table_schema() -> None:
    rows = [
        {"id": "first", "remote": None},
        {"id": "second", "remote": None},
        {"id": "third", "remote": "REMOTE"},
    ]

    frame = gen._table_export_frame(gen.TABLES[0], rows)

    assert frame.height == 3
    assert frame["remote"].to_list() == [None, None, "REMOTE"]


def test_kaggle_artifact_cleanup_drops_private_sqlite_tables(tmp_path: Path) -> None:
    db_path = tmp_path / gen.DB_FILE
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE http_cache (key TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO http_cache VALUES ('cached')")
        conn.execute("CREATE TABLE http_cache_metadata (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO http_cache_metadata VALUES ('schema', 'v1')")
        conn.execute("CREATE TABLE alembic_version (version_num TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO alembic_version VALUES ('0001')")
        conn.execute("CREATE TABLE foo (id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO foo VALUES ('extra')")
        conn.execute("CREATE TABLE sources (key TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO sources VALUES ('keep')")

    gen._drop_private_sqlite_tables(db_path)

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert "http_cache" not in tables
    assert "http_cache_metadata" not in tables
    assert "alembic_version" not in tables
    assert "foo" not in tables
    assert "sources" in tables


def test_skill_backfill_populates_legacy_sqlite_skill_tables(tmp_path: Path) -> None:
    db_path = tmp_path / gen.DB_FILE
    store = OpenOppsStore(OpenOppsSettings(db_url=f"sqlite:///{db_path}"))
    store.init_db()
    observed_at = "2026-06-13T12:00:00+00:00"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO jobs (
                id,
                board_key,
                provider_id,
                remote_id,
                status,
                first_seen_at,
                last_seen_at,
                synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "acme:greenhouse:1",
                "acme",
                "greenhouse",
                "1",
                "open",
                observed_at,
                observed_at,
                observed_at,
            ),
        )
        conn.execute(
            """
            INSERT INTO job_versions (
                id,
                job_id,
                version,
                content_hash,
                payload_hash,
                title,
                locations,
                description,
                responsibilities,
                qualifications,
                skills,
                first_seen_at,
                last_seen_at,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "acme-greenhouse-1:version:1",
                "acme:greenhouse:1",
                1,
                "content",
                "payload",
                "Senior Data Engineer",
                "[]",
                "Build Python and SQL data pipelines on AWS.",
                "[]",
                "[]",
                "[]",
                observed_at,
                observed_at,
                observed_at,
            ),
        )

    result = gen._backfill_sqlite_skill_tables(db_path)

    with sqlite3.connect(db_path) as conn:
        skills = conn.execute("SELECT name, level FROM job_version_skills").fetchall()
        keywords = [
            row[0]
            for row in conn.execute(
                "SELECT keyword FROM job_version_skill_keywords ORDER BY keyword"
            ).fetchall()
        ]
        stored_skills = conn.execute(
            "SELECT skills FROM job_versions WHERE id = ?",
            ("acme-greenhouse-1:version:1",),
        ).fetchone()[0]

    assert result["versionsBackfilled"] == 1
    assert skills
    assert ("Programming Languages", "Senior") in skills
    assert "Python" in keywords
    assert "SQL" in keywords
    assert "AWS" in keywords
    assert json.loads(stored_skills)


def test_sqlite_sidecar_cleanup_removes_upload_extra_files(tmp_path: Path) -> None:
    db_path = tmp_path / gen.DB_FILE
    db_path.write_bytes(b"SQLite format 3\x00")
    for suffix in gen.SQLITE_SIDECAR_SUFFIXES:
        db_path.with_name(f"{db_path.name}{suffix}").write_text(
            "stale sidecar", encoding="utf-8"
        )

    gen._remove_sqlite_sidecars(db_path)

    assert db_path.exists()
    for suffix in gen.SQLITE_SIDECAR_SUFFIXES:
        assert not db_path.with_name(f"{db_path.name}{suffix}").exists()


def test_sqlite_upload_finalization_makes_wal_database_portable(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / gen.DB_FILE
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() == "wal"
        conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO sample (value) VALUES ('ok')")

    assert gen._sqlite_header_read_write_versions(db_path) == (2, 2)

    gen._finalize_sqlite_for_upload(db_path)

    assert gen._sqlite_header_read_write_versions(db_path) == (1, 1)
    for suffix in gen.SQLITE_SIDECAR_SUFFIXES:
        assert not db_path.with_name(f"{db_path.name}{suffix}").exists()
    with sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True) as conn:
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT value FROM sample").fetchone()[0] == "ok"


def test_sqlite_upload_finalization_compacts_freed_payload(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / gen.DB_FILE
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO sample (value) VALUES (?)", ("x" * 1_000_000,))
        conn.commit()
    full_size = db_path.stat().st_size
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE sample SET value = NULL")
        conn.commit()

    gen._finalize_sqlite_for_upload(db_path)

    assert db_path.stat().st_size < full_size
    with sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True) as conn:
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT value FROM sample").fetchone()[0] is None


def test_sqlite_upload_finalization_skips_vacuum_without_disk_headroom(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    db_path = tmp_path / gen.DB_FILE
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE keep (id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO keep (value) VALUES ('ok')")
        conn.execute("CREATE TABLE discard (id INTEGER PRIMARY KEY, value TEXT)")
        conn.executemany(
            "INSERT INTO discard (value) VALUES (?)",
            [("x" * 10_000,) for _ in range(100)],
        )
        conn.execute("DROP TABLE discard")
        conn.commit()
        assert int(conn.execute("PRAGMA freelist_count").fetchone()[0]) > 0
    before_size = db_path.stat().st_size

    monkeypatch.setattr(
        gen.shutil,
        "disk_usage",
        lambda path: types.SimpleNamespace(free=0, total=before_size, used=before_size),
    )

    gen._finalize_sqlite_for_upload(db_path)
    output = capsys.readouterr().out

    assert "working disk lacks compaction headroom" in output
    assert db_path.stat().st_size == before_size
    with sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True) as conn:
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT value FROM keep").fetchone()[0] == "ok"


def test_generated_data_files_are_all_described_when_present() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    kaggle_dir = repo_root / "kaggle"
    data_files = [
        path.relative_to(kaggle_dir).as_posix()
        for path in (kaggle_dir / "exports").glob("**/*")
        if path.is_file()
    ]
    sqlite_path = kaggle_dir / gen.DB_FILE
    if sqlite_path.exists():
        data_files.append(gen.DB_FILE)

    dataset_paths = {
        resource["path"] for resource in gen.dataset_metadata()["resources"]
    }
    assert set(data_files) <= dataset_paths


def test_generated_kaggle_upload_root_has_only_public_data_files() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    kaggle_dir = repo_root / "kaggle"
    allowed_public_files = {
        "dataset-cover-image.png",
        "dataset-metadata.json",
        "kernel-metadata.json",
        gen.NB_FILE,
        f"starter/{gen.STARTER_NB_FILE}",
        "starter/kernel-metadata.json",
        *{
            f"examples/{spec.slug}/{spec.code_file}"
            for spec in gen.PUBLIC_EXAMPLE_NOTEBOOKS
        },
        *{
            f"examples/{spec.slug}/kernel-metadata.json"
            for spec in gen.PUBLIC_EXAMPLE_NOTEBOOKS
        },
        gen.DB_FILE,
        *{f"{gen.CSV_DIR}/{table.name}.csv" for table in gen.TABLES},
        *{f"{gen.PARQUET_DIR}/{table.name}.parquet" for table in gen.TABLES},
    }
    if not (kaggle_dir / gen.DB_FILE).exists():
        allowed_public_files.remove(gen.DB_FILE)

    actual_files = {
        path.relative_to(kaggle_dir).as_posix()
        for path in kaggle_dir.rglob("*")
        if path.is_file() and path.name != ".DS_Store"
    }

    assert actual_files <= allowed_public_files
    assert not (actual_files & set(gen.PRIVATE_EVIDENCE_FILES))
    assert not (actual_files & set(gen.PRIVATE_METADATA_FILES))


def test_public_upload_stage_excludes_private_and_manager_files(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    csv_dir = bundle_dir / gen.CSV_DIR
    parquet_dir = bundle_dir / gen.PARQUET_DIR
    csv_dir.mkdir(parents=True)
    parquet_dir.mkdir(parents=True)
    (bundle_dir / "dataset-metadata.json").write_text("{}\n", encoding="utf-8")
    (bundle_dir / gen.DATASET_IMAGE_FILE).write_bytes(b"image")
    schema_db = tmp_path / "schema.sqlite"
    store = OpenOppsStore(OpenOppsSettings(db_url=f"sqlite:///{schema_db}"))
    store.init_db()
    shutil.copy2(schema_db, bundle_dir / gen.DB_FILE)
    for table in gen.TABLES:
        (csv_dir / f"{table.name}.csv").write_text("id\njob-1\n", encoding="utf-8")
        (parquet_dir / f"{table.name}.parquet").write_bytes(b"PAR1")
    (csv_dir / "stray.csv").write_text("should_not_upload\n", encoding="utf-8")
    (parquet_dir / "stray.parquet").write_bytes(b"PAR1")

    for relative_path in gen.PRIVATE_EVIDENCE_FILES + gen.PRIVATE_METADATA_FILES:
        path = bundle_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    (bundle_dir / "kernel-metadata.json").write_text("{}\n", encoding="utf-8")
    (bundle_dir / gen.NB_FILE).write_text("{}\n", encoding="utf-8")
    starter_dir = bundle_dir / "starter"
    starter_dir.mkdir()
    (starter_dir / "kernel-metadata.json").write_text("{}\n", encoding="utf-8")
    (starter_dir / gen.STARTER_NB_FILE).write_text("{}\n", encoding="utf-8")
    examples_dir = bundle_dir / "examples"
    for spec in gen.PUBLIC_EXAMPLE_NOTEBOOKS:
        notebook_dir = examples_dir / spec.slug
        notebook_dir.mkdir(parents=True)
        (notebook_dir / "kernel-metadata.json").write_text("{}\n", encoding="utf-8")
        (notebook_dir / spec.code_file).write_text("{}\n", encoding="utf-8")

    upload_dir = tmp_path / "upload"
    gen._stage_public_upload_dir(bundle_dir, upload_dir)

    actual_files = {
        path.relative_to(upload_dir).as_posix()
        for path in upload_dir.rglob("*")
        if path.is_file()
    }

    assert actual_files == {
        "dataset-metadata.json",
        gen.DATASET_IMAGE_FILE,
        *gen.PUBLIC_UPLOAD_DATA_FILES,
    }
    assert f"{gen.CSV_DIR}/stray.csv" not in actual_files
    assert f"{gen.PARQUET_DIR}/stray.parquet" not in actual_files
    assert "kernel-metadata.json" not in actual_files
    assert gen.NB_FILE not in actual_files
    assert "starter/kernel-metadata.json" not in actual_files
    assert f"starter/{gen.STARTER_NB_FILE}" not in actual_files
    for spec in gen.PUBLIC_EXAMPLE_NOTEBOOKS:
        assert f"examples/{spec.slug}/kernel-metadata.json" not in actual_files
        assert f"examples/{spec.slug}/{spec.code_file}" not in actual_files
    assert not (actual_files & set(gen.PRIVATE_EVIDENCE_FILES))
    assert not (actual_files & set(gen.PRIVATE_METADATA_FILES))


def _write_public_upload_stage_bundle(root_dir: Path) -> Path:
    root_dir.mkdir(parents=True, exist_ok=True)
    bundle_dir = root_dir / "bundle"
    csv_dir = bundle_dir / gen.CSV_DIR
    parquet_dir = bundle_dir / gen.PARQUET_DIR
    csv_dir.mkdir(parents=True)
    parquet_dir.mkdir(parents=True)
    (bundle_dir / "dataset-metadata.json").write_text("{}\n", encoding="utf-8")
    (bundle_dir / gen.DATASET_IMAGE_FILE).write_bytes(b"image")
    schema_db = root_dir / "schema.sqlite"
    store = OpenOppsStore(OpenOppsSettings(db_url=f"sqlite:///{schema_db}"))
    store.init_db()
    shutil.copy2(schema_db, bundle_dir / gen.DB_FILE)
    for table in gen.TABLES:
        (csv_dir / f"{table.name}.csv").write_text("id\njob-1\n", encoding="utf-8")
        (parquet_dir / f"{table.name}.parquet").write_bytes(b"PAR1")
    return bundle_dir


def test_public_upload_stage_rejects_existing_unowned_dir(tmp_path: Path) -> None:
    bundle_dir = _write_public_upload_stage_bundle(tmp_path / "source")
    upload_dir = tmp_path / "upload"
    upload_dir.mkdir()
    existing_file = upload_dir / "keep.txt"
    existing_file.write_text("do not delete\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Refusing to overwrite non-empty"):
        gen._stage_public_upload_dir(bundle_dir, upload_dir)

    assert existing_file.read_text(encoding="utf-8") == "do not delete\n"


def test_public_upload_stage_accepts_empty_existing_dir(tmp_path: Path) -> None:
    bundle_dir = _write_public_upload_stage_bundle(tmp_path / "source")
    upload_dir = tmp_path / "upload"
    upload_dir.mkdir()

    gen._stage_public_upload_dir(bundle_dir, upload_dir)

    assert (upload_dir / "dataset-metadata.json").is_file()
    assert (upload_dir / gen.DB_FILE).is_file()


def test_public_upload_stage_replaces_prior_tool_owned_dir(tmp_path: Path) -> None:
    bundle_dir = _write_public_upload_stage_bundle(tmp_path / "source")
    upload_dir = tmp_path / "upload"

    gen._stage_public_upload_dir(bundle_dir, upload_dir)
    (upload_dir / "dataset-metadata.json").write_text("old\n", encoding="utf-8")
    (bundle_dir / "dataset-metadata.json").write_text(
        '{"updated": true}\n',
        encoding="utf-8",
    )

    gen._stage_public_upload_dir(bundle_dir, upload_dir)

    assert (
        (upload_dir / "dataset-metadata.json").read_text(encoding="utf-8")
        == '{"updated": true}\n'
    )


def test_public_upload_stage_rejects_dataset_descendant(tmp_path: Path) -> None:
    bundle_dir = _write_public_upload_stage_bundle(tmp_path / "source")
    upload_dir = bundle_dir / "upload"

    with pytest.raises(ValueError, match="outside the dataset dir"):
        gen._stage_public_upload_dir(bundle_dir, upload_dir)


def test_private_upload_prune_removes_runtime_artifacts(tmp_path: Path) -> None:
    (tmp_path / "dataset-metadata.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / gen.DATASET_IMAGE_FILE).write_bytes(b"image")
    (tmp_path / gen.DB_FILE).write_bytes(b"SQLite format 3\x00")
    for relative_path in (
        gen.PRIVATE_EVIDENCE_FILES
        + gen.PRIVATE_METADATA_FILES
        + gen.PRIVATE_UPLOAD_RUNTIME_FILES
    ):
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    runtime_pkg = tmp_path / gen.RUNTIME_GENERATOR_PACKAGE_DIR
    runtime_pkg.mkdir(parents=True, exist_ok=True)
    (runtime_pkg / "runtime_manifest.py").write_text("# runtime\n", encoding="utf-8")
    for relative_dir in gen.PRIVATE_UPLOAD_RUNTIME_DIRS:
        path = tmp_path / relative_dir
        path.mkdir(parents=True, exist_ok=True)
        (path / "private.txt").write_text("private\n", encoding="utf-8")
    for suffix in gen.SQLITE_SIDECAR_SUFFIXES:
        (tmp_path / f"{gen.DB_FILE}{suffix}").write_text("sidecar\n", encoding="utf-8")

    gen._prune_private_upload_files(tmp_path)

    assert (tmp_path / "dataset-metadata.json").exists()
    assert (tmp_path / gen.DATASET_IMAGE_FILE).exists()
    assert (tmp_path / gen.DB_FILE).exists()
    for relative_path in (
        gen.PRIVATE_EVIDENCE_FILES
        + gen.PRIVATE_METADATA_FILES
        + gen.PRIVATE_UPLOAD_RUNTIME_FILES
    ):
        assert not (tmp_path / relative_path).exists()
    for relative_dir in gen.PRIVATE_UPLOAD_RUNTIME_DIRS:
        assert not (tmp_path / relative_dir).exists()
    assert not runtime_pkg.exists()
    for suffix in gen.SQLITE_SIDECAR_SUFFIXES:
        assert not (tmp_path / f"{gen.DB_FILE}{suffix}").exists()


def test_public_upload_stage_prefers_hardlinks() -> None:
    source = inspect.getsource(gen._stage_public_upload_dir)

    assert "hardlink_to" in source
    assert "shutil.copy2" in source


def test_runtime_generator_stage_is_minimal(tmp_path: Path) -> None:
    upload_dir = tmp_path / "runtime-upload"

    gen._stage_runtime_generator_dir(upload_dir)

    actual_files = {
        path.relative_to(upload_dir).as_posix()
        for path in upload_dir.rglob("*")
        if path.is_file()
    }
    metadata = json.loads((upload_dir / "dataset-metadata.json").read_text())
    script_sha256 = gen.runtime_generator_script_sha256()

    assert "dataset-metadata.json" in actual_files
    assert gen.RUNTIME_MANIFEST_FILE in actual_files
    assert any(path.startswith(f"{gen.RUNTIME_GENERATOR_PACKAGE_DIR}/") for path in actual_files)
    assert metadata["id"] == gen.RUNTIME_GENERATOR_DATASET_ID
    assert metadata["isPrivate"] is True
    assert metadata["licenses"] == [{"name": gen.DATASET_LICENSE}]
    assert script_sha256 in metadata["description"]
    assert metadata["resources"] == [
        {
            "path": gen.RUNTIME_MANIFEST_FILE,
            "description": (
                "OpenOppsDB Kaggle metadata, bundle, quality gate, staging, "
                "and live metadata repair generator used by the manager "
                "notebook runtime. Expected SHA-256: "
                f"{script_sha256}."
            ),
        }
    ]
    assert len(script_sha256) == 64
    assert set(script_sha256) <= set("0123456789abcdef")
    assert not (actual_files & set(gen.PUBLIC_UPLOAD_DATA_FILES))
    assert not (actual_files & set(gen.PRIVATE_EVIDENCE_FILES))
    assert not (actual_files & set(gen.PRIVATE_METADATA_FILES))
    assert gen.NB_FILE not in actual_files
    assert gen.STARTER_NB_FILE not in actual_files
    assert gen.DATAPACKAGE_FILE not in actual_files


def test_generator_cli_stages_runtime_generator_and_exits(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_dir = tmp_path / "output"
    upload_dir = tmp_path / "runtime-upload"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "openopps_kaggle",
            "--output-dir",
            str(output_dir),
            "--stage-runtime-generator-dir",
            str(upload_dir),
        ],
    )

    from openopps_kaggle.cli import main as cli_main  # ty: ignore[unresolved-import]
    cli_main()

    assert not output_dir.exists()
    names = {path.name for path in upload_dir.iterdir()}
    assert names >= {"dataset-metadata.json", gen.RUNTIME_MANIFEST_FILE, gen.RUNTIME_GENERATOR_PACKAGE_DIR}


def test_manager_notebook_generator_probe_env_strips_kaggle_credentials(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENOPPS_KAGGLE_OUTPUT_DIR", str(tmp_path / "openoppsdb"))
    monkeypatch.setenv("OPENOPPS_KEEP_FOR_PROBE", "1")
    for key in (
        "KAGGLE_USERNAME",
        "KAGGLE_KEY",
        "KAGGLE_API_TOKEN",
        "KAGGLE_API_V1_TOKEN_PATH",
        "KAGGLE_CONFIG_DIR",
        "KAGGLE_URL_BASE",
        "KAGGLE_USER_SECRETS_TOKEN",
    ):
        monkeypatch.setenv(key, f"value-for-{key.lower()}")

    namespace = _notebook_setup_namespace()
    probe_env = namespace["runtime_probe_env"]()

    assert probe_env["OPENOPPS_KEEP_FOR_PROBE"] == "1"
    assert not any(key.startswith("KAGGLE_") for key in probe_env)
    for key in namespace["KAGGLE_CREDENTIAL_ENV_NAMES"]:
        assert key not in probe_env


def test_manager_notebook_download_verifies_before_help_and_scrubs_env(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_dir = tmp_path / "openoppsdb"
    monkeypatch.setenv("OPENOPPS_KAGGLE_OUTPUT_DIR", str(output_dir))
    runtime_input = tmp_path / "input"
    digest = _stage_runtime_input(runtime_input / "openoppsdb-manager-runtime")
    namespace = _notebook_setup_namespace(runtime_input=runtime_input)
    namespace["RUNTIME_PACKAGE_SHA256"] = digest
    namespace["GENERATOR_SCRIPT_SHA256"] = digest
    seen: dict[str, object] = {}

    class Completed:
        returncode = 0
        stdout = "--skip-notebooks --stage-public-upload-dir --quality-report\n"
        stderr = ""

        def check_returncode(self) -> None:
            raise AssertionError("download help probe unexpectedly failed")

    def fake_run(command: list[str], **kwargs) -> Completed:
        seen["command"] = command
        seen["env"] = kwargs["env"]
        return Completed()

    monkeypatch.setattr(namespace["subprocess"], "run", fake_run)
    monkeypatch.setenv("KAGGLE_USERNAME", "user")
    monkeypatch.setenv("KAGGLE_KEY", "key")
    monkeypatch.setenv("KAGGLE_API_TOKEN", "token")

    namespace["download_runtime_package"]()

    assert namespace["RUNTIME_PACKAGE_VERIFIED_SHA256"] == digest
    assert seen["command"] == [
        sys.executable,
        "-m",
        "openopps_kaggle",
        "--help",
    ]
    probe_env = seen["env"]
    assert isinstance(probe_env, dict)
    assert not any(key.startswith("KAGGLE_") for key in probe_env)


def test_manager_notebook_download_rejects_checksum_before_compile(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_dir = tmp_path / "openoppsdb"
    monkeypatch.setenv("OPENOPPS_KAGGLE_OUTPUT_DIR", str(output_dir))
    runtime_input = tmp_path / "input"
    digest = _stage_runtime_input(runtime_input / "openoppsdb-manager-runtime")
    namespace = _notebook_setup_namespace(runtime_input=runtime_input)
    namespace["RUNTIME_PACKAGE_SHA256"] = hashlib.sha256(b"expected").hexdigest()
    namespace["GENERATOR_SCRIPT_SHA256"] = namespace["RUNTIME_PACKAGE_SHA256"]

    def fail_run(*args, **kwargs) -> None:
        del args, kwargs
        raise AssertionError("help probe must not run after checksum mismatch")

    monkeypatch.setattr(namespace["subprocess"], "run", fail_run)

    with pytest.raises(RuntimeError, match="checksum mismatch"):
        namespace["download_runtime_package"]()
    assert digest != namespace["RUNTIME_PACKAGE_SHA256"]


def test_manager_notebook_run_openopps_kaggle_verifies_existing_script_before_execution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_dir = tmp_path / "openoppsdb"
    monkeypatch.setenv("OPENOPPS_KAGGLE_OUTPUT_DIR", str(output_dir))
    runtime_input = tmp_path / "input"
    digest = _stage_runtime_input(runtime_input / "openoppsdb-manager-runtime")
    namespace = _notebook_setup_namespace(runtime_input=runtime_input)
    namespace["RUNTIME_PACKAGE_SHA256"] = digest
    namespace["GENERATOR_SCRIPT_SHA256"] = digest
    namespace["download_runtime_package"]()
    (namespace["RUNTIME_PACKAGE_DIR"] / "cli.py").write_text(
        "print('tampered')\n",
        encoding="utf-8",
    )

    def fail_run(*args, **kwargs) -> None:
        del args, kwargs
        raise AssertionError("generator command must not run before verification")

    namespace["run"] = fail_run

    with pytest.raises(RuntimeError, match="checksum mismatch"):
        namespace["run_openopps_kaggle"](["--skip-notebooks"])


def test_live_kaggle_dataset_recipes_use_public_upload_stage() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    justfile = (repo_root / "Justfile").read_text(encoding="utf-8")
    kaggle_dir = repo_root / "kaggle"

    assert "--stage-public-upload-dir" in justfile
    assert "publication publish --kind runtime" in justfile
    assert 'kaggle := "uv run --frozen --group ops kaggle"' in justfile
    pyproject = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    assert '"kaggle==2.2.4"' in pyproject
    assert "kaggle-runtime-generator-create message=" in justfile
    assert "kaggle-runtime-generator-version message=" in justfile
    assert "publication publish --kind runtime --action create" in justfile
    assert "publication publish --kind runtime --action version" in justfile
    assert '{{ kaggle }} datasets create -p "$upload_dir"' not in justfile
    assert '{{ kaggle }} datasets version -p "$upload_dir"' not in justfile
    # Fail-closed: default create/version require rebuild-from-db (not silent stage-only).
    assert "kaggle-dataset-create db=" in justfile
    assert "kaggle-dataset-version message=" in justfile
    assert "allow_stale" in justfile
    assert "--data-db" in justfile
    assert "--allow-stale" in justfile
    assert "--expected-current-version" in justfile
    assert "--allow-no-rollback" in justfile
    assert "execute=\"0\"" in justfile
    assert "kaggle-bundle-smoke:" in justfile
    assert "{{ kaggle }} datasets status wyattowalsh/openoppsdb" in justfile
    assert "--live-file-metadata-browser-cookies" in justfile
    assert (
        'kaggle-ops-gen := "PYTHONPATH=scripts uv run --frozen --group ops '
        'python -m openopps_kaggle"'
        in justfile
    )
    assert '"browser-cookie3==0.20.1"' in pyproject
    assert "kagglehub-live-readback" in justfile
    assert "args=(verify-readback --dataset" in justfile
    assert '{{ kaggle-ops-gen }} "${args[@]}"' in justfile
    assert '"kagglehub[polars-datasets]==1.0.2"' in pyproject
    assert 'kaggle-notebook-push timeout="7200" execute="0":' in justfile
    assert 'kaggle-example-notebooks-push timeout="3600" execute="0":' in justfile
    assert "publication kernel-push --bundle examples" in justfile
    assert "kaggle-example-notebooks-status:" in justfile
    assert "kaggle-example-notebooks-pull-check:" in justfile
    assert 'kaggle-example-notebooks-files page_size="200":' in justfile
    assert "openopps_kaggle verify-notebooks" in justfile
    for kernel_dir in [
        kaggle_dir,
        kaggle_dir / "starter",
        kaggle_dir / "examples" / "advanced-usage",
        kaggle_dir / "examples" / "hiring-market-map",
        kaggle_dir / "examples" / "skills-radar",
    ]:
        assert (kernel_dir / "kernel-metadata.json").is_file()
    assert gen.ADVANCED_NB_ID in justfile
    assert gen.HIRING_MARKET_NB_ID in justfile
    assert gen.SKILLS_RADAR_NB_ID in justfile
    assert "${dataset#dataset=}" in justfile
    assert "${dataset#version=}" in justfile
    assert "${version#version=}" in justfile
    assert (
        "kaggle-live-verify: kaggle-live-status kaggle-live-files "
        "kagglehub-live-readback"
    ) in justfile
    assert (
        "kaggle-example-notebooks-status kaggle-example-notebooks-pull-check"
        in justfile
    )
    assert "kaggle datasets create -p kaggle" not in justfile
    assert "kaggle datasets version -p kaggle" not in justfile


def test_generator_cli_orchestrates_manager_runtime_bundle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_dir = tmp_path / "output"
    upload_dir = tmp_path / "upload"
    data_db = tmp_path / gen.DB_FILE
    sync_metrics = tmp_path / gen.SYNC_METRICS_FILE
    status_json = tmp_path / gen.STATUS_FILE
    coverage_json = tmp_path / gen.COVERAGE_FILE
    quality_report = tmp_path / gen.SNAPSHOT_QUALITY_FILE
    data_db.write_bytes(b"SQLite format 3\x00")
    sync_metrics.write_text("{}\n", encoding="utf-8")
    status_json.write_text("{}\n", encoding="utf-8")
    coverage_json.write_text("{}\n", encoding="utf-8")
    calls: list[tuple[str, tuple, dict]] = []

    def record(name: str):
        def inner(*args, **kwargs):
            calls.append((name, args, kwargs))
            if name == "quality":
                kwargs["report_path"].write_text(
                    '{"status":"pass"}\n', encoding="utf-8"
                )

        return inner

    monkeypatch.setattr(core, "_write_data_artifacts", record("data"))
    monkeypatch.setattr(core, "_write_dataset_image", record("image"))
    monkeypatch.setattr(core, "_write_snapshot_quality_report", record("quality"))
    monkeypatch.setattr(core, "_prune_private_evidence_files", record("evidence_prune"))
    monkeypatch.setattr(core, "_prune_private_upload_files", record("prune"))
    monkeypatch.setattr(core, "_stage_public_upload_dir", record("stage"))
    monkeypatch.setattr(core, "_wait_live_dataset_ready", record("wait"))
    monkeypatch.setattr(core, "_update_live_file_metadata", record("live"))
    monkeypatch.setattr(core, "_write_manager_notebook", record("manager"))
    monkeypatch.setattr(core, "_write_starter_notebook", record("starter"))

    import openopps_kaggle.cli as cli  # ty: ignore[unresolved-import]

    monkeypatch.setattr(cli, "_write_data_artifacts", record("data"))
    monkeypatch.setattr(cli, "_write_dataset_image", record("image"))
    monkeypatch.setattr(cli, "_write_snapshot_quality_report", record("quality"))
    monkeypatch.setattr(cli, "_prune_private_evidence_files", record("evidence_prune"))
    monkeypatch.setattr(cli, "_prune_private_upload_files", record("prune"))
    monkeypatch.setattr(cli, "_stage_public_upload_dir", record("stage"))
    monkeypatch.setattr(cli, "_wait_live_dataset_ready", record("wait"))
    monkeypatch.setattr(cli, "_update_live_file_metadata", record("live"))
    monkeypatch.setattr(cli, "_write_manager_notebook", record("manager"))
    monkeypatch.setattr(cli, "_write_starter_notebook", record("starter"))
    monkeypatch.setattr(cli, "require_disk_headroom", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "openopps_kaggle",
            "--output-dir",
            str(output_dir),
            "--data-db",
            str(data_db),
            "--mutate-data-db-for-upload",
            "--sync-metrics",
            str(sync_metrics),
            "--status-json",
            str(status_json),
            "--coverage-json",
            str(coverage_json),
            "--quality-report",
            str(quality_report),
            "--prune-private-upload-files",
            "--stage-public-upload-dir",
            str(upload_dir),
            "--skip-notebooks",
            "--wait-live-dataset-ready",
            "--wait-live-dataset-min-version",
            "37",
            "--wait-live-dataset-timeout-seconds",
            "12",
            "--wait-live-dataset-poll-seconds",
            "3",
            "--update-live-file-metadata",
            "--live-file-metadata-kaggle-auth",
            "--live-file-metadata-sqlite-timeout-seconds",
            "4",
            "--live-file-metadata-sqlite-poll-seconds",
            "2",
        ],
    )

    from openopps_kaggle.cli import main as cli_main  # ty: ignore[unresolved-import]
    cli_main()

    names = [name for name, _, _ in calls]
    assert names == ["data", "image", "quality", "prune", "stage", "wait", "live"]
    assert calls[0][1] == (output_dir, data_db)
    assert calls[0][2] == {"mutate_data_db_for_upload": True}
    assert calls[2][2]["report_path"] == quality_report
    assert calls[4][1] == (output_dir, upload_dir)
    assert calls[5][1] == (gen.DATASET_ID,)
    assert calls[5][2] == {
        "min_version": 37,
        "timeout_seconds": 12.0,
        "poll_seconds": 3.0,
    }
    assert calls[6][1] == (output_dir / "dataset-metadata.json",)
    assert calls[6][2] == {
        "use_browser_cookies": False,
        "use_kaggle_auth": True,
        "sqlite_index_timeout_seconds": 4.0,
        "sqlite_index_poll_seconds": 2.0,
    }


def test_live_file_metadata_can_use_kaggle_auth_repair(
    tmp_path: Path,
    monkeypatch,
) -> None:
    metadata_path = tmp_path / "dataset-metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "id": gen.DATASET_ID,
                "title": "openoppsdb",
                "subtitle": "",
                "description": "desc",
                "isPrivate": False,
                "licenses": [{"name": gen.DATASET_LICENSE}],
                "keywords": [],
                "expectedUpdateFrequency": "daily",
                "userSpecifiedSources": "",
                "resources": [{"path": gen.DB_FILE, "description": "db"}],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    class FakeKaggleClient:
        def __enter__(self):
            return types.SimpleNamespace(
                datasets=types.SimpleNamespace(
                    dataset_api_client=types.SimpleNamespace(
                        update_dataset_metadata=lambda request: types.SimpleNamespace(
                            errors=[]
                        )
                    )
                )
            )

        def __exit__(self, exc_type, exc, traceback):
            return False

    class FakeKaggleApi:
        def authenticate(self) -> None:
            pass

        def _new_license(self, name: str) -> str:
            return name

        def build_kaggle_client(self) -> FakeKaggleClient:
            return FakeKaggleClient()

    kaggle_api_module: Any = types.ModuleType("kaggle.api.kaggle_api_extended")
    kaggle_api_module.KaggleApi = FakeKaggleApi
    dataset_api_service_module: Any = types.ModuleType(
        "kagglesdk.datasets.types.dataset_api_service"
    )
    dataset_api_service_module.ApiUpdateDatasetMetadataRequest = type(
        "ApiUpdateDatasetMetadataRequest",
        (),
        {},
    )
    dataset_types_module: Any = types.ModuleType("kagglesdk.datasets.types.dataset_types")
    dataset_types_module.DatasetSettings = type("DatasetSettings", (), {})
    dataset_types_module.DatasetSettingsFile = type("DatasetSettingsFile", (), {})
    dataset_types_module.DatasetSettingsFileColumn = type(
        "DatasetSettingsFileColumn",
        (),
        {},
    )
    monkeypatch.setitem(sys.modules, "kaggle", types.ModuleType("kaggle"))
    monkeypatch.setitem(sys.modules, "kaggle.api", types.ModuleType("kaggle.api"))
    monkeypatch.setitem(sys.modules, "kagglesdk", types.ModuleType("kagglesdk"))
    monkeypatch.setitem(
        sys.modules,
        "kagglesdk.datasets",
        types.ModuleType("kagglesdk.datasets"),
    )
    monkeypatch.setitem(
        sys.modules,
        "kagglesdk.datasets.types",
        types.ModuleType("kagglesdk.datasets.types"),
    )
    monkeypatch.setitem(
        sys.modules, "kaggle.api.kaggle_api_extended", kaggle_api_module
    )
    monkeypatch.setitem(
        sys.modules,
        "kagglesdk.datasets.types.dataset_api_service",
        dataset_api_service_module,
    )
    monkeypatch.setitem(
        sys.modules,
        "kagglesdk.datasets.types.dataset_types",
        dataset_types_module,
    )
    calls: list[tuple[dict, float, float]] = []

    def fake_kaggle_auth(
        metadata, *, sqlite_index_timeout_seconds, sqlite_index_poll_seconds
    ):
        calls.append(
            (metadata, sqlite_index_timeout_seconds, sqlite_index_poll_seconds)
        )

    monkeypatch.setattr(
        core,
        "_update_live_databundle_metadata_with_kaggle_auth",
        fake_kaggle_auth,
    )

    gen._update_live_file_metadata(
        metadata_path,
        use_kaggle_auth=True,
        sqlite_index_timeout_seconds=4,
        sqlite_index_poll_seconds=2,
    )

    assert calls == [
        (
            json.loads(metadata_path.read_text(encoding="utf-8")),
            4,
            2,
        )
    ]


def test_live_file_metadata_skips_unauthenticated_kaggle_auth_after_official_update(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    metadata_path = tmp_path / "dataset-metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "id": gen.DATASET_ID,
                "title": "openoppsdb",
                "subtitle": "",
                "description": "desc",
                "isPrivate": False,
                "licenses": [{"name": gen.DATASET_LICENSE}],
                "keywords": [],
                "expectedUpdateFrequency": "daily",
                "userSpecifiedSources": "",
                "resources": [{"path": gen.DB_FILE, "description": "db"}],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    class FakeKaggleClient:
        def __enter__(self):
            return types.SimpleNamespace(
                datasets=types.SimpleNamespace(
                    dataset_api_client=types.SimpleNamespace(
                        update_dataset_metadata=lambda request: types.SimpleNamespace(
                            errors=[]
                        )
                    )
                )
            )

        def __exit__(self, exc_type, exc, traceback):
            return False

    class FakeKaggleApi:
        def authenticate(self) -> None:
            pass

        def _new_license(self, name: str) -> str:
            return name

        def build_kaggle_client(self) -> FakeKaggleClient:
            return FakeKaggleClient()

    kaggle_api_module: Any = types.ModuleType("kaggle.api.kaggle_api_extended")
    kaggle_api_module.KaggleApi = FakeKaggleApi
    dataset_api_service_module: Any = types.ModuleType(
        "kagglesdk.datasets.types.dataset_api_service"
    )
    dataset_api_service_module.ApiUpdateDatasetMetadataRequest = type(
        "ApiUpdateDatasetMetadataRequest",
        (),
        {},
    )
    dataset_types_module: Any = types.ModuleType("kagglesdk.datasets.types.dataset_types")
    dataset_types_module.DatasetSettings = type("DatasetSettings", (), {})
    dataset_types_module.DatasetSettingsFile = type("DatasetSettingsFile", (), {})
    dataset_types_module.DatasetSettingsFileColumn = type(
        "DatasetSettingsFileColumn",
        (),
        {},
    )
    monkeypatch.setitem(sys.modules, "kaggle", types.ModuleType("kaggle"))
    monkeypatch.setitem(sys.modules, "kaggle.api", types.ModuleType("kaggle.api"))
    monkeypatch.setitem(sys.modules, "kagglesdk", types.ModuleType("kagglesdk"))
    monkeypatch.setitem(
        sys.modules,
        "kagglesdk.datasets",
        types.ModuleType("kagglesdk.datasets"),
    )
    monkeypatch.setitem(
        sys.modules,
        "kagglesdk.datasets.types",
        types.ModuleType("kagglesdk.datasets.types"),
    )
    monkeypatch.setitem(
        sys.modules, "kaggle.api.kaggle_api_extended", kaggle_api_module
    )
    monkeypatch.setitem(
        sys.modules,
        "kagglesdk.datasets.types.dataset_api_service",
        dataset_api_service_module,
    )
    monkeypatch.setitem(
        sys.modules,
        "kagglesdk.datasets.types.dataset_types",
        dataset_types_module,
    )

    def fake_kaggle_auth(
        metadata, *, sqlite_index_timeout_seconds, sqlite_index_poll_seconds
    ):
        raise RuntimeError(
            "Kaggle internal metadata API failed for "
            "datasets.databundles.DatabundleService/UpdateDatabundleMetadataExternal: "
            '401 {"error":{"status":"UNAUTHENTICATED"}}'
        )

    monkeypatch.setattr(
        core,
        "_update_live_databundle_metadata_with_kaggle_auth",
        fake_kaggle_auth,
    )

    gen._update_live_file_metadata(
        metadata_path,
        use_kaggle_auth=True,
        sqlite_index_timeout_seconds=4,
        sqlite_index_poll_seconds=2,
    )

    output = capsys.readouterr().out
    assert "Updated Kaggle file metadata for 1 public files." in output
    assert "Kaggle-auth databundle metadata repair skipped" in output
    assert '"status": "unauthenticated"' in output


def test_kaggle_basic_auth_header_reads_environment(monkeypatch) -> None:
    monkeypatch.setenv("KAGGLE_USERNAME", "user")
    monkeypatch.setenv("KAGGLE_KEY", "key")
    monkeypatch.delenv("KAGGLE_API_TOKEN", raising=False)

    assert gen._kaggle_basic_auth_header() == "Basic dXNlcjprZXk="


def test_sqlite_table_metadata_repair_updates_indexed_kaggle_tables() -> None:
    calls: list[tuple[str, dict]] = []

    def post(route: str, body: dict) -> dict:
        calls.append((route, body))
        if route.endswith("GetDatabundleExternalChildren"):
            return {
                "tables": [
                    {
                        "name": table.name,
                        "path": f"sqliteTables/{table.name}",
                    }
                    for table in gen.TABLES
                ]
            }
        if route.endswith("GetDatabundleExternalColumns"):
            table_name = str(body["firestorePath"]).split("/")[-1]
            table = next(item for item in gen.TABLES if item.name == table_name)
            return {
                "columns": [
                    {"name": field["name"], "firestorePath": f"columns/{field['name']}"}
                    for field in gen._model_schema_metadata(table.model)["fields"]
                ]
            }
        if route.endswith("UpdateDatabundleMetadataExternal"):
            return {"usabilityRating": {"score": 10}}
        raise AssertionError(route)

    table_count, column_count, rating = gen._update_sqlite_table_metadata_external(
        post,
        {"datasetId": 1, "databundleVersionId": 2},
        {
            "path": "files/openoppsdb.sqlite",
            "sqliteInfo": {"tables": {"totalChildren": len(gen.TABLES)}},
        },
    )

    update_calls = [
        body
        for route, body in calls
        if route.endswith("UpdateDatabundleMetadataExternal")
    ]
    jobs_update = next(
        body for body in update_calls if body["firestorePath"] == "sqliteTables/jobs"
    )
    board_key = next(
        column for column in jobs_update["columns"] if column["name"] == "board_key"
    )

    assert table_count == len(gen.TABLES)
    assert column_count == sum(len(table.model.model_fields) for table in gen.TABLES)
    assert rating == {"score": 10}
    assert len(update_calls) == len(gen.TABLES)
    assert jobs_update["description"] == "Stable job identities and lifecycle state."
    assert board_key["description"] == "Board key this job belongs to."
    assert board_key["type"] == "STRING"
    assert board_key["extendedType"] == "ID"


def test_sqlite_table_metadata_repair_fails_when_kaggle_has_not_indexed_sqlite() -> (
    None
):
    def post(route: str, body: dict) -> dict:
        raise AssertionError(route)

    try:
        gen._update_sqlite_table_metadata_external(
            post,
            {"datasetId": 1, "databundleVersionId": 2},
            {"path": "files/openoppsdb.sqlite"},
        )
    except RuntimeError as exc:
        assert "Kaggle did not expose sqliteInfo.tables" in str(exc)
    else:
        raise AssertionError("Expected missing sqliteInfo to fail")


def test_sqlite_table_metadata_wait_returns_blocker_when_unindexed() -> None:
    def post(route: str, body: dict) -> dict:
        raise AssertionError(route)

    def refresh_file_info() -> dict:
        raise AssertionError("refresh should not run after an immediate timeout")

    table_count, column_count, rating, blocker = (
        gen._update_sqlite_table_metadata_when_indexed(
            post,
            {"datasetId": 1, "databundleVersionId": 2},
            {"path": "files/openoppsdb.sqlite"},
            refresh_file_info=refresh_file_info,
            timeout_seconds=0,
            poll_seconds=1,
        )
    )

    assert table_count == 0
    assert column_count == 0
    assert rating == {}
    assert blocker is not None
    assert "Kaggle did not expose sqliteInfo.tables" in blocker


def test_wait_live_dataset_ready_requires_next_ready_version(monkeypatch) -> None:
    statuses = iter(
        [
            {"status": "ready", "current_version_number": 25},
            {"status": "creating", "current_version_number": 26},
            {"status": "ready", "current_version_number": 26},
        ]
    )
    sleeps: list[float] = []

    monkeypatch.setattr(
        core,
        "_kaggle_dataset_status",
        lambda dataset_id: next(statuses),
    )
    monkeypatch.setattr(core.time, "sleep", lambda seconds: sleeps.append(seconds))

    status = gen._wait_live_dataset_ready(
        gen.DATASET_ID,
        min_version=26,
        timeout_seconds=60,
        poll_seconds=5,
    )

    assert status == {"status": "ready", "current_version_number": 26}
    assert sleeps == [5, 5]


def test_sqlite_metadata_tables_store_table_and_column_descriptions(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / gen.DB_FILE
    gen._write_sqlite_metadata(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        table_rows = conn.execute("SELECT * FROM openopps_tables").fetchall()
        column_rows = conn.execute("SELECT * FROM openopps_columns").fetchall()
        jobs = conn.execute(
            "SELECT * FROM openopps_tables WHERE table_name = 'jobs'"
        ).fetchone()
        job_column = conn.execute(
            """
            SELECT * FROM openopps_columns
            WHERE table_name = 'jobs' AND column_name = 'board_key'
            """
        ).fetchone()

    assert len(table_rows) == len(gen.TABLES)
    assert len(column_rows) == sum(
        len(table.model.model_fields) for table in gen.TABLES
    )
    assert jobs["table_title"] == "Jobs"
    assert jobs["table_description"] == "Stable job identities and lifecycle state."
    assert job_column["column_title"] == "Board Key"
    assert job_column["column_description"] == "Board key this job belongs to."
    assert job_column["operational_nullable"] == 0
    assert job_column["public_sqlite_value_status"] == "full"
    assert json.loads(job_column["full_export_paths_json"]) == [
        "exports/csv/jobs.csv",
        "exports/parquet/jobs.parquet",
    ]
    assert json.loads(job_column["relationship_json"]) == {
        "joinHint": None,
        "primaryKey": False,
        "referencedBy": [],
        "references": [
            {
                "column": "key",
                "nullable": False,
                "onDelete": "CASCADE",
                "table": "boards",
            }
        ],
    }


def test_public_sqlite_integrity_checks_table_columns_and_relationships(
    tmp_path: Path,
) -> None:
    db_path = _write_quality_bundle(tmp_path, job_versions=1)

    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE jobs SET current_version_id = 'missing-version'")
        conn.commit()

    report = gen._sqlite_snapshot_report(db_path)

    assert report["missingColumnErrors"] == []
    assert report["extraColumnErrors"] == []
    assert "jobs.current_version_id->job_versions.id:1" in report["orphanErrors"]


def test_snapshot_quality_report_blocks_null_required_relationships(
    tmp_path: Path,
) -> None:
    db_path = _write_quality_bundle(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE jobs SET board_key = NULL WHERE id = 'job-1'")
        conn.commit()

    sqlite_report = gen._sqlite_snapshot_report(db_path)
    report = gen.snapshot_quality_report(
        output_dir=tmp_path,
        db_path=db_path,
        sync_metrics=_sync_metrics(),
        status=_status(),
        coverage=_coverage(),
    )

    assert "jobs.board_key->boards.key:1" in sqlite_report["orphanErrors"]
    assert "sqlite_orphan_error:jobs.board_key->boards.key:1" in report["hardBlockers"]


def test_snapshot_quality_report_blocks_null_public_sqlite_primary_keys(
    tmp_path: Path,
) -> None:
    db_path = _write_quality_bundle(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE jobs SET id = NULL WHERE id = 'job-1'")
        conn.commit()

    sqlite_report = gen._sqlite_snapshot_report(db_path)
    report = gen.snapshot_quality_report(
        output_dir=tmp_path,
        db_path=db_path,
        sync_metrics=_sync_metrics(),
        status=_status(),
        coverage=_coverage(),
    )

    assert "jobs.pk:1" in sqlite_report["nullKeyErrors"]
    assert "sqlite_null_key_error:jobs.pk:1" in report["hardBlockers"]
    assert "jobs.pk:1" not in sqlite_report["duplicateErrors"]


def test_public_sqlite_integrity_blocks_missing_model_columns(tmp_path: Path) -> None:
    db_path = tmp_path / gen.DB_FILE
    with sqlite3.connect(db_path) as conn:
        for table in gen.DATA_TABLES:
            conn.execute(f'CREATE TABLE "{table.name}" (row_id INTEGER)')
    gen._write_sqlite_metadata(db_path)

    report = gen._sqlite_snapshot_report(db_path)

    assert "sources.key" in report["missingColumnErrors"]
    assert "sources.row_id" in report["extraColumnErrors"]


def test_public_bundle_prunes_stale_board_provider_routes(tmp_path: Path) -> None:
    db_path = _write_quality_bundle(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO board_providers (
                id, source_key, board_key, provider_id, support_level
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("orphan-route", "source-1", "missing-board", "greenhouse", "jobs"),
        )
        conn.commit()

    assert gen._prune_orphan_board_provider_routes(db_path) == 1
    report = gen._sqlite_snapshot_report(db_path)

    assert report["orphanErrors"] == []
    with sqlite3.connect(db_path) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM board_providers WHERE id = 'orphan-route'"
            ).fetchone()[0]
            == 0
        )


def test_snapshot_quality_report_passes_for_complete_snapshot(tmp_path: Path) -> None:
    db_path = _write_quality_bundle(tmp_path)

    report = gen.snapshot_quality_report(
        output_dir=tmp_path,
        db_path=db_path,
        sync_metrics=_sync_metrics(),
        status=_status(),
        coverage=_coverage(),
    )

    assert report["status"] == "pass"
    assert report["hardBlockers"] == []
    assert report["counts"]["currentJobs"] == 1


def test_snapshot_quality_report_passes_for_parquet_only_exports(
    tmp_path: Path,
) -> None:
    db_path = _write_quality_bundle(tmp_path, job_versions=1)
    parquet_dir = tmp_path / gen.PARQUET_DIR
    gen.pl.DataFrame({"row_id": [1]}).write_parquet(
        parquet_dir / "job_version_skills.parquet"
    )
    gen.pl.DataFrame({"row_id": [1]}).write_parquet(
        parquet_dir / "job_version_skill_keywords.parquet"
    )
    for table in gen.TABLES:
        csv_path = tmp_path / gen.CSV_DIR / f"{table.name}.csv"
        if csv_path.is_file():
            csv_path.unlink()
    csv_dir = tmp_path / gen.CSV_DIR
    if csv_dir.exists() and not any(csv_dir.iterdir()):
        csv_dir.rmdir()

    report = gen.snapshot_quality_report(
        output_dir=tmp_path,
        db_path=db_path,
        sync_metrics=_sync_metrics(),
        status=_status(),
        coverage=_coverage(),
    )

    assert report["status"] == "pass"
    assert report["hardBlockers"] == []
    required_paths = {check["path"] for check in report["requiredFiles"]}
    assert not any(path.endswith(".csv") for path in required_paths)
    assert all(
        (tmp_path / path).is_file()
        for path in required_paths
        if path.endswith(".parquet")
    )


def test_snapshot_quality_report_blocks_structurally_unusable_snapshot(
    tmp_path: Path,
) -> None:
    db_path = _write_quality_bundle(
        tmp_path,
        sources=0,
        boards=0,
        routes=0,
    )

    report = gen.snapshot_quality_report(
        output_dir=tmp_path,
        db_path=db_path,
        sync_metrics=_sync_metrics(job_sync_runs=0, jobs_persisted=0),
        status=_status(sources=0, boards=0, routes=0, jobs=0),
        coverage=_coverage(),
    )

    assert report["status"] == "fail"
    assert "missing_source_evidence" in report["hardBlockers"]
    assert "missing_board_data" in report["hardBlockers"]
    assert "missing_executable_route_evidence" in report["hardBlockers"]


def test_snapshot_quality_report_blocks_empty_jobs_without_explanation(
    tmp_path: Path,
) -> None:
    db_path = _write_quality_bundle(tmp_path, jobs=0)

    report = gen.snapshot_quality_report(
        output_dir=tmp_path,
        db_path=db_path,
        sync_metrics=_sync_metrics(jobs_persisted=0),
        status=_status(jobs=0),
        coverage=_coverage(),
    )

    assert report["status"] == "fail"
    assert "missing_current_job_evidence" in report["hardBlockers"]


def test_snapshot_quality_report_allows_versions_with_empty_skills_json(
    tmp_path: Path,
) -> None:
    db_path = _write_quality_bundle(
        tmp_path,
        job_versions=1,
        job_version_skills_json="[]",
    )

    report = gen.snapshot_quality_report(
        output_dir=tmp_path,
        db_path=db_path,
        sync_metrics=_sync_metrics(),
        status=_status(),
        coverage=_coverage(),
    )

    assert report["status"] == "pass"
    assert "missing_job_version_skill_rows" not in report["hardBlockers"]
    assert "missing_job_version_skill_keyword_rows" not in report["hardBlockers"]


def test_snapshot_quality_report_blocks_empty_skill_tables(tmp_path: Path) -> None:
    db_path = _write_quality_bundle(
        tmp_path,
        job_versions=1,
        job_version_skills_json='[{"name":"Python"}]',
    )

    report = gen.snapshot_quality_report(
        output_dir=tmp_path,
        db_path=db_path,
        sync_metrics=_sync_metrics(),
        status=_status(),
        coverage=_coverage(),
    )

    assert report["status"] == "fail"
    assert "missing_job_version_skill_rows" in report["hardBlockers"]
    assert "missing_job_version_skill_keyword_rows" in report["hardBlockers"]


def test_snapshot_quality_report_uses_parquet_counts_for_sqlite_preview_tables(
    tmp_path: Path,
) -> None:
    db_path = _write_quality_bundle(tmp_path, job_versions=1)
    parquet_dir = tmp_path / gen.PARQUET_DIR
    gen.pl.DataFrame({"row_id": [1]}).write_parquet(
        parquet_dir / "job_version_skills.parquet"
    )
    gen.pl.DataFrame({"row_id": [1]}).write_parquet(
        parquet_dir / "job_version_skill_keywords.parquet"
    )

    report = gen.snapshot_quality_report(
        output_dir=tmp_path,
        db_path=db_path,
        sync_metrics=_sync_metrics(),
        status=_status(),
        coverage=_coverage(),
    )

    assert report["status"] == "pass"
    assert report["hardBlockers"] == []
    assert report["counts"]["job_version_skills"] == 1
    assert report["counts"]["job_version_skill_keywords"] == 1
    assert report["parquetCounts"] == {
        "job_version_skill_keywords": 1,
        "job_version_skills": 1,
    }


def test_snapshot_quality_report_allows_documented_empty_snapshot(
    tmp_path: Path,
) -> None:
    db_path = _write_quality_bundle(tmp_path, jobs=0)

    report = gen.snapshot_quality_report(
        output_dir=tmp_path,
        db_path=db_path,
        sync_metrics=_sync_metrics(jobs_persisted=0),
        status=_status(jobs=0),
        coverage=_coverage(),
        empty_snapshot_explanation="documented upstream outage",
    )

    assert report["status"] == "pass"
    assert "empty_snapshot_explanation_present" in report["warnings"]


def test_snapshot_quality_report_warns_for_classified_provider_errors(
    tmp_path: Path,
) -> None:
    db_path = _write_quality_bundle(tmp_path)

    report = gen.snapshot_quality_report(
        output_dir=tmp_path,
        db_path=db_path,
        sync_metrics=_sync_metrics(
            provider_errors={"workable": 1},
            provider_error_details={"workable": {"rate_limited": 1}},
        ),
        status=_status(),
        coverage=_coverage(),
    )

    assert report["status"] == "pass"
    assert "classified_provider_errors_present" in report["warnings"]


def test_snapshot_quality_report_blocks_unclassified_provider_errors(
    tmp_path: Path,
) -> None:
    db_path = _write_quality_bundle(tmp_path)

    report = gen.snapshot_quality_report(
        output_dir=tmp_path,
        db_path=db_path,
        sync_metrics=_sync_metrics(
            provider_errors={"workable": 2},
            provider_error_details={"workable": {"rate_limited": 1}},
        ),
        status=_status(),
        coverage=_coverage(),
    )

    assert report["status"] == "fail"
    assert "unclassified_provider_errors:workable" in report["hardBlockers"]


def test_snapshot_quality_report_blocks_dominant_provider_failures(
    tmp_path: Path,
) -> None:
    db_path = _write_quality_bundle(tmp_path, jobs=0)

    report = gen.snapshot_quality_report(
        output_dir=tmp_path,
        db_path=db_path,
        sync_metrics=_sync_metrics(
            job_sync_runs=1,
            jobs_persisted=0,
            provider_errors={"workable": 2},
            provider_error_details={"workable": {"rate_limited": 2}},
        ),
        status=_status(jobs=0),
        coverage=_coverage(),
    )

    assert report["status"] == "fail"
    assert "dominant_provider_failures" in report["hardBlockers"]


def test_snapshot_quality_report_requires_current_authoritative_success(
    tmp_path: Path,
) -> None:
    db_path = _write_quality_bundle(tmp_path, jobs=1, job_sync_runs=1)

    report = gen.snapshot_quality_report(
        output_dir=tmp_path,
        db_path=db_path,
        sync_metrics=_sync_metrics(
            job_sync_attempts=1,
            job_sync_runs=0,
            jobs_persisted=0,
            provider_errors={"workable": 1},
            provider_error_details={"workable": {"rate_limited": 1}},
        ),
        status=_status(jobs=1),
        coverage=_coverage(),
    )

    assert report["status"] == "fail"
    assert "missing_job_sync_run_evidence" in report["hardBlockers"]
    assert report["counts"]["jobSyncAttempts"] == 1
    assert report["counts"]["jobSyncRuns"] == 0


def _write_quality_bundle(
    output_dir: Path,
    *,
    sources: int = 1,
    boards: int = 1,
    routes: int = 1,
    jobs: int = 1,
    job_versions: int = 0,
    job_version_skills: int = 0,
    job_version_skill_keywords: int = 0,
    job_version_skills_json: str | None = None,
    job_sync_runs: int = 1,
) -> Path:
    db_path = output_dir / gen.DB_FILE
    with sqlite3.connect(db_path) as conn:
        for table in gen.DATA_TABLES:
            columns = ", ".join(
                f"{_quote_identifier(column)} TEXT"
                for column in table.model.model_fields
            )
            conn.execute(f"CREATE TABLE {_quote_identifier(table.name)} ({columns})")

        def insert_rows(
            table_name: str,
            columns: tuple[str, ...],
            rows: list[tuple[object, ...]],
        ) -> None:
            if not rows:
                return
            column_sql = ", ".join(_quote_identifier(column) for column in columns)
            placeholders = ", ".join("?" for _ in columns)
            conn.executemany(
                f"INSERT INTO {_quote_identifier(table_name)} ({column_sql}) "
                f"VALUES ({placeholders})",
                rows,
            )

        insert_rows(
            "sources",
            ("key",),
            [(f"source-{index}",) for index in range(1, sources + 1)],
        )
        insert_rows(
            "boards",
            ("key", "source_key"),
            [(f"board-{index}", "source-1") for index in range(1, boards + 1)],
        )
        insert_rows(
            "board_providers",
            ("id", "source_key", "board_key", "provider_id", "support_level"),
            [
                (f"route-{index}", "source-1", "board-1", "greenhouse", "jobs")
                for index in range(1, routes + 1)
            ],
        )
        current_version_id = "version-1" if job_versions else None
        insert_rows(
            "jobs",
            ("id", "board_key", "status", "current_version_id"),
            [
                (f"job-{index}", "board-1", "open", current_version_id)
                for index in range(1, jobs + 1)
            ],
        )
        if job_version_skills_json is None:
            insert_rows(
                "job_versions",
                ("id", "job_id"),
                [
                    (f"version-{index}", "job-1" if jobs else None)
                    for index in range(1, job_versions + 1)
                ],
            )
        else:
            insert_rows(
                "job_versions",
                ("id", "job_id", "skills"),
                [
                    (
                        f"version-{index}",
                        "job-1" if jobs else None,
                        job_version_skills_json,
                    )
                    for index in range(1, job_versions + 1)
                ],
            )
        insert_rows(
            "job_version_skills",
            ("id", "job_version_id", "ordinal"),
            [
                (f"skill-{index}", "version-1" if job_versions else None, index - 1)
                for index in range(1, job_version_skills + 1)
            ],
        )
        insert_rows(
            "job_version_skill_keywords",
            ("id", "skill_id"),
            [
                (f"keyword-{index}", "skill-1" if job_version_skills else None)
                for index in range(1, job_version_skill_keywords + 1)
            ],
        )
        insert_rows(
            "job_sync_runs",
            ("id", "board_key", "success"),
            [
                (f"sync-run-{index}", "board-1", 1)
                for index in range(1, job_sync_runs + 1)
            ],
        )
    gen._write_sqlite_metadata(db_path)
    _write_required_quality_files(output_dir)
    return db_path


def _write_required_quality_files(output_dir: Path) -> None:
    paths = [
        "dataset-metadata.json",
        gen.DATASET_IMAGE_FILE,
        gen.SYNC_METRICS_FILE,
        gen.STATUS_FILE,
        gen.COVERAGE_FILE,
        gen.SNAPSHOT_QUALITY_FILE,
    ]
    paths.extend(f"{gen.CSV_DIR}/{table.name}.csv" for table in gen.TABLES)
    paths.extend(f"{gen.PARQUET_DIR}/{table.name}.parquet" for table in gen.TABLES)
    for relative_path in paths:
        path = output_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")


def _notebook_setup_namespace(
    *,
    runtime_input: Path | None = None,
) -> dict[str, Any]:
    setup_source = gen._notebook_setup_source()
    setup_defs = setup_source.split("\nrequire_kaggle_credentials()\n", 1)[0]
    namespace: dict[str, Any] = {}
    exec(setup_defs, namespace)
    if runtime_input is not None:
        namespace["KAGGLE_INPUT_DIR"] = runtime_input
    return namespace


def _stage_runtime_input(runtime_input: Path) -> str:
    staging_dir = runtime_input.parent / "_staging"
    gen._stage_runtime_generator_dir(staging_dir)
    if runtime_input.exists():
        shutil.rmtree(runtime_input)
    shutil.copytree(
        staging_dir,
        runtime_input,
        ignore=shutil.ignore_patterns("dataset-metadata.json"),
    )
    shutil.rmtree(staging_dir)
    manifest = json.loads(
        (runtime_input / gen.RUNTIME_MANIFEST_FILE).read_text(encoding="utf-8")
    )
    return str(manifest["sha256"])


def _insert_representative_app_rows(db_path: Path) -> None:
    observed_at = "2026-06-16 12:00:00"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO sources (
                key, url, provider_id, version, raw_metadata,
                extra_payload, synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "source-1",
                "https://example.com/jobs",
                "getro",
                '{"name":"fixture"}',
                '{"catalog":"fixture"}',
                "{}",
                observed_at,
            ),
        )
        conn.execute(
            """
            INSERT INTO boards (
                key, source_key, source_keys, source_board_keys, remote_id,
                remote_slug, name, domain, website_url, description, markets,
                locations, staff_count, num_jobs_hint, raw_payload, extra_payload,
                synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "board-1",
                "source-1",
                '["source-1"]',
                '["source-1:board-1"]',
                "remote-board-1",
                "acme",
                "Acme",
                "example.com",
                "https://example.com",
                "Fixture board",
                '["SaaS"]',
                '["New York"]',
                10,
                1,
                '{"board":true}',
                "{}",
                observed_at,
            ),
        )
        conn.execute(
            """
            INSERT INTO board_providers (
                id, source_key, board_key, provider_id, label, support_level,
                count_hint, board_url, token, host, tenant, site, last_status,
                raw_payload, extra_payload, detected_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "board-provider-1",
                "source-1",
                "board-1",
                "greenhouse",
                "Greenhouse",
                "jobs",
                1,
                "https://boards.greenhouse.io/acme",
                "acme",
                None,
                None,
                None,
                "route_ready",
                '{"provider":true}',
                "{}",
                observed_at,
            ),
        )
        conn.execute(
            """
            INSERT INTO jobs (
                id, board_key, provider_id, remote_id, status, current_version_id,
                current_content_hash, current_payload_hash, first_seen_at,
                last_seen_at, closed_at, synced_at, extra_payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "job-1",
                "board-1",
                "greenhouse",
                "remote-job-1",
                "open",
                "version-1",
                "content-hash-1",
                "payload-hash-1",
                observed_at,
                observed_at,
                None,
                observed_at,
                "{}",
            ),
        )
        conn.execute(
            """
            INSERT INTO job_versions (
                id, job_id, version, content_hash, payload_hash, title,
                locations, department, team, workplace_type, company,
                employment_type, description, description_html, remote,
                compensation, salary, salary_min, salary_max, salary_currency,
                experience, responsibilities, qualifications, skills,
                job_description, posting_url, apply_url, posted_at, updated_at,
                extra_payload, first_seen_at, last_seen_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "version-1",
                "job-1",
                1,
                "content-hash-1",
                "payload-hash-1",
                "Software Engineer",
                '["New York"]',
                "Engineering",
                "Platform",
                "remote",
                "Acme",
                "full-time",
                "Build products.",
                "<p>Build products.</p>",
                "remote",
                '{"currency":"USD"}',
                "$100k",
                100000.0,
                150000.0,
                "USD",
                "mid",
                '["Build"]',
                '["Python"]',
                '[{"name":"Python"}]',
                '{"title":"Software Engineer"}',
                "https://example.com/jobs/1",
                "https://example.com/apply/1",
                "2026-06-16",
                "2026-06-16",
                "{}",
                observed_at,
                observed_at,
                observed_at,
            ),
        )
        conn.execute(
            "INSERT INTO job_version_locations VALUES (?, ?, ?, ?)",
            ("location-1", "version-1", 0, "New York"),
        )
        conn.execute(
            "INSERT INTO job_version_skills VALUES (?, ?, ?, ?, ?)",
            ("skill-1", "version-1", 0, "Python", "mid"),
        )
        conn.execute(
            "INSERT INTO job_version_skill_keywords VALUES (?, ?, ?, ?)",
            ("keyword-1", "skill-1", 0, "python"),
        )
        conn.execute(
            "INSERT INTO job_version_bullets VALUES (?, ?, ?, ?, ?)",
            ("bullet-1", "version-1", "responsibility", 0, "Build products."),
        )
        conn.execute(
            "INSERT INTO job_payload_snapshots VALUES (?, ?, ?, ?, ?, ?)",
            (
                "payload-1",
                "job-1",
                "listing",
                "payload-hash-1",
                '{"raw":true}',
                observed_at,
            ),
        )
        conn.execute(
            """
            INSERT INTO job_sync_runs (
                id, board_key, provider_id, synced_at, success, error, job_count,
                new_count, unchanged_count, changed_count, reopened_count,
                closed_count, started_at, finished_at, status, error_kind,
                authoritative, committed_batch_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "sync-run-1",
                "board-1",
                "greenhouse",
                observed_at,
                1,
                None,
                1,
                1,
                0,
                0,
                0,
                0,
                observed_at,
                observed_at,
                "succeeded",
                None,
                1,
                1,
            ),
        )
        conn.execute(
            "INSERT INTO job_sync_observations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "observation-1",
                "sync-run-1",
                "job-1",
                "version-1",
                "seen",
                "content-hash-1",
                "payload-hash-1",
                observed_at,
            ),
        )


def _copy_plain_public_snapshot(
    schema_db: Path,
    public_db: Path,
    *,
    app_table_names: tuple[str, ...],
) -> None:
    public_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(public_db) as conn:
        conn.execute(
            f"ATTACH DATABASE {_quote_sql_literal(schema_db.as_posix())} AS operational"
        )
        for table_name in app_table_names:
            conn.execute(
                f"CREATE TABLE {_quote_identifier(table_name)} AS "
                f"SELECT * FROM operational.{_quote_identifier(table_name)}"
            )
        conn.execute(
            """
            CREATE TABLE openopps_tables (
                table_name TEXT PRIMARY KEY,
                table_title TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO openopps_tables VALUES (?, ?)",
            ("sources", "Sources"),
        )
        conn.execute(
            """
            CREATE TABLE openopps_columns (
                table_name TEXT NOT NULL,
                column_name TEXT NOT NULL,
                column_title TEXT NOT NULL,
                PRIMARY KEY (table_name, column_name)
            )
            """
        )
        conn.execute(
            "INSERT INTO openopps_columns VALUES (?, ?, ?)",
            ("sources", "key", "Key"),
        )
        conn.commit()
        conn.execute("DETACH DATABASE operational")


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _quote_sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _has_sqlite_index(
    conn: sqlite3.Connection,
    table_name: str,
    columns: tuple[str, ...],
    *,
    unique: bool = False,
) -> bool:
    indexes = conn.execute(
        f"PRAGMA index_list({_quote_identifier(table_name)})"
    ).fetchall()
    for index in indexes:
        if unique and not index[2]:
            continue
        indexed_columns = tuple(
            row[2]
            for row in conn.execute(
                f"PRAGMA index_info({_quote_identifier(index[1])})"
            ).fetchall()
        )
        if indexed_columns == columns:
            return True
    return False


def _png_dimensions(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", header[16:24])


def _sync_metrics(
    *,
    job_sync_attempts: int | None = None,
    job_sync_runs: int = 1,
    jobs_persisted: int = 1,
    provider_errors: dict[str, int] | None = None,
    provider_error_details: dict[str, dict[str, int]] | None = None,
) -> dict[str, object]:
    return {
        "name": "sync",
        "jobsPersisted": jobs_persisted,
        "jobSyncAttempts": (
            job_sync_runs if job_sync_attempts is None else job_sync_attempts
        ),
        "jobSyncRuns": job_sync_runs,
        "jobsDeduped": 0,
        "providerErrors": provider_errors or {},
        "providerErrorDetails": provider_error_details or {},
    }


def _status(
    *,
    sources: int = 1,
    boards: int = 1,
    routes: int = 1,
    jobs: int = 1,
) -> dict[str, object]:
    return {
        "database": {
            "counts": {
                "sources": sources,
                "boards": boards,
                "boardProviders": routes,
                "jobs": jobs,
            }
        },
        "readiness": {"executableRoutes": routes},
    }


def _coverage() -> dict[str, object]:
    return {"routes": {"executable": 1}, "jobs": {"current": 1}}
