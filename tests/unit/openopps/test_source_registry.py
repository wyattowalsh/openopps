from __future__ import annotations

import importlib
import pkgutil
from collections import defaultdict
from types import ModuleType

from openopps.models import SourceRecord
from openopps.providers import sources as sources_pkg
from openopps.providers.sources import BOARD_SOURCE_CATALOG, BOARD_SOURCE_RECORDS


def test_source_record_keys_have_single_module_owner() -> None:
    records_by_key: dict[str, list[tuple[str, SourceRecord]]] = defaultdict(list)
    for module in _source_modules():
        for source in getattr(module, "SOURCE_RECORDS", ()):
            if isinstance(source, SourceRecord):
                records_by_key[source.key].append((module.__name__, source))

    duplicates = {
        key: [
            {
                "module": module_name,
                "url": source.url,
                "provider_id": source.provider_id,
            }
            for module_name, source in records
        ]
        for key, records in records_by_key.items()
        if len(records) > 1
    }

    assert duplicates == {}


def test_source_catalog_matches_unique_module_records() -> None:
    module_records = [
        source
        for module in _source_modules()
        for source in getattr(module, "SOURCE_RECORDS", ())
        if isinstance(source, SourceRecord)
    ]
    module_keys = {source.key for source in module_records}

    assert len(module_records) == len(module_keys)
    assert len(BOARD_SOURCE_RECORDS) == len(module_keys)
    assert set(BOARD_SOURCE_CATALOG) == module_keys


def _source_modules() -> tuple[ModuleType, ...]:
    return tuple(
        importlib.import_module(module_info.name)
        for module_info in pkgutil.iter_modules(
            sources_pkg.__path__, f"{sources_pkg.__name__}."
        )
        if not module_info.ispkg
    )
