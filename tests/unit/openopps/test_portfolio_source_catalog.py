from __future__ import annotations

import json
import re
from importlib import resources
from urllib.parse import urlparse

from openopps.models import SourceRecord, validate_public_https_url
from openopps.providers.sources import BOARD_SOURCE_ADAPTERS, BOARD_SOURCE_CATALOG
from openopps.source_scope import validate_packaged_source_catalog
from openopps.providers.sources.source_utils import (
    load_packaged_portfolio_source_records,
    portfolio_source_catalog_fingerprint,
    source_record_to_catalog_entry,
)

_PACKAGED_CATALOG_RESOURCE = "portfolio_source_catalog.json"
_DEAD_DIRECT_ATS_KEYS = {"1776", "1848ventures", "54collective", "777partners"}
_CONSIDER_STAGING_SUFFIX = ".board.staging.consider.com"


def _exact_consider_board_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    path_parts = [part for part in parsed.path.split("/") if part]
    if (
        hostname == "consider.com"
        and len(path_parts) >= 3
        and path_parts[:2] in (["boards", "co"], ["boards", "vc"])
    ):
        return path_parts[2]
    if hostname.endswith(_CONSIDER_STAGING_SUFFIX):
        return hostname[: -len(_CONSIDER_STAGING_SUFFIX)]
    return None


def test_packaged_portfolio_catalog_json_integrity() -> None:
    package = "openopps.providers.sources.data"
    raw = (
        resources.files(package)
        .joinpath(_PACKAGED_CATALOG_RESOURCE)
        .read_text(encoding="utf-8")
    )
    payload = json.loads(raw)
    entries = payload["entries"]
    assert isinstance(payload["version"], int) and payload["version"] >= 2
    assert payload["count"] == len(entries)
    assert payload["fingerprint"] == portfolio_source_catalog_fingerprint(entries)
    records = load_packaged_portfolio_source_records()
    assert len(records) == len(entries)
    loaded_entries = [source_record_to_catalog_entry(record) for record in records]
    assert (
        portfolio_source_catalog_fingerprint(loaded_entries) == payload["fingerprint"]
    )


def test_portfolio_fingerprint_includes_provider_and_metadata() -> None:
    base = {
        "key": "fp-probe",
        "url": "https://example.com/portfolio",
        "provider_id": "public_page",
        "version": {},
        "raw_metadata": {"providerType": "venture_firm"},
    }
    left = portfolio_source_catalog_fingerprint([base])
    right = portfolio_source_catalog_fingerprint(
        [{**base, "raw_metadata": {"providerType": "other"}}]
    )
    assert left != right
    provider_changed = portfolio_source_catalog_fingerprint(
        [{**base, "provider_id": "getro"}]
    )
    assert left != provider_changed


def test_packaged_portfolio_catalog_records_are_valid_source_records() -> None:
    for record in load_packaged_portfolio_source_records():
        assert isinstance(record, SourceRecord)
        assert record.key
        assert record.url
        assert record.provider_id


def test_special_module_uses_packaged_portfolio_catalog() -> None:
    packaged_keys = {record.key for record in load_packaged_portfolio_source_records()}
    for key in packaged_keys:
        assert key in BOARD_SOURCE_CATALOG
    twobear = BOARD_SOURCE_CATALOG.get("twobearcapital")
    assert twobear is not None
    assert twobear.provider_id == "public_page"


def test_packaged_portfolio_catalog_keys_and_urls_are_unique() -> None:
    records = load_packaged_portfolio_source_records()
    keys = [record.key for record in records]
    urls = [record.url for record in records]
    assert len(keys) == len(set(keys))
    assert len(urls) == len(set(urls))


def test_packaged_consider_metadata_preserves_exact_url_board_tokens() -> None:
    checked = 0
    for record in load_packaged_portfolio_source_records():
        if record.provider_id != "consider":
            continue
        expected_board = _exact_consider_board_from_url(record.url)
        if expected_board is None:
            continue
        checked += 1
        assert record.raw_metadata.get("board") == expected_board, record.key
    assert checked == 1023


def test_packaged_catalog_excludes_dead_direct_ats_sources() -> None:
    packaged_keys = {record.key for record in load_packaged_portfolio_source_records()}
    assert packaged_keys.isdisjoint(_DEAD_DIRECT_ATS_KEYS)
    assert set(BOARD_SOURCE_CATALOG).isdisjoint(_DEAD_DIRECT_ATS_KEYS)


def test_named_consider_sources_do_not_duplicate_packaged_sources() -> None:
    from openopps.providers.sources import consider as consider_mod

    packaged_keys = {record.key for record in load_packaged_portfolio_source_records()}
    named_keys = {record.key for record in consider_mod.SOURCE_RECORDS}
    assert packaged_keys.isdisjoint(named_keys)


