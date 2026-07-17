"""Prod-ready gates: clean schema, sync contract, size, fail-closed publish."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import openopps_kaggle.generator as gen
from openopps_kaggle.constants import (
    NOTEBOOK_JOB_ROUTE_LIMIT,
    PUBLIC_EXPORTS_MAX_BYTES,
    PUBLIC_SQLITE_MAX_BYTES,
)

REPO_ROOT = Path(__file__).resolve().parents[4]


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _write_quality_bundle(output_dir: Path) -> Path:
    """Minimal public-shaped SQLite used by integrity/upload tests."""
    db_path = output_dir / gen.DB_FILE
    with sqlite3.connect(db_path) as conn:
        for table in gen.DATA_TABLES:
            columns = ", ".join(
                f"{_quote_identifier(column)} TEXT"
                for column in table.model.model_fields
            )
            conn.execute(f"CREATE TABLE {_quote_identifier(table.name)} ({columns})")
        conn.execute(
            f'INSERT INTO {_quote_identifier("sources")} '
            f"({_quote_identifier('key')}) VALUES (?)",
            ("source-1",),
        )
        conn.execute(
            f'INSERT INTO {_quote_identifier("boards")} '
            f"({_quote_identifier('key')}, {_quote_identifier('source_key')}) "
            "VALUES (?, ?)",
            ("board-1", "source-1"),
        )
        conn.execute(
            f'INSERT INTO {_quote_identifier("board_providers")} '
            f"({_quote_identifier('id')}, {_quote_identifier('source_key')}, "
            f"{_quote_identifier('board_key')}, {_quote_identifier('provider_id')}, "
            f"{_quote_identifier('support_level')}) VALUES (?, ?, ?, ?, ?)",
            ("route-1", "source-1", "board-1", "greenhouse", "jobs"),
        )
        conn.execute(
            f'INSERT INTO {_quote_identifier("jobs")} '
            f"({_quote_identifier('id')}, {_quote_identifier('board_key')}, "
            f"{_quote_identifier('status')}) VALUES (?, ?, ?)",
            ("job-1", "board-1", "open"),
        )
        conn.execute(
            f'INSERT INTO {_quote_identifier("job_sync_runs")} '
            f"({_quote_identifier('id')}, {_quote_identifier('board_key')}, "
            f"{_quote_identifier('success')}) VALUES (?, ?, ?)",
            ("sync-run-1", "board-1", 1),
        )
    gen._write_sqlite_metadata(db_path)
    return db_path


def test_manager_sync_contract_is_bounded_jobs_sync() -> None:
    """Manager notebook setup embeds bounded jobs sync (not unfiltered openopps sync)."""
    notebook = gen.notebook()
    notebook_source = "\n".join(
        line
        for cell in notebook.get("cells", [])
        for line in (
            cell.get("source", [])
            if isinstance(cell.get("source"), list)
            else [str(cell.get("source", ""))]
        )
    )
    setup_source = gen._notebook_setup_source()
    combined = notebook_source + "\n" + setup_source

    assert "--metrics-json" in combined
    assert "--freshness-seconds" in combined
    assert "--limit" in combined
    # Embedded helper builds argv for jobs sync.
    assert '"jobs"' in setup_source
    assert '"sync"' in setup_source
    assert "openopps jobs sync" in gen._dataset_description()
    assert NOTEBOOK_JOB_ROUTE_LIMIT == 120
    # Unfiltered full CLI sync is not the manager path.
    assert "openopps\",\n            \"sync\",\n            \"--metrics-json\"" not in setup_source


def test_public_upload_writer_hard_fails_legacy_sources_enabled(
    tmp_path: Path,
) -> None:
    """Legacy sources.enabled must fail the real public upload writer path."""
    db_path = _write_quality_bundle(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("ALTER TABLE sources ADD COLUMN enabled INTEGER DEFAULT 1")
        conn.commit()

    out = tmp_path / "out"
    out.mkdir()
    # Copy required control files lightly so writer can proceed to integrity.
    (out / "dataset-metadata.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match=r"sources\.enabled") as excinfo:
        gen._write_data_artifacts(out, db_path)

    message = str(excinfo.value)
    assert "legacy or unexpected column" in message or "sources.enabled" in message
    assert "sources.enabled" in message


def test_public_upload_writer_clean_db_integrity_ok(tmp_path: Path) -> None:
    """Clean-schema fixture yields integrity-ok public SQLite via real writer."""
    db_path = _write_quality_bundle(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "dataset-metadata.json").write_text("{}\n", encoding="utf-8")

    gen._write_data_artifacts(out, db_path)

    public_db = out / gen.DB_FILE
    assert public_db.is_file()
    with sqlite3.connect(public_db) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        cols = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(sources)").fetchall()
        }
    assert integrity == "ok"
    assert "enabled" not in cols
    parquet_dir = out / gen.PARQUET_DIR
    assert parquet_dir.is_dir()
    assert any(parquet_dir.glob("*.parquet"))


def test_snapshot_quality_blocks_oversize_sqlite(tmp_path: Path, monkeypatch) -> None:
    import openopps_kaggle._core as core

    db_path = _write_quality_bundle(tmp_path)
    # Function resolves PUBLIC_SQLITE_MAX_BYTES from _core globals.
    monkeypatch.setattr(core, "PUBLIC_SQLITE_MAX_BYTES", 1)

    blockers = core._public_snapshot_size_blockers(output_dir=tmp_path, db_path=db_path)
    assert any(b.startswith("public_sqlite_oversize:") for b in blockers)

    report = core.snapshot_quality_report(
        output_dir=tmp_path,
        db_path=db_path,
        sync_metrics={
            "routesAttempted": 1,
            "routesSucceeded": 1,
            "routesFailed": 0,
            "jobsDiscovered": 1,
            "jobsChanged": 0,
            "jobsClosed": 0,
            "providerErrors": [],
        },
        status={
            "counts": {
                "currentJobs": 1,
                "openJobs": 1,
                "jobCapableRoutes": 1,
                "successfulJobSyncRuns": 1,
            }
        },
        coverage={"providers": []},
        include_quality_file=False,
    )
    assert report["status"] == "fail"
    assert any(
        b.startswith("public_sqlite_oversize:") for b in report["hardBlockers"]
    )


def test_public_sqlite_max_bytes_constant_is_positive() -> None:
    assert PUBLIC_SQLITE_MAX_BYTES >= 100 * 1024 * 1024
    assert PUBLIC_EXPORTS_MAX_BYTES >= PUBLIC_SQLITE_MAX_BYTES


def test_fail_closed_publish_recipes_require_db_or_allow_stale() -> None:
    justfile = (REPO_ROOT / "Justfile").read_text(encoding="utf-8")
    assert "kaggle-dataset-create db=" in justfile
    assert "kaggle-dataset-version message=" in justfile
    assert "allow_stale" in justfile
    assert "requires db=<path-to-clean-openoppsdb.sqlite>" in justfile
    assert "WARNING: allow_stale=1" in justfile
    # Rebuild path is present for non-stale publishes.
    create_idx = justfile.index("kaggle-dataset-create db=")
    version_idx = justfile.index("kaggle-dataset-version message=")
    create_block = justfile[create_idx : create_idx + 1200]
    version_block = justfile[version_idx : version_idx + 1600]
    assert "--data-db" in create_block
    assert "--data-db" in version_block
    assert "--stage-public-upload-dir" in create_block
    assert "--stage-public-upload-dir" in version_block


def test_web_search_index_requires_kaggle_sqlite_message() -> None:
    justfile = (REPO_ROOT / "Justfile").read_text(encoding="utf-8")
    assert "web-search-index:" in justfile
    assert "Missing kaggle/openoppsdb.sqlite" in justfile
    assert "sources.enabled" in justfile or "clean" in justfile.lower()
    # CI committed-only check remains separate.
    assert "web-search-artifacts-check:" in justfile


def test_ci_kaggle_bundle_smoke_does_not_require_just_binary() -> None:
    """Artifacts job must not invoke just (ubuntu runner has no just by default)."""
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "Kaggle clean-DB bundle smoke" in workflow
    assert "run: just kaggle-bundle-smoke" not in workflow
    # Inline smoke path uses the same generator entrypoints as Justfile.
    assert "admin db init" in workflow
    assert "--stage-public-upload-dir" in workflow
    assert "--data-db" in workflow


def test_dataset_description_documents_size_and_bounded_sync() -> None:
    description = gen._dataset_description()
    assert "jobs sync" in description
    assert "freshness-seconds" in description
