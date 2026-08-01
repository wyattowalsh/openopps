"""Resolve packaged source configuration against persisted runtime state."""

from __future__ import annotations

from collections.abc import Sequence

from openopps.models import SourceRecord


def resolve_effective_source(
    catalog_source: SourceRecord | None,
    stored_source: SourceRecord | None,
) -> SourceRecord | None:
    if catalog_source is None:
        return stored_source
    if stored_source is None:
        return catalog_source
    if (
        stored_source.url != catalog_source.url
        or stored_source.provider_id != catalog_source.provider_id
    ):
        return stored_source

    raw_metadata = stored_source.raw_metadata | catalog_source.raw_metadata
    configuration_changed = raw_metadata != stored_source.raw_metadata
    return catalog_source.model_copy(
        update={
            "version": stored_source.version,
            "raw_metadata": raw_metadata,
            "synced_at": None if configuration_changed else stored_source.synced_at,
        }
    )


def resolve_effective_sources(
    catalog_sources: Sequence[SourceRecord],
    stored_sources: Sequence[SourceRecord],
) -> list[SourceRecord]:
    stored_by_key = {source.key: source for source in stored_sources}
    catalog_keys: set[str] = set()
    resolved: list[SourceRecord] = []
    for catalog_source in catalog_sources:
        catalog_keys.add(catalog_source.key)
        source = resolve_effective_source(
            catalog_source, stored_by_key.get(catalog_source.key)
        )
        if source is not None:
            resolved.append(source)
    resolved.extend(
        source for source in stored_sources if source.key not in catalog_keys
    )
    return resolved
