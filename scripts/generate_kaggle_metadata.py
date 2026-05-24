from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sqlite3
from typing import Any

import polars as pl

from openopps.kaggle_metadata import (
    KAGGLE_EXPORT_CSV_DIR,
    KAGGLE_EXPORT_PARQUET_DIR,
    KAGGLE_NOTEBOOK_FILE,
    KAGGLE_SQLITE_FILE,
    KAGGLE_SQLITE_TABLES,
    build_kaggle_datapackage,
    build_kaggle_dataset_metadata,
    build_kaggle_kernel_metadata,
    build_kaggle_update_notebook,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Kaggle dataset metadata from OpenOpps package models."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "kaggle",
        help="Directory to receive Kaggle dataset and notebook metadata.",
    )
    parser.add_argument(
        "--data-db",
        type=Path,
        default=None,
        help="Existing SQLite DB to copy as openopps.sqlite and export alongside table files.",
    )
    args = parser.parse_args()

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.data_db is not None:
        _write_data_artifacts(output_dir, args.data_db)
    _write_json(output_dir / "dataset-metadata.json", build_kaggle_dataset_metadata())
    _write_json(output_dir / "datapackage.json", build_kaggle_datapackage())
    notebooks_dir = output_dir / "notebooks"
    notebooks_dir.mkdir(parents=True, exist_ok=True)
    _write_json(notebooks_dir / "kernel-metadata.json", build_kaggle_kernel_metadata())
    _write_json(
        notebooks_dir / KAGGLE_NOTEBOOK_FILE,
        build_kaggle_update_notebook(),
    )


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_data_artifacts(output_dir: Path, data_db: Path) -> None:
    source_db = data_db.expanduser().resolve()
    if not source_db.exists():
        raise FileNotFoundError(f"SQLite database does not exist: {source_db}")
    target_db = output_dir / KAGGLE_SQLITE_FILE
    _clean_data_artifacts(output_dir, preserve=source_db)
    _checkpoint_sqlite(source_db)
    if source_db != target_db.resolve():
        shutil.copy2(source_db, target_db)
        if source_db.parent == output_dir.resolve():
            source_db.unlink()
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


def _write_full_table_exports(output_dir: Path, db_path: Path) -> None:
    csv_dir = output_dir / KAGGLE_EXPORT_CSV_DIR
    parquet_dir = output_dir / KAGGLE_EXPORT_PARQUET_DIR
    csv_dir.mkdir(parents=True, exist_ok=True)
    parquet_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        for table in KAGGLE_SQLITE_TABLES:
            rows = [dict(row) for row in conn.execute(f'SELECT * FROM "{table.name}"')]
            frame = pl.DataFrame(
                rows or {field: [] for field in table.model.model_fields}
            )
            frame.write_csv(csv_dir / f"{table.name}.csv")
            frame.write_parquet(parquet_dir / f"{table.name}.parquet")


def _checkpoint_sqlite(path: Path) -> None:
    if not path.exists():
        return
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


if __name__ == "__main__":
    main()
