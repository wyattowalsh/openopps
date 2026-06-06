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
                assert field["title"] == gen._title_from_name(field["name"])
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
    assert jobs_fields["board_key"]["title"] == "Board Key"
    assert jobs_fields["board_key"]["description"] == "Board key this job belongs to."
    assert jobs_fields["board_key"]["type"] == "id"


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
    assert "--data-db" in source
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
    assert "capture_output=True" not in source
    for key, value in gen.NOTEBOOK_SYNC_ENV_DEFAULTS.items():
        assert f'"{key}": "{value}"' in source
    assert "run_json" in source
    assert "sync_metrics.json" in source
    assert "status.json" in source
    assert "coverage.json" in source
    assert "snapshot-quality.json" in source
    assert "--prune-private-upload-files" in source
    assert '"providers", "coverage", "--json"' in source
    assert "--quality-report" in source
    assert "OPENOPPS_EMPTY_SNAPSHOT_EXPLANATION" in source
    assert "kaggle" in source
    assert "datasets" in source
    assert "version" in source
    assert '"status", DATASET_ID, "--format", "json"' in source
    assert '"files", DATASET_ID, "--page-size", "200"' in source
    assert "zip" in source
    assert "KAGGLE_API_TOKEN" in source
    assert "KAGGLE_API_V1_TOKEN_PATH" in source
    assert "Kaggle API credentials are required" in source
    assert "KAGGLE_USERNAME" in source
    assert "KAGGLE_KEY" in source
    assert "def require_kaggle_credentials()" in source
    assert gen.DB_FILE in source
    assert source.index("require_kaggle_credentials()") < source.index(
        "install_openopps()"
    )
    assert source.index("install_openopps()") < source.index("copy_latest_input_db()")
    assert source.index("copy_latest_input_db()") < source.index(
        'run(["openopps", "admin", "db", "init"]'
    )
    assert source.index('["openopps", "sync", "--metrics-json"]') < source.index(
        "--data-db"
    )
    assert source.index("--data-db") < source.index("--quality-report")
    assert source.index("--quality-report") < source.index('"datasets"')
    assert gen.DATASET_IMAGE_SOURCE.as_posix() == "docs/public/social/openoppsdb.png"


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

    assert generated_dataset == gen.dataset_metadata()
    assert generated_kernel == gen.kernel_metadata()
    assert generated_notebook == gen.notebook()
    assert not (kaggle_dir / gen.DATAPACKAGE_FILE).exists()
    assert not (kaggle_dir / gen.EXPOSED_DATAPACKAGE_FILE).exists()
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


def test_table_export_frame_infers_full_sqlite_table_schema() -> None:
    rows = [
        {"id": "first", "remote": None},
        {"id": "second", "remote": None},
        {"id": "third", "remote": "REMOTE"},
    ]

    frame = gen._table_export_frame(gen.TABLES[0], rows)

    assert frame.height == 3
    assert frame["remote"].to_list() == [None, None, "REMOTE"]


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
    assert not (actual_files & set(gen.PRIVATE_EVIDENCE_FILES))
    assert not (actual_files & set(gen.PRIVATE_METADATA_FILES))


def test_live_kaggle_dataset_recipes_use_public_upload_stage() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    justfile = (repo_root / "Justfile").read_text(encoding="utf-8")

    assert "--stage-public-upload-dir" in justfile
    assert 'kaggle datasets create -p "$upload_dir"' in justfile
    assert 'kaggle datasets version -p "$upload_dir"' in justfile
    assert "kaggle datasets create -p kaggle" not in justfile
    assert "kaggle datasets version -p kaggle" not in justfile


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
