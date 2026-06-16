from __future__ import annotations

import importlib.util
import inspect
import json
from pathlib import Path
import sqlite3
import struct
import sys

from openopps.settings import OpenOppsSettings
from openopps.storage import OpenOppsStore

SCRIPT_PATH = (
    Path(__file__).resolve().parents[3] / "scripts/generate_kaggle_metadata.py"
)
SPEC = importlib.util.spec_from_file_location("generate_kaggle_metadata", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
gen = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gen
SPEC.loader.exec_module(gen)


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
    assert "Quick start" in metadata["description"]
    assert gen.DB_FILE in metadata["description"]
    assert "Parquet" in metadata["description"]
    assert set(resources) == {resource.path for resource in gen.RESOURCES}
    assert set(resources) == {resource.path for resource in gen.DATA_RESOURCES}
    assert resources[gen.DB_FILE]["description"]
    assert "schema" not in resources[gen.DB_FILE]
    assert {table["name"] for table in resources[gen.DB_FILE]["tables"]} == {
        table.name for table in gen.TABLES
    }
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
    sqlite_tables = {
        table_metadata["name"]: table_metadata
        for table_metadata in sqlite_resource["tables"]
    }
    assert set(sqlite_tables) == {table.name for table in gen.TABLES}
    assert "schema" not in sqlite_resource

    for table in gen.TABLES:
        expected_fields = list(table.model.model_fields)
        sqlite_table = sqlite_tables[table.name]
        assert sqlite_table["description"] == table.description
        sqlite_fields = sqlite_table["schema"]["fields"]
        assert [field["name"] for field in sqlite_fields] == expected_fields
        for path in (
            f"{gen.CSV_DIR}/{table.name}.csv",
            f"{gen.PARQUET_DIR}/{table.name}.parquet",
        ):
            resource = resources[path]
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
    assert metadata["dataset_sources"] == [gen.DATASET_ID]
    assert metadata["code_file"] == gen.NB_FILE
    assert metadata["code_file"] == "openoppsdb-manager.ipynb"
    assert metadata["code_file"].endswith(".ipynb")
    assert "0 6 * * *" in source
    assert "0 */6 * * *" not in source
    assert gen.DATASET_ID in source
    assert "git+https://github.com/wyattowalsh/openopps.git@main" in source
    assert "/kaggle/input" in source
    assert "openopps-*.whl" not in source
    assert "**/openoppsdb.sqlite" in source
    assert "/kaggle/working/openoppsdb" in source
    assert "Copied prior OpenOpps DB snapshot" in source
    assert "OPENOPPS_GENERATOR_SCRIPT_URL" in source
    assert "generate_kaggle_metadata.py" in source
    assert "openopps.kaggle_metadata" not in source
    assert "openopps" in source
    assert "sync" in source
    assert "--metrics-json" in source
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
    assert "DATASET_METADATA = {" in source
    assert "SQLITE_TABLE_METADATA = [" in source
    assert "OPENOPPS_TABLE_ROWS = [" in source
    assert "OPENOPPS_COLUMN_ROWS = [" in source
    assert "def write_public_bundle()" in source
    assert "def write_full_table_exports" in source
    assert "pl.scan_csv" in source
    assert "kaggle" in source
    assert "datasets" in source
    assert "version" in source
    assert '"status", DATASET_ID, "--format", "json"' in source
    assert '"files", DATASET_ID, "--page-size", "200"' in source
    assert "zip" in source
    assert "KAGGLE_API_TOKEN" in source
    assert "KAGGLE_API_V1_TOKEN_PATH" in source
    assert "UserSecretsClient" in source
    assert "user_secrets = UserSecretsClient()" in source
    assert 'secret_value_0 = user_secrets.get_secret("KAGGLE_KEY")' in source
    assert 'secret_value_1 = user_secrets.get_secret("KAGGLE_USERNAME")' in source
    assert 'client.get_secret("KAGGLE_API_TOKEN")' not in source
    assert "def load_kaggle_notebook_secrets()" in source
    assert "def read_kaggle_notebook_secrets" in source
    assert "OPENOPPS_KAGGLE_SECRET_RETRIES" in source
    assert "time.sleep(KAGGLE_SECRET_RETRY_SECONDS)" in source
    assert "Kaggle API credentials are required" in source
    assert "OPENOPPS_KAGGLE_SQLITE_INDEX_WAIT_SECONDS" in source
    assert "Waiting for Kaggle SQLite indexer metadata" in source
    assert "kaggle_databundle_files(session, headers, basics)" in source
    assert "def project_sqlite_for_kaggle_indexer" in source
    assert "def normalize_sqlite_schema_for_kaggle_indexer" in source
    assert "def rebuild_sqlite_tables_for_kaggle_indexer" in source
    assert '("job_versions", "description_html")' in source
    assert '("job_versions", "description")' in source
    assert '("boards", "raw_payload")' in source
    assert "INPUT_BOARDS_PARQUET_GLOB" in source
    assert "INPUT_JOB_VERSIONS_PARQUET_GLOB" in source
    assert "INPUT_JOB_PAYLOAD_SNAPSHOTS_PARQUET_GLOB" in source
    assert "def restore_projected_sqlite_columns_from_input_exports()" in source
    assert "restore_projected_sqlite_columns_from_input_exports()" in source
    assert '"description_html",' in source
    assert '"job_description",' in source
    assert '"responsibilities",' in source
    assert 'key_column="key"' in source
    assert 'column_names=["payload"]' in source
    assert "csv.field_size_limit(sys.maxsize)" in source
    assert "KAGGLE_USERNAME" in source
    assert "KAGGLE_KEY" in source
    compact_source = "\n".join(
        line.strip() for line in source.splitlines() if line.strip()
    )
    assert (
        "require_kaggle_credentials()\n"
        "install_openopps()\n"
        "copy_latest_input_db()\n"
        "download_dataset_assets()"
    ) in compact_source
    assert "def update_kaggle_dataset_file_metadata(" in source
    assert "def try_update_kaggle_dataset_file_metadata(" in source
    assert "def kaggle_dataset_status()" in source
    assert "previous_status = kaggle_dataset_status()" in source
    assert "current_version_number" in source
    assert "published_basics = wait_for_new_live_dataset_version(previous_version)" in source
    assert "expected_version = previous_version + 1" in source
    assert "current_version >= expected_version" in source
    assert "dataset_version_number=expected_version" in source
    assert "path for path in PUBLIC_UPLOAD_DATA_FILES if path not in live_files" in source
    assert "try_update_kaggle_dataset_file_metadata(published_basics)" in source
    metadata_update_call = source.rindex(
        "try_update_kaggle_dataset_file_metadata(published_basics)"
    )
    assert source.index('"zip"', source.index('"datasets"')) < metadata_update_call
    assert metadata_update_call < source.index(
        'run(["kaggle", "datasets", "status", DATASET_ID, "--format", "json"]'
    )
    assert "ApiUpdateDatasetMetadataRequest" in source
    assert "DatasetSettingsFile" in source
    assert "datasets.databundles.DatabundleService/UpdateDatabundleMetadataExternal" in source
    assert "datasets.databundles.DatabundleService/GetDatabundleExternalColumns" in source
    assert "def update_sqlite_table_metadata_external(" in source
    assert "Kaggle SQLite indexer did not index openoppsdb.sqlite" in source
    assert "sqliteTables" in source
    assert "def finalize_sqlite_for_upload(" in source
    assert "VACUUM INTO" in source
    assert "PRAGMA journal_mode=DELETE" in source
    assert "header read/write versions" in source
    assert "kaggle_basic_auth_header()" in source
    assert "X-XSRF-TOKEN" in source
    assert "Kaggle live dataset version ready for metadata repair" in source
    assert "OpenOpps live metadata repair:" in source
    assert "def backfill_openopps_skill_tables" in source
    assert "OpenOpps skill backfill:" in source
    assert "def run_sync_metrics(" in source
    assert "sqlite-derived-after-plain-sync" in source
    assert '"jobs",' in source
    assert '"sync",' in source
    assert '"--freshness-seconds",' in source
    assert '"--limit",' in source
    assert "OPENOPPS_KAGGLE_JOB_ROUTE_LIMIT" in source
    assert "bounded openopps jobs sync --metrics-json failed" in source
    embedded_sync = source[
        source.index("EMBEDDED_BOUNDED_JOB_SYNC_CODE")
        : source.index("def openopps_cli_supports_bounded_jobs_sync")
    ]
    assert (
        'output_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\\n")'
        in embedded_sync
    )
    assert "def compiled_skill_catalog" in source
    assert "compile_skill_aliases(tuple(aliases))" in source
    assert "LIMIT ? OFFSET ?" not in source
    assert source.index("run_sync_metrics(") < source.index(
        "backfill_openopps_skill_tables(DB_PATH)"
    )
    assert "def require_kaggle_credentials()" in source
    assert gen.DB_FILE in source
    setup_db_init = compact_source.index('run(["openopps", "admin", "db", "init"]')
    setup_calls = compact_source[
        compact_source.index("require_kaggle_credentials()\ninstall_openopps()") :
        setup_db_init
    ]
    assert setup_calls.index("require_kaggle_credentials()") < setup_calls.index(
        "install_openopps()"
    )
    assert setup_calls.index("install_openopps()") < setup_calls.index(
        "copy_latest_input_db()"
    )
    assert setup_calls.index("copy_latest_input_db()") < setup_calls.index(
        "download_dataset_assets()"
    )
    assert compact_source.index("download_dataset_assets()") < setup_db_init
    assert source.index('"jobs",') < source.index(
        "backfill_openopps_skill_tables(DB_PATH)"
    )
    assert source.index(
        "skill_backfill = backfill_openopps_skill_tables(DB_PATH)"
    ) < source.index(
        "quality = write_public_bundle()"
    )
    quality_call = source.index("quality = write_public_bundle()")
    assert quality_call < source.index('"datasets"', quality_call)
    assert gen.DATASET_IMAGE_SOURCE.as_posix() == "docs/public/social/openoppsdb.png"


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


def test_generated_kaggle_metadata_artifacts_are_current() -> None:
    repo_root = Path(__file__).resolve().parents[3]
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

    assert generated_dataset == gen.dataset_metadata()
    assert generated_kernel == gen.kernel_metadata()
    assert generated_notebook == gen.notebook()
    assert generated_starter_kernel == gen.starter_kernel_metadata()
    assert generated_starter_notebook == gen.starter_notebook()
    assert not (kaggle_dir / gen.DATAPACKAGE_FILE).exists()
    assert not (kaggle_dir / gen.EXPOSED_DATAPACKAGE_FILE).exists()
    assert not any((repo_root / "kaggle-manager").glob("*"))
    assert not (kaggle_dir / "notebooks").exists()
    assert (kaggle_dir / gen.DATASET_IMAGE_FILE).is_file()
    assert generated_dataset["image"] == gen.DATASET_IMAGE_FILE


def test_generated_kaggle_dataset_image_matches_metadata_contract() -> None:
    repo_root = Path(__file__).resolve().parents[3]
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

    assert source.index("_drop_private_sqlite_tables(build_db)") < source.index(
        "_backfill_sqlite_skill_tables(build_db)"
    )
    assert source.index("_backfill_sqlite_skill_tables(build_db)") < source.index(
        "_write_sqlite_metadata(build_db)"
    )
    assert source.index("_write_sqlite_metadata(build_db)") < source.index(
        "_write_full_table_exports(output_dir, build_db)"
    )
    assert source.index("_write_full_table_exports(output_dir, build_db)") < source.index(
        "_project_sqlite_for_kaggle_indexer(build_db)"
    )
    assert source.index("_project_sqlite_for_kaggle_indexer(build_db)") < source.index(
        "_normalize_sqlite_schema_for_kaggle_indexer(build_db)"
    )
    assert source.index("_normalize_sqlite_schema_for_kaggle_indexer(build_db)") < source.index(
        "_rebuild_sqlite_tables_for_kaggle_indexer(build_db)"
    )
    assert source.index("_rebuild_sqlite_tables_for_kaggle_indexer(build_db)") < source.index(
        "_finalize_sqlite_for_upload(build_db)"
    )


def test_sqlite_upload_projection_nulls_large_rendered_html_mirror(
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

    result = gen._project_sqlite_for_kaggle_indexer(db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, description, description_html, job_description "
            "FROM job_versions ORDER BY id"
        ).fetchall()
        payload_rows = conn.execute(
            "SELECT id, payload FROM job_payload_snapshots ORDER BY id"
        ).fetchall()

    assert result == {
        "projected_rows": 5,
        "estimated_bytes_removed": (
            len("plain text")
            + len("already compact")
            + len("<p>plain text</p>")
            + len('{"title":"Engineer"}')
            + len('{"raw":true}')
        ),
    }
    assert rows == [
        ("version-1", None, None, None),
        ("version-2", None, None, None),
    ]
    assert payload_rows == [("payload-1", None)]


def test_local_data_artifact_writer_restores_projected_columns_from_parquet(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / gen.DB_FILE
    parquet_dir = tmp_path / gen.PARQUET_DIR
    parquet_dir.mkdir(parents=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute('CREATE TABLE boards ("key" TEXT PRIMARY KEY, raw_payload TEXT)')
        conn.execute(
            """
            CREATE TABLE job_versions (
                id TEXT PRIMARY KEY,
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
        conn.execute("INSERT INTO boards VALUES ('board-1', NULL)")
        conn.execute(
            "INSERT INTO job_versions VALUES ('version-1', NULL, NULL, NULL, NULL, NULL, NULL, NULL)"
        )
        conn.execute("INSERT INTO job_payload_snapshots VALUES ('payload-1', NULL)")
    gen.pl.DataFrame(
        {"key": ["board-1"], "raw_payload": ['{"board": true}']}
    ).write_parquet(parquet_dir / "boards.parquet")
    gen.pl.DataFrame(
        {
            "id": ["version-1"],
            "description": ["plain"],
            "description_html": ["<p>plain</p>"],
            "job_description": ['{"plain": true}'],
            "responsibilities": ["[]"],
            "qualifications": ["[]"],
            "skills": ["[]"],
            "compensation": ["salary"],
        }
    ).write_parquet(parquet_dir / "job_versions.parquet")
    gen.pl.DataFrame(
        {"id": ["payload-1"], "payload": ['{"raw": true}']}
    ).write_parquet(parquet_dir / "job_payload_snapshots.parquet")

    result = gen._restore_projected_sqlite_columns_from_export_dir(
        db_path,
        parquet_dir,
    )

    with sqlite3.connect(db_path) as conn:
        board_payload = conn.execute("SELECT raw_payload FROM boards").fetchone()[0]
        version = conn.execute(
            "SELECT description, description_html, job_description, compensation "
            "FROM job_versions"
        ).fetchone()
        payload = conn.execute(
            "SELECT payload FROM job_payload_snapshots"
        ).fetchone()[0]

    assert result == {"tables": 3, "rows": 3}
    assert board_payload == '{"board": true}'
    assert version == ("plain", "<p>plain</p>", '{"plain": true}', "salary")
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

    updated = gen._normalize_sqlite_schema_for_kaggle_indexer(db_path)

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


def test_sqlite_upload_rebuilds_plain_tables_for_kaggle_indexer(
    tmp_path: Path,
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

    result = gen._rebuild_sqlite_tables_for_kaggle_indexer(db_path)

    with sqlite3.connect(db_path) as conn:
        ddl = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT name, sql FROM sqlite_schema WHERE type = 'table'"
            )
        }
        child = conn.execute("SELECT * FROM child").fetchone()

    assert result == {"tables": 2, "rows": 2}
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
        source.index("def _backfill_sqlite_skill_tables") :
        source.index("def _extract_version_skills")
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
        conn.execute("CREATE TABLE alembic_version (version_num TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO alembic_version VALUES ('0001')")

    gen._drop_private_sqlite_tables(db_path)

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert "http_cache" not in tables
    assert "alembic_version" not in tables


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


def test_generated_data_files_are_all_described_when_present() -> None:
    repo_root = Path(__file__).resolve().parents[3]
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
    repo_root = Path(__file__).resolve().parents[3]
    kaggle_dir = repo_root / "kaggle"
    allowed_public_files = {
        "dataset-cover-image.png",
        "dataset-metadata.json",
        "kernel-metadata.json",
        gen.NB_FILE,
        f"starter/{gen.STARTER_NB_FILE}",
        "starter/kernel-metadata.json",
        gen.DB_FILE,
        *{f"{gen.CSV_DIR}/{table.name}.csv" for table in gen.TABLES},
        *{f"{gen.PARQUET_DIR}/{table.name}.parquet" for table in gen.TABLES},
    }
    if not (kaggle_dir / gen.DB_FILE).exists():
        allowed_public_files.remove(gen.DB_FILE)

    actual_files = {
        path.relative_to(kaggle_dir).as_posix()
        for path in kaggle_dir.rglob("*")
        if path.is_file()
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
    (bundle_dir / gen.DB_FILE).write_bytes(b"SQLite format 3\x00")
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
    assert not (actual_files & set(gen.PRIVATE_EVIDENCE_FILES))
    assert not (actual_files & set(gen.PRIVATE_METADATA_FILES))


def test_public_upload_stage_prefers_hardlinks() -> None:
    source = inspect.getsource(gen._stage_public_upload_dir)

    assert "hardlink_to" in source
    assert "shutil.copy2" in source


def test_live_kaggle_dataset_recipes_use_public_upload_stage() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    justfile = (repo_root / "Justfile").read_text(encoding="utf-8")

    assert "--stage-public-upload-dir" in justfile
    assert 'kaggle := "uv run --with kaggle kaggle"' in justfile
    assert '{{ kaggle }} datasets create -p "$upload_dir"' in justfile
    assert '{{ kaggle }} datasets version -p "$upload_dir"' in justfile
    assert "{{ kaggle }} datasets status wyattowalsh/openoppsdb" in justfile
    assert "current_version=" in justfile
    assert "next_version=" in justfile
    assert "--wait-live-dataset-ready" in justfile
    assert '--wait-live-dataset-min-version "$next_version"' in justfile
    assert "--live-file-metadata-browser-cookies" in justfile
    assert "--with browser-cookie3" in justfile
    assert "kagglehub-live-readback" in justfile
    assert "scripts/verify_kagglehub_readback.py" in justfile
    assert "kagglehub[polars-datasets]" in justfile
    assert '${dataset#dataset=}' in justfile
    assert '${dataset#version=}' in justfile
    assert '${version#version=}' in justfile
    assert (
        "kaggle-live-verify: kaggle-live-status kaggle-live-files "
        "kagglehub-live-readback"
    ) in justfile
    assert "kaggle datasets create -p kaggle" not in justfile
    assert "kaggle datasets version -p kaggle" not in justfile


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


def test_sqlite_table_metadata_repair_fails_when_kaggle_has_not_indexed_sqlite() -> None:
    def post(route: str, body: dict) -> dict:
        raise AssertionError(route)

    try:
        gen._update_sqlite_table_metadata_external(
            post,
            {"datasetId": 1, "databundleVersionId": 2},
            {"path": "files/openoppsdb.sqlite"},
        )
    except RuntimeError as exc:
        assert "Kaggle SQLite indexer did not index openoppsdb.sqlite" in str(exc)
    else:
        raise AssertionError("Expected missing sqliteInfo to fail")


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
        gen,
        "_kaggle_dataset_status",
        lambda dataset_id: next(statuses),
    )
    monkeypatch.setattr(gen.time, "sleep", lambda seconds: sleeps.append(seconds))

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


def test_snapshot_quality_report_blocks_structurally_unusable_snapshot(
    tmp_path: Path,
) -> None:
    db_path = _write_quality_bundle(
        tmp_path,
        enabled_sources=0,
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
    assert "missing_enabled_source_evidence" in report["hardBlockers"]
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


def test_snapshot_quality_report_blocks_empty_skill_tables(tmp_path: Path) -> None:
    db_path = _write_quality_bundle(tmp_path, job_versions=1)

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


def _write_quality_bundle(
    output_dir: Path,
    *,
    enabled_sources: int = 1,
    boards: int = 1,
    routes: int = 1,
    jobs: int = 1,
    job_versions: int = 0,
    job_version_skills: int = 0,
    job_version_skill_keywords: int = 0,
    job_sync_runs: int = 1,
) -> Path:
    db_path = output_dir / gen.DB_FILE
    with sqlite3.connect(db_path) as conn:
        for table in gen.DATA_TABLES:
            extra_columns = {
                "sources": "enabled INTEGER",
                "jobs": "status TEXT",
                "board_providers": "support_level TEXT",
                "job_sync_runs": "success INTEGER",
            }.get(table.name)
            columns = "row_id INTEGER"
            if extra_columns:
                columns = f"{columns}, {extra_columns}"
            conn.execute(f'CREATE TABLE "{table.name}" ({columns})')
        conn.executemany(
            "INSERT INTO sources (enabled) VALUES (1)",
            [() for _ in range(enabled_sources)],
        )
        conn.executemany(
            "INSERT INTO boards (row_id) VALUES (1)",
            [() for _ in range(boards)],
        )
        conn.executemany(
            "INSERT INTO board_providers (support_level) VALUES ('jobs')",
            [() for _ in range(routes)],
        )
        conn.executemany(
            "INSERT INTO jobs (status) VALUES ('open')",
            [() for _ in range(jobs)],
        )
        conn.executemany(
            "INSERT INTO job_versions (row_id) VALUES (1)",
            [() for _ in range(job_versions)],
        )
        conn.executemany(
            "INSERT INTO job_version_skills (row_id) VALUES (1)",
            [() for _ in range(job_version_skills)],
        )
        conn.executemany(
            "INSERT INTO job_version_skill_keywords (row_id) VALUES (1)",
            [() for _ in range(job_version_skill_keywords)],
        )
        conn.executemany(
            "INSERT INTO job_sync_runs (success) VALUES (1)",
            [() for _ in range(job_sync_runs)],
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


def _png_dimensions(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", header[16:24])


def _sync_metrics(
    *,
    job_sync_runs: int = 1,
    jobs_persisted: int = 1,
    provider_errors: dict[str, int] | None = None,
    provider_error_details: dict[str, dict[str, int]] | None = None,
) -> dict[str, object]:
    return {
        "name": "sync",
        "jobsPersisted": jobs_persisted,
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
