from datetime import timedelta

from openopps.models import SourceRecord, utc_now
from openopps.source_resolution import (
    resolve_effective_source,
    resolve_effective_sources,
)


def test_catalog_metadata_wins_without_losing_persisted_runtime_state() -> None:
    synced_at = utc_now() - timedelta(hours=1)
    stored = SourceRecord(
        key="portfolio",
        url="https://consider.com/boards/co/allspice.io",
        provider_id="consider",
        version={"cursor": "next"},
        raw_metadata={"board": "allspiceio", "lastPage": {"page": 2}},
        synced_at=synced_at,
    )
    catalog = stored.model_copy(
        update={"version": {}, "raw_metadata": {"board": "allspice.io"}}
    )

    resolved = resolve_effective_source(catalog, stored)

    assert resolved is not None
    assert resolved.raw_metadata == {
        "board": "allspice.io",
        "lastPage": {"page": 2},
    }
    assert resolved.version == {"cursor": "next"}
    assert resolved.synced_at is None


def test_unchanged_catalog_configuration_preserves_sync_freshness() -> None:
    synced_at = utc_now() - timedelta(hours=1)
    stored = SourceRecord(
        key="portfolio",
        url="https://consider.com/boards/co/allspice.io",
        provider_id="consider",
        version={"cursor": "next"},
        raw_metadata={"board": "allspice.io", "lastPage": {"page": 2}},
        synced_at=synced_at,
    )
    catalog = stored.model_copy(
        update={"version": {}, "raw_metadata": {"board": "allspice.io"}}
    )

    resolved = resolve_effective_source(catalog, stored)

    assert resolved is not None
    assert resolved.synced_at == synced_at
    assert resolved.version == stored.version
    assert resolved.raw_metadata == stored.raw_metadata


def test_different_persisted_identity_remains_an_explicit_local_override() -> None:
    catalog = SourceRecord(
        key="portfolio",
        url="https://consider.com/boards/co/company",
        provider_id="consider",
        raw_metadata={"board": "company"},
    )
    stored = SourceRecord(
        key="portfolio",
        url="https://custom.example/companies",
        provider_id="manual",
        raw_metadata={"owner": "local"},
    )

    assert resolve_effective_source(catalog, stored) is stored


def test_effective_source_union_keeps_catalog_order_and_custom_sources() -> None:
    first = SourceRecord(key="first", url="manual://first", provider_id="manual")
    second = SourceRecord(key="second", url="manual://second", provider_id="manual")
    custom = SourceRecord(key="custom", url="manual://custom", provider_id="manual")

    resolved = resolve_effective_sources([first, second], [second, custom])

    assert [source.key for source in resolved] == ["first", "second", "custom"]
