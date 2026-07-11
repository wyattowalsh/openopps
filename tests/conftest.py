from __future__ import annotations

from pathlib import Path

import pytest

from _fixtures.store import seeded_coverage_store


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        path_parts = Path(str(item.fspath)).parts
        if "unit" in path_parts:
            item.add_marker(pytest.mark.unit)
        elif "integration" in path_parts:
            item.add_marker(pytest.mark.integration)
        elif "smoke" in path_parts:
            item.add_marker(pytest.mark.smoke)
        elif "e2e" in path_parts:
            item.add_marker(pytest.mark.e2e)


@pytest.fixture
def seeded_store(tmp_path: Path):
    """Coverage-oriented ledger with sources, routes, and jobs."""
    return seeded_coverage_store(tmp_path)
