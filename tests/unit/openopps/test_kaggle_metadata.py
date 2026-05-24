from __future__ import annotations

import json
from pathlib import Path

from openopps.kaggle_metadata import (
    KAGGLE_DATASET_ID,
    KAGGLE_EXPORT_CSV_DIR,
    KAGGLE_EXPORT_PARQUET_DIR,
    KAGGLE_NOTEBOOK_ID,
    KAGGLE_NOTEBOOK_FILE,
    KAGGLE_RESOURCES,
    KAGGLE_SQLITE_FILE,
    KAGGLE_SQLITE_TABLES,
    build_kaggle_datapackage,
    build_kaggle_dataset_metadata,
    build_kaggle_kernel_metadata,
    build_kaggle_update_notebook,
)


def test_kaggle_dataset_metadata_has_required_kaggle_fields() -> None:
    metadata = build_kaggle_dataset_metadata()

    assert metadata["id"]
    assert metadata["title"]
    assert metadata["licenses"]
    assert metadata["description"]
    assert metadata["id"] == "wyattowalsh/openoppsdb"
    assert metadata["id"] == KAGGLE_DATASET_ID
    assert metadata["title"] == "openoppsdb"
    assert "datapackage.json" in metadata["description"]
    assert KAGGLE_SQLITE_FILE in metadata["description"]
    assert "Parquet" in metadata["description"]


def test_kaggle_datapackage_annotates_all_resource_fields() -> None:
    datapackage = build_kaggle_datapackage()
    resources = {resource["name"]: resource for resource in datapackage["resources"]}

    assert set(resources) == {resource.name for resource in KAGGLE_RESOURCES}
    sqlite_resource = resources["openopps_database"]
    assert sqlite_resource["path"] == KAGGLE_SQLITE_FILE
    assert sqlite_resource["format"] == "sqlite"
    assert {table["name"] for table in sqlite_resource["tables"]} == {
        table.name for table in KAGGLE_SQLITE_TABLES
    }
    for table in KAGGLE_SQLITE_TABLES:
        csv_resource = resources[f"{table.name}_csv"]
        parquet_resource = resources[f"{table.name}_parquet"]
        assert csv_resource["path"] == f"{KAGGLE_EXPORT_CSV_DIR}/{table.name}.csv"
        assert csv_resource["format"] == "csv"
        assert parquet_resource["path"] == (
            f"{KAGGLE_EXPORT_PARQUET_DIR}/{table.name}.parquet"
        )
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


def test_kaggle_notebook_metadata_runs_private_scheduled_snapshot() -> None:
    metadata = build_kaggle_kernel_metadata()
    notebook = build_kaggle_update_notebook()
    source = "\n".join(
        line for cell in notebook["cells"] for line in cell.get("source", [])
    )

    assert metadata["kernel_type"] == "notebook"
    assert metadata["enable_internet"] == "true"
    assert metadata["is_private"] == "true"
    assert metadata["id"] == "wyattowalsh/snapshot-openoppsdb"
    assert metadata["id"] == KAGGLE_NOTEBOOK_ID
    assert metadata["dataset_sources"] == [KAGGLE_DATASET_ID]
    assert metadata["code_file"] == KAGGLE_NOTEBOOK_FILE
    assert metadata["code_file"].endswith(".ipynb")
    assert "0 */6 * * *" in source
    assert KAGGLE_DATASET_ID in source
    assert "git+https://github.com/wyattowalsh/openopps.git@main" in source
    assert "/kaggle/input" in source
    assert "openopps-*.whl" not in source
    assert "**/openopps.sqlite" in source
    assert "Copied prior OpenOpps DB snapshot" in source
    assert "KAGGLE_EXPORT_CSV_DIR" in source
    assert "KAGGLE_EXPORT_PARQUET_DIR" in source
    assert "openopps" in source
    assert "sync" in source
    assert "--metrics-json" in source
    assert "kaggle" in source
    assert "datasets" in source
    assert "version" in source
    assert "KAGGLE_API_TOKEN" in source
    assert "KAGGLE_API_V1_TOKEN_PATH" in source
    assert KAGGLE_SQLITE_FILE in source


def test_generated_kaggle_metadata_artifacts_are_current() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    kaggle_dir = repo_root / "kaggle"

    dataset_metadata = json.loads(
        (kaggle_dir / "dataset-metadata.json").read_text(encoding="utf-8")
    )
    datapackage = json.loads(
        (kaggle_dir / "datapackage.json").read_text(encoding="utf-8")
    )
    kernel_metadata = json.loads(
        (kaggle_dir / "notebooks" / "kernel-metadata.json").read_text(encoding="utf-8")
    )
    notebook = json.loads(
        (kaggle_dir / "notebooks" / KAGGLE_NOTEBOOK_FILE).read_text(encoding="utf-8")
    )

    assert dataset_metadata == build_kaggle_dataset_metadata()
    assert datapackage == build_kaggle_datapackage()
    assert kernel_metadata == build_kaggle_kernel_metadata()
    assert notebook == build_kaggle_update_notebook()
