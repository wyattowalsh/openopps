from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
import tempfile
from typing import Any

import polars as pl

from openopps.models import ExportFormat

SQLITE_METADATA_TABLE = "_openopps_export_metadata"


def canonical_json_dumps(value: Any) -> str:
    """Serialize JSON-compatible values with stable key ordering."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _jsonable_record(record: Any) -> dict[str, Any]:
    if hasattr(record, "model_dump"):
        return record.model_dump(mode="json")  # type: ignore[attr-defined]
    return dict(record)


def _jsonable_records(records: Iterable[Any]) -> Iterator[dict[str, Any]]:
    for record in records:
        yield _jsonable_record(record)


def _tabular_records(
    records: Iterable[dict[str, Any]], *, neutralize_formulas: bool = False
) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for record in records:
        flattened.append(
            {
                key: _tabular_value(value, neutralize_formulas=neutralize_formulas)
                for key, value in sorted(record.items())
            }
        )
    return flattened


def _tabular_value(value: Any, *, neutralize_formulas: bool) -> Any:
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if (
        neutralize_formulas
        and isinstance(value, str)
        and value.startswith(("=", "+", "-", "@", "\t", "\r"))
    ):
        return f"'{value}"
    return value


def export_records(
    records: Iterable[Any],
    output: Path,
    format_: ExportFormat,
    *,
    sqlite_table: str = "records",
    metadata: dict[str, Any] | None = None,
) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    with _atomic_output_path(
        output,
        remove_sqlite_sidecars=format_ == ExportFormat.SQLITE,
    ) as staged_output:
        if format_ == ExportFormat.JSONL:
            count = 0
            with staged_output.open("w", encoding="utf-8") as handle:
                for row in _jsonable_records(records):
                    handle.write(canonical_json_dumps(row) + "\n")
                    count += 1
            return count
        rows = list(_jsonable_records(records))
        if format_ == ExportFormat.CSV:
            if not rows:
                staged_output.write_text("", encoding="utf-8")
                return 0
            pl.DataFrame(_tabular_records(rows, neutralize_formulas=True)).write_csv(
                staged_output
            )
            return len(rows)
        if format_ == ExportFormat.PARQUET:
            if not rows:
                pl.DataFrame().write_parquet(staged_output)
                return 0
            pl.DataFrame(_tabular_records(rows)).write_parquet(staged_output)
            return len(rows)
        if format_ == ExportFormat.SQLITE:
            return _write_sqlite_export(
                rows,
                staged_output,
                table_name=sqlite_table,
                metadata=metadata or {},
            )
        raise ValueError(f"Unsupported export format: {format_}")


@contextmanager
def _atomic_output_path(
    output: Path,
    *,
    remove_sqlite_sidecars: bool,
) -> Iterator[Path]:
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{output.name}.",
        suffix=".tmp",
        dir=output.parent,
    )
    os.close(descriptor)
    staged_output = Path(raw_path)
    try:
        yield staged_output
        if remove_sqlite_sidecars:
            _require_no_sqlite_sidecars(output)
        os.replace(staged_output, output)
    finally:
        if staged_output.exists():
            staged_output.unlink()
        _remove_sqlite_sidecars(staged_output)


def _write_sqlite_export(
    rows: list[dict[str, Any]],
    output: Path,
    *,
    table_name: str,
    metadata: dict[str, Any],
) -> int:
    if output.exists():
        output.unlink()
    _remove_sqlite_sidecars(output)

    table_identifier = _sqlite_identifier(table_name)
    columns = _sqlite_columns(rows)
    with sqlite3.connect(output) as conn:
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute(
            f"CREATE TABLE {table_identifier} ("
            + ", ".join(
                f"{_sqlite_identifier(name)} {_sqlite_type(name, rows)}"
                for name in columns
            )
            + ")"
        )
        if rows:
            placeholders = ", ".join("?" for _ in columns)
            column_sql = ", ".join(_sqlite_identifier(name) for name in columns)
            conn.executemany(
                f"INSERT INTO {table_identifier} ({column_sql}) VALUES ({placeholders})",
                (
                    tuple(
                        _sqlite_value(row.get(column), neutralize_formulas=False)
                        for column in columns
                    )
                    for row in _tabular_records(rows)
                ),
            )
        conn.execute(
            f"""
            CREATE TABLE {_sqlite_identifier(SQLITE_METADATA_TABLE)} (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        metadata_rows = {
            "entity": table_name,
            "row_count": len(rows),
            "export_format": ExportFormat.SQLITE.value,
            **metadata,
        }
        conn.executemany(
            f"INSERT INTO {_sqlite_identifier(SQLITE_METADATA_TABLE)} (key, value) "
            "VALUES (?, ?)",
            (
                (key, json.dumps(value, ensure_ascii=False, sort_keys=True))
                for key, value in sorted(metadata_rows.items())
            ),
        )
        integrity = conn.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise sqlite3.DatabaseError(
                f"SQLite export integrity check failed: {integrity!r}"
            )
    return len(rows)


def _sqlite_columns(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["_empty"]
    columns: set[str] = set()
    for row in rows:
        columns.update(str(key) for key in row)
    return sorted(columns)


def _sqlite_type(column: str, rows: list[dict[str, Any]]) -> str:
    values = [
        row.get(column)
        for row in rows
        if row.get(column) is not None and row.get(column) != ""
    ]
    if not values:
        return "TEXT"
    if all(isinstance(value, bool) for value in values):
        return "INTEGER"
    if all(isinstance(value, int) and not isinstance(value, bool) for value in values):
        return "INTEGER"
    if all(
        isinstance(value, (int, float)) and not isinstance(value, bool)
        for value in values
    ):
        return "REAL"
    return "TEXT"


def _sqlite_value(value: Any, *, neutralize_formulas: bool) -> Any:
    value = _tabular_value(value, neutralize_formulas=neutralize_formulas)
    if isinstance(value, bool):
        return int(value)
    return value


def _sqlite_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _remove_sqlite_sidecars(path: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = path.with_name(f"{path.name}{suffix}")
        if sidecar.exists():
            sidecar.unlink()


def _require_no_sqlite_sidecars(path: Path) -> None:
    sidecars = [
        path.with_name(f"{path.name}{suffix}")
        for suffix in ("-wal", "-shm", "-journal")
    ]
    present = [sidecar.name for sidecar in sidecars if sidecar.exists()]
    if present:
        raise RuntimeError(
            "Refusing to replace a SQLite export with active or stale sidecars: "
            + ", ".join(present)
        )
