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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify live OpenOppsDB readback through KaggleHub."
    )
    parser.add_argument("--dataset", default=DATASET_ID)
    parser.add_argument("--version", type=int, default=None)
    parser.add_argument("--skip-sqlite", action="store_true")
    args = parser.parse_args()

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

    checks: dict[str, Any] = {"dataset": handle, "files": {}, "sqlite": {}}

    parquet_checks = {
        f"exports/parquet/{table}.parquet": {"min_rows": 1} for table in TABLES
    }
    parquet_checks["exports/parquet/openopps_tables.parquet"] = {
        "rows": EXPECTED_TABLES
    }
    parquet_checks["exports/parquet/openopps_columns.parquet"] = {
        "min_rows": EXPECTED_TABLES
    }
    csv_checks = {
        "exports/csv/openopps_tables.csv": {"rows": EXPECTED_TABLES},
        "exports/csv/openopps_columns.csv": {"min_rows": 1},
        "exports/csv/sources.csv": {"min_rows": 1},
    }

    for path, expectation in {**parquet_checks, **csv_checks}.items():
        frame = kagglehub.dataset_load(KaggleDatasetAdapter.POLARS, handle, path)
        summary = _summarize_frame(frame)
        _assert_expectation(path, summary, expectation)
        checks["files"][path] = summary

    if not args.skip_sqlite:
        sqlite_queries = {
            "jobs": "select count(*) as rows from jobs",
            "job_versions": "select count(*) as rows from job_versions",
            "job_sync_runs": "select count(*) as rows from job_sync_runs",
            "openopps_tables": "select count(*) as rows from openopps_tables",
            "openopps_columns": "select count(*) as rows from openopps_columns",
        }
        for table_name, query in sqlite_queries.items():
            frame = kagglehub.dataset_load(
                KaggleDatasetAdapter.POLARS,
                handle,
                "openoppsdb.sqlite",
                sql_query=query,
            )
            row_count = _single_value(frame, "rows")
            if table_name == "openopps_tables":
                if row_count != EXPECTED_TABLES:
                    raise AssertionError(
                        f"SQLite {table_name} expected {EXPECTED_TABLES} rows, "
                        f"found {row_count}."
                    )
            elif row_count <= 0:
                raise AssertionError(f"SQLite {table_name} is empty.")
            checks["sqlite"][table_name] = {"rows": row_count}

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
