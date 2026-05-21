from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import polars as pl

from openopps.models import ExportFormat


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
                for key, value in record.items()
            }
        )
    return flattened


def _tabular_value(value: Any, *, neutralize_formulas: bool) -> Any:
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    if (
        neutralize_formulas
        and isinstance(value, str)
        and value.startswith(("=", "+", "-", "@", "\t", "\r"))
    ):
        return f"'{value}"
    return value


def export_records(records: Iterable[Any], output: Path, format_: ExportFormat) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    if format_ == ExportFormat.JSONL:
        count = 0
        with output.open("w", encoding="utf-8") as handle:
            for row in _jsonable_records(records):
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                count += 1
        return count
    rows = list(_jsonable_records(records))
    if format_ == ExportFormat.CSV:
        if not rows:
            output.write_text("", encoding="utf-8")
            return 0
        pl.DataFrame(_tabular_records(rows, neutralize_formulas=True)).write_csv(output)
        return len(rows)
    if format_ == ExportFormat.PARQUET:
        if not rows:
            pl.DataFrame().write_parquet(output)
            return 0
        pl.DataFrame(_tabular_records(rows)).write_parquet(output)
        return len(rows)
    raise ValueError(f"Unsupported export format: {format_}")