def test_board_source_catalog_passes_scope_and_https_invariants() -> None:
    validate_packaged_source_catalog(BOARD_SOURCE_CATALOG)
    keys = list(BOARD_SOURCE_CATALOG)
    assert len(keys) == len(set(keys))
    for key, source in BOARD_SOURCE_CATALOG.items():
        assert source.key == key
        assert source.provider_id in BOARD_SOURCE_ADAPTERS, key
        assert "enabled" not in source.model_dump(mode="json")
        assert source.url.startswith(("https://", "http://", "manual://")), key
        assert not re.search(r"\s", source.url), key
        if source.url.startswith("manual://"):
            continue
        parsed = urlparse(source.url)
        assert parsed.hostname, key


def test_packaged_portfolio_catalog_public_page_urls_are_https() -> None:
    """Packaged portfolio records should use public HTTPS URLs for scrapable pages."""
    invalid: list[str] = []
    for record in load_packaged_portfolio_source_records():
        if record.provider_id != "public_page":
            continue
        if not record.url.startswith("https://"):
            invalid.append(record.key)
            continue
        try:
            validate_public_https_url(record.url)
        except ValueError:
            invalid.append(record.key)
    assert invalid == []


def test_getro_and_consider_catalog_metadata_invariants() -> None:
    """Named getro/consider modules should retain metadata; portfolio getro may be URL-only."""
    from openopps.providers.sources import getro as getro_mod
    from openopps.providers.sources import consider as consider_mod

    for record in getro_mod.SOURCE_RECORDS:
        if record.provider_id != "getro":
            continue
        assert str(record.raw_metadata.get("collectionId") or "").strip(), record.key
        parsed = urlparse(record.url)
        assert parsed.scheme == "https" and parsed.hostname, record.key

    for record in consider_mod.SOURCE_RECORDS:
        if record.provider_id != "consider":
            continue
        assert str(record.raw_metadata.get("board") or "").strip(), record.key
        parsed = urlparse(record.url)
        assert parsed.scheme == "https" and parsed.hostname, record.key


def test_requested_consider_sources_preserve_board_routes() -> None:
    expected = {
        "blueprinttalentgroup": "blue-print-talent-group",
        "kinvie": "kinvie",
        "midoceanpartners": "midocean-partners",
        "pretium": "pretium",
        "quantonation": "quantonation",
        "singaporeglobalnetwork": "singapore-global-network",
    }
    for key, board_slug in expected.items():
        record = BOARD_SOURCE_CATALOG[key]
        assert record.provider_id == "consider"
        assert record.raw_metadata == {"board": board_slug}
        if urlparse(record.url).hostname == "consider.com":
            assert f"/boards/vc/{board_slug}/" in record.url
        else:
            assert key == "quantonation"
            assert record.url == "https://jobs.quantonation.com/companies"


def test_packaged_direct_ats_sources_have_route_metadata() -> None:
    provider_hosts = {
        "ashby": "jobs.ashbyhq.com",
        "greenhouse_source": "job-boards.greenhouse.io",
        "lever_source": "jobs.lever.co",
        "workable_source": "apply.workable.com",
    }
    direct_sources = [
        record
        for record in load_packaged_portfolio_source_records()
        if record.provider_id in provider_hosts
    ]
    assert direct_sources
    expected_taxonomy = {
        "providerType": "job_board",
        "coverageMode": "portfolio_jobs",
        "accessType": "public_json_api",
        "licenseStatus": "public_attribution_required",
        "refreshCadence": "periodic",
        "sourceCategory": "startup_ecosystem",
    }
    for record in direct_sources:
        assert str(record.raw_metadata.get("token") or "").strip(), record.key
        assert str(record.raw_metadata.get("label") or "").strip(), record.key
        for field, expected in expected_taxonomy.items():
            assert record.raw_metadata.get(field) == expected, record.key
        assert str(record.raw_metadata.get("sourceAttribution") or "").strip(), (
            record.key
        )
        assert str(record.raw_metadata.get("inclusionReason") or "").strip(), record.key
        assert urlparse(record.url).hostname == provider_hosts[record.provider_id]


def test_board_source_catalog_special_adapter_entries() -> None:
    southparkcommons = BOARD_SOURCE_CATALOG["southparkcommons"]
    assert southparkcommons.provider_id == "southparkcommons"
    assert southparkcommons.url == "https://www.southparkcommons.com/jobs"

    workable1871 = BOARD_SOURCE_CATALOG["1871"]
    assert workable1871.provider_id == "workable_source"
    assert workable1871.raw_metadata.get("token") == "1871"

    twobear = BOARD_SOURCE_CATALOG["twobearcapital"]
    assert twobear.provider_id == "public_page"
    assert twobear.raw_metadata.get("label") == "Two Bear Capital"

    bioct = BOARD_SOURCE_CATALOG["bioct"]
    assert bioct.provider_id == "public_page"
    assert bioct.raw_metadata.get("observedStatus") == "cloudflare_challenge"
