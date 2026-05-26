from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sqlite3
import sys

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
    assert metadata["description"]
    assert metadata["id"] == "wyattowalsh/openoppsdb"
    assert metadata["id"] == gen.DATASET_ID
    assert metadata["title"] == "openoppsdb"
    assert metadata["image"] == gen.DATASET_IMAGE_FILE
    assert metadata["expectedUpdateFrequency"] == "daily"
    assert metadata["userSpecifiedSources"]
    assert metadata["keywords"]
    assert "datapackage.json" in metadata["description"]
    assert "openoppsdb-manager" in metadata["description"]
    assert "Quick start" in metadata["description"]
    assert gen.DB_FILE in metadata["description"]
    assert "Parquet" in metadata["description"]
    assert set(resources) == {resource.path for resource in gen.RESOURCES} | {
        "datapackage.json"
    }
    assert resources[gen.DB_FILE]["description"]
    assert "schema" not in resources[gen.DB_FILE]
    assert resources["datapackage.json"]["description"]


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

    for table in gen.TABLES:
        expected_fields = list(table.model.model_fields)
        for path in (
            f"{gen.CSV_DIR}/{table.name}.csv",
            f"{gen.PARQUET_DIR}/{table.name}.parquet",
        ):
            resource = resources[path]
            fields = resource["schema"]["fields"]
            assert [field["name"] for field in fields] == expected_fields
            for field in fields:
                assert field["title"]
                assert field["description"], field["name"]
                assert field["title"] == field["description"]
                assert field["type"] in supported_types
                assert field["type"] != "str"
                assert field["type"] != "bool"
                assert "object<" not in field["type"]
                assert "array<" not in field["type"]
                assert "Annotated" not in field["type"]
                assert "typing." not in field["type"]
                assert "| null" not in field["type"]


def test_kaggle_datapackage_annotates_all_resource_fields() -> None:
    data = gen.datapackage()
    resources = {resource["name"]: resource for resource in data["resources"]}

    assert set(resources) == {resource.name for resource in gen.RESOURCES}
    sqlite_resource = resources["openopps_database"]
    assert sqlite_resource["path"] == gen.DB_FILE
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
        assert csv_resource["format"] == "csv"
        assert parquet_resource["path"] == f"{gen.PARQUET_DIR}/{table.name}.parquet"
        assert parquet_resource["format"] == "parquet"
    for resource in resources.values():
        schemas = []
        if "schema" in resource:
            schemas.append(resource["schema"])
        schemas.extend(table["schema"] for table in resource.get("tables", []))
        assert schemas
        for schema in schemas:
            fields = schema["fields"]
            assert fields
            for field in fields:
                assert field["name"]
                assert field["title"]
                assert field["description"], field["name"]
                assert field["type"]
                assert "Annotated[" not in field["type"]
                assert field["jsonSchemaType"]
                assert isinstance(field["required"], bool)


def test_kaggle_notebook_metadata_runs_public_scheduled_snapshot() -> None:
    metadata = gen.kernel_metadata()
    data = gen.notebook()
    source = "\n".join(
        line for cell in data["cells"] for line in cell.get("source", [])
    )

    assert metadata["kernel_type"] == "notebook"
    assert metadata["enable_internet"] is True
    assert metadata["is_private"] is True
    assert metadata["id"] == "wyattowalsh/openoppsdb-manager"
    assert metadata["id"] == gen.NB_ID
    assert metadata["id_no"] == 120479527
    assert metadata["title"] == "openoppsdb manager"
    assert metadata["dataset_sources"] == [gen.DATASET_ID]
    assert metadata["code_file"] == gen.NB_FILE
    assert metadata["code_file"] == "openoppsdb-manager.ipynb"
    assert metadata["code_file"].endswith(".ipynb")
    assert "0 */6 * * *" in source
    assert gen.DATASET_ID in source
    assert "git+https://github.com/wyattowalsh/openopps.git@main" in source
    assert "/kaggle/input" in source
    assert "openopps-*.whl" not in source
    assert "**/openoppsdb.sqlite" in source
    assert "/kaggle/working/openoppsdb" in source
    assert "Copied prior OpenOpps DB snapshot" in source
    assert "OPENOPPS_GENERATOR_SCRIPT_URL" in source
    assert "generate_kaggle_metadata.py" in source
    assert "--data-db" in source
    assert "openopps.kaggle_metadata" not in source
    assert "openopps" in source
    assert "sync" in source
    assert "--metrics-json" in source
    assert "kaggle" in source
    assert "datasets" in source
    assert "version" in source
    assert "zip" in source
    assert "KAGGLE_API_TOKEN" in source
    assert "KAGGLE_API_V1_TOKEN_PATH" in source
    assert gen.DB_FILE in source
    assert source.index("install_openopps()") < source.index("copy_latest_input_db()")
    assert source.index("copy_latest_input_db()") < source.index(
        'run(["openopps", "admin", "db", "init"]'
    )
    assert source.index('run(["openopps", "sync", "--metrics-json"]') < source.index(
        "--data-db"
    )
    assert source.index("--data-db") < source.index('"datasets"')
    assert gen.DATASET_IMAGE_SOURCE.as_posix() == "docs/public/social/openoppsdb.png"


def test_generated_kaggle_metadata_artifacts_are_current() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    kaggle_dir = repo_root / "kaggle"

    generated_dataset = json.loads(
        (kaggle_dir / "dataset-metadata.json").read_text(encoding="utf-8")
    )
    generated_datapackage = json.loads(
        (kaggle_dir / "datapackage.json").read_text(encoding="utf-8")
    )
    generated_kernel = json.loads(
        (kaggle_dir / "kernel-metadata.json").read_text(encoding="utf-8")
    )
    generated_notebook = json.loads(
        (kaggle_dir / gen.NB_FILE).read_text(encoding="utf-8")
    )

    assert generated_dataset == gen.dataset_metadata()
    assert generated_datapackage == gen.datapackage()
    assert generated_kernel == gen.kernel_metadata()
    assert generated_notebook == gen.notebook()
    assert not any((repo_root / "kaggle-manager").glob("*"))
    assert not (kaggle_dir / "notebooks").exists()
    assert (kaggle_dir / gen.DATASET_IMAGE_FILE).is_file()


def test_data_artifact_writer_adds_metadata_before_exports() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert source.index("_drop_cache_tables(target_db)") < source.index(
        "_write_sqlite_metadata(target_db)"
    )
    assert source.index("_write_sqlite_metadata(target_db)") < source.index(
        "_write_full_table_exports(output_dir, target_db)"
    )


def test_kaggle_artifact_cleanup_drops_http_cache_table(tmp_path: Path) -> None:
    db_path = tmp_path / gen.DB_FILE
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE http_cache (key TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO http_cache VALUES ('cached')")

    gen._drop_cache_tables(db_path)

    with sqlite3.connect(db_path) as conn:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'http_cache'"
        ).fetchone()
    assert table is None


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

    datapackage_paths = {
        resource["path"] for resource in gen.datapackage()["resources"]
    }
    dataset_paths = {
        resource["path"] for resource in gen.dataset_metadata()["resources"]
    }
    assert set(data_files) <= datapackage_paths
    assert set(data_files) <= dataset_paths


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
