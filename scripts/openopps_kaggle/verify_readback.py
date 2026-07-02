from __future__ import annotations

import argparse
import json
from typing import Any

DATASET_ID = "wyattowalsh/openoppsdb"
TABLES = (
    "sources",
    "boards",
    "board_providers",
    "jobs",
    "job_versions",
    "job_version_locations",
    "job_version_skills",
    "job_version_skill_keywords",
    "job_version_bullets",
    "job_payload_snapshots",
    "job_sync_runs",
    "job_sync_observations",
    "openopps_tables",
    "openopps_columns",
)
EXPECTED_TABLES = len(TABLES)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Verify live OpenOppsDB readback through KaggleHub."
    )
    parser.add_argument("--dataset", default=DATASET_ID)
    parser.add_argument("--version", type=int, default=None)
    parser.add_argument("--skip-sqlite", action="store_true")
    args = parser.parse_args(argv)

    try:
        import kagglehub
        from kagglehub import KaggleDatasetAdapter
    except Exception as exc:  # pragma: no cover - dependency is injected by recipe.
        raise RuntimeError(
            "KaggleHub readback requires kagglehub. Run via "
            "`just kagglehub-live-readback`."
        ) from exc

    handle = args.dataset
    if args.version is not None:
        handle = f"{handle}/versions/{args.version}"

    checks: dict[str, Any] = {
        "dataset": handle,
        "files": {},
        "sqlite": {},
        "tableCounts": {},
    }
    table_counts: dict[str, dict[str, int]] = {table: {} for table in TABLES}

    file_checks = {
        **{
            f"exports/parquet/{table}.parquet": _table_expectation(table)
            for table in TABLES
        },
        **{f"exports/csv/{table}.csv": _table_expectation(table) for table in TABLES},
    }

    for path, expectation in file_checks.items():
        frame = kagglehub.dataset_load(KaggleDatasetAdapter.POLARS, handle, path)
        summary = _summarize_frame(frame)
        _assert_expectation(path, summary, expectation)
        checks["files"][path] = summary
        table_name = _table_name_from_export_path(path)
        surface = "parquet" if path.endswith(".parquet") else "csv"
        table_counts[table_name][surface] = summary["rows"]

    if not args.skip_sqlite:
        for table_name in TABLES:
            frame = kagglehub.dataset_load(
                KaggleDatasetAdapter.POLARS,
                handle,
                "openoppsdb.sqlite",
                sql_query=f'select count(*) as rows from "{table_name}"',
            )
            row_count = _single_value(frame, "rows")
            _assert_expectation(
                f"SQLite {table_name}",
                {"rows": row_count, "columns": 1},
                _table_expectation(table_name),
            )
            checks["sqlite"][table_name] = {"rows": row_count}
            table_counts[table_name]["sqlite"] = row_count

    for table_name, surface_counts in table_counts.items():
        if len(set(surface_counts.values())) > 1:
            raise AssertionError(
                f"{table_name} row counts differ across public surfaces: "
                f"{surface_counts}."
            )
        checks["tableCounts"][table_name] = surface_counts

    print(json.dumps(checks, indent=2, sort_keys=True))


def _collect_frame(frame: Any) -> Any:
    collect = getattr(frame, "collect", None)
    if callable(collect):
        return collect()
    return frame


def _summarize_frame(frame: Any) -> dict[str, int]:
    data = _collect_frame(frame)
    height = getattr(data, "height", None)
    width = getattr(data, "width", None)
    if height is None or width is None:
        shape = getattr(data, "shape", None)
        if shape is None:
            raise TypeError(f"Unsupported KaggleHub frame type: {type(data)!r}")
        height, width = shape
    return {"rows": int(height), "columns": int(width)}


def _table_expectation(table_name: str) -> dict[str, int]:
    if table_name == "openopps_tables":
        return {"rows": EXPECTED_TABLES}
    if table_name == "openopps_columns":
        return {"min_rows": EXPECTED_TABLES}
    return {"min_rows": 1}


def _table_name_from_export_path(path: str) -> str:
    return path.rsplit("/", 1)[-1].rsplit(".", 1)[0]


def _single_value(frame: Any, column: str) -> int:
    data = _collect_frame(frame)
    if getattr(data, "height", 0) != 1:
        raise AssertionError(f"Expected one-row SQL result for {column}.")
    return int(data[column][0])


def _assert_expectation(
    path: str, summary: dict[str, int], expectation: dict[str, int]
) -> None:
    if "rows" in expectation and summary["rows"] != expectation["rows"]:
        raise AssertionError(
            f"{path} expected {expectation['rows']} rows, found {summary['rows']}."
        )
    if "min_rows" in expectation and summary["rows"] < expectation["min_rows"]:
        raise AssertionError(
            f"{path} expected at least {expectation['min_rows']} rows, "
            f"found {summary['rows']}."
        )
    if summary["columns"] <= 0:
        raise AssertionError(f"{path} has no columns.")


if __name__ == "__main__":
    main()
