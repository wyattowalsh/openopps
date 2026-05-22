from __future__ import annotations

import copy

from openopps.docs_data import build_docs_data


def test_build_docs_data_is_deterministic() -> None:
    first = build_docs_data()
    second = build_docs_data()

    assert first == second


def test_build_docs_data_matches_provider_counts() -> None:
    data = copy.deepcopy(build_docs_data())

    assert data["stats"] == {
        "sourceRecordCount": len(data["sourceCatalog"]),
        "sourceAdapterCount": len(data["sourceAdapters"]),
        "jobProviderCount": len(data["jobProviders"]),
        "exportFormatCount": len(data["exportFormats"]),
    }
    assert data["jobProviders"]
    assert data["sourceCatalog"] == sorted(
        data["sourceCatalog"], key=lambda source: source["key"]
    )
