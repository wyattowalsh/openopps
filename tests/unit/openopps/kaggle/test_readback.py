from __future__ import annotations

import json
import re
import sys
import types

import pytest

import openopps_kaggle.verify_readback as readback


class FakeFrame:
    def __init__(
        self, *, height: int, columns: int = 3, value: int | None = None
    ) -> None:
        self.height = height
        self.width = columns
        self._rows = [height if value is None else value]

    def __getitem__(self, name: str) -> list[int]:
        assert name == "rows"
        return self._rows


def test_kagglehub_readback_checks_all_public_surfaces(monkeypatch, capsys) -> None:
    calls: list[tuple[str, str | None]] = []
    counts = _counts()

    def dataset_load(adapter, handle: str, path: str, *, sql_query: str | None = None):
        del adapter, handle
        calls.append((path, sql_query))
        if sql_query is not None:
            table = _table_from_sql(sql_query)
            return FakeFrame(height=1, columns=1, value=counts[table])
        return FakeFrame(height=counts[_table_from_path(path)])

    _install_fake_kagglehub(monkeypatch, dataset_load)

    readback.main([])

    output = json.loads(capsys.readouterr().out)
    assert output["dataset"] == readback.DATASET_ID
    assert set(output["tableCounts"]) == set(readback.TABLES)
    assert len([call for call in calls if call[1] is None]) == len(readback.TABLES) * 2
    assert len([call for call in calls if call[1] is not None]) == len(readback.TABLES)


def test_kagglehub_readback_blocks_surface_row_count_drift(monkeypatch) -> None:
    counts = _counts()

    def dataset_load(adapter, handle: str, path: str, *, sql_query: str | None = None):
        del adapter, handle
        if sql_query is not None:
            return FakeFrame(
                height=1,
                columns=1,
                value=counts[_table_from_sql(sql_query)],
            )
        table = _table_from_path(path)
        rows = 2 if path == "exports/csv/sources.csv" else counts[table]
        return FakeFrame(height=rows)

    _install_fake_kagglehub(monkeypatch, dataset_load)

    with pytest.raises(AssertionError, match="sources row counts differ"):
        readback.main([])


def _counts() -> dict[str, int]:
    return {
        table: (
            readback.EXPECTED_TABLES
            if table == "openopps_tables"
            else len(readback.TABLES) * 10
            if table == "openopps_columns"
            else 1
        )
        for table in readback.TABLES
    }


def _install_fake_kagglehub(monkeypatch, dataset_load) -> None:
    fake = types.ModuleType("kagglehub")
    fake.dataset_load = dataset_load
    fake.KaggleDatasetAdapter = types.SimpleNamespace(POLARS="polars")
    monkeypatch.setitem(sys.modules, "kagglehub", fake)


def _table_from_path(path: str) -> str:
    return path.rsplit("/", 1)[-1].rsplit(".", 1)[0]


def _table_from_sql(sql: str) -> str:
    match = re.search(r'from "([^"]+)"', sql, re.IGNORECASE)
    assert match is not None
    return match.group(1)
