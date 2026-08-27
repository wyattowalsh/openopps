from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from openopps.discovery.api import encode_channel_replay_receipt
from openopps.discovery.enumerators import CapturedObservation, EnumeratorError
from openopps.discovery.models import BoundedReason, ChannelBudget, ChannelProfile
from openopps.discovery.official import OfficialSeed, enumerate_official_channel
from openopps.discovery.robots import admit_public_sitemap_locators, parse_robots


ROOT = Path(__file__).resolve().parents[4]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "discovery"
OBSERVED_AT = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
ORIGIN = "https://jobs.example.test:443"


def _budget(**updates: int) -> ChannelBudget:
    values = {
        "query_limit": 2,
        "request_limit": 10,
        "origin_limit": 3,
        "redirect_limit": 2,
        "page_limit": 4,
        "response_byte_limit": 50_000,
        "aggregate_byte_limit": 200_000,
        "candidate_limit": 20,
        "concurrency_limit": 2,
        "per_origin_concurrency_limit": 1,
        "retry_limit": 2,
        "parser_depth_limit": 16,
        "wall_clock_limit_ms": 5_000,
    }
    values.update(updates)
    return ChannelBudget(**values)


def _profile(
    *,
    seed_ids: tuple[str, ...] = ("official-catalog",),
    parser_ids: tuple[str, ...] = ("html-links-v1", "official-json-v1"),
    **budget: int,
) -> ChannelProfile:
    return ChannelProfile(
        channel="official",
        budget=_budget(**budget),
        seed_ids=seed_ids,
        allowed_origins=(ORIGIN,),
        allowed_query_keys=("page",),
        parser_ids=parser_ids,
    )


def _seed(**updates: object) -> OfficialSeed:
    values: dict[str, object] = {
        "seed_id": "official-catalog",
        "document_locator": "https://jobs.example.test/catalog.json",
        "parser_id": "official-json-v1",
        "robots_locator": "https://jobs.example.test/robots.txt",
        "sitemap_locator": "https://jobs.example.test/sitemap.xml",
    }
    values.update(updates)
    return OfficialSeed(**values)  # type: ignore[arg-type]


def test_official_seed_rejects_parser_ids_from_outside_the_trusted_profile() -> None:
    with pytest.raises(EnumeratorError, match="official_parser"):
        enumerate_official_channel(
            profile=_profile(parser_ids=("official-json-v1",)),
            seeds=(_seed(parser_id="html-links-v1"),),
            observations=(),
            observed_at=OBSERVED_AT,
        )


def test_official_catalog_fixture_enumerates_without_promotion_judgment() -> None:
    catalog = (FIXTURE_ROOT / "parser" / "official-catalog.json").read_bytes()
    robots = (FIXTURE_ROOT / "robots" / "allow.txt").read_bytes()
    sitemap = (FIXTURE_ROOT / "sitemap" / "urlset.xml").read_bytes()
    receipt = enumerate_official_channel(
        profile=_profile(),
        seeds=(_seed(),),
        observations=(
            CapturedObservation(
                locator="https://jobs.example.test/robots.txt",
                status_code=200,
                body=robots,
                media_type="text/plain",
            ),
            CapturedObservation(
                locator="https://jobs.example.test/sitemap.xml",
                status_code=200,
                body=sitemap,
                media_type="application/xml",
            ),
            CapturedObservation(
                locator="https://jobs.example.test/catalog.json",
                status_code=200,
                body=catalog,
                media_type="application/json",
            ),
        ),
        observed_at=OBSERVED_AT,
    )
    assert receipt.channel == "official"
    assert receipt.accounting.channel_state == "complete"
    assert receipt.accounting.unstarted == 0
    urls = {item.identity.canonical_url for item in receipt.occurrences}
    assert "https://jobs.example.test/catalog.json" in urls
    assert "https://jobs.example.test/companies/acme/jobs" in urls
    assert "https://jobs.example.test/companies/example/jobs" in urls
    assert all(item.channel == "official" for item in receipt.occurrences)
    dumped = encode_channel_replay_receipt(receipt)
    assert b"promotable" not in dumped
    assert b"eligibleForReview" not in dumped
    lastmod_claims = [
        claim
        for claim in receipt.provenance_claims
        if claim.field_name.startswith("lastmod:")
    ]
    assert any(claim.value == "2026-08-20T01:02:03Z" for claim in lastmod_claims)
    assert all(claim.accepted is False for claim in lastmod_claims)


def test_official_robots_unreachable_is_complete_disallow() -> None:
    receipt = enumerate_official_channel(
        profile=_profile(),
        seeds=(_seed(),),
        observations=(
            CapturedObservation(
                locator="https://jobs.example.test/robots.txt",
                transport_state="network_unreachable",
                status_code=None,
                body=None,
            ),
        ),
        observed_at=OBSERVED_AT,
    )
    assert receipt.operation_outcomes[
        receipt.operation_ids.index("official-catalog:robots")
    ] == ("blocked")
    assert receipt.operation_outcomes[
        receipt.operation_ids.index("official-catalog:document")
    ] == ("blocked")
    assert receipt.accounting.succeeded == 0


def test_official_security_rejected_robots_redirect_fails_closed() -> None:
    receipt = enumerate_official_channel(
        profile=_profile(),
        seeds=(_seed(sitemap_locator=None),),
        observations=(
            CapturedObservation(
                locator="https://jobs.example.test/robots.txt",
                transport_state="security_rejected_redirect",
                status_code=302,
                body=None,
            ),
        ),
        observed_at=OBSERVED_AT,
    )
    robots_index = receipt.operation_ids.index("official-catalog:robots")
    assert receipt.operation_outcomes[robots_index] == "blocked"
    assert receipt.request_receipts[0].reason_code is BoundedReason.REDIRECT_REJECTED


def test_official_raw_robots_sitemap_is_not_fetched_until_admitted() -> None:
    robots_body = (
        b"User-agent: *\nAllow: /\n"
        b"Sitemap: https://jobs.example.test/sitemap.xml\n"
        b"Sitemap: https://127.0.0.1/sitemap.xml\n"
    )
    policy = parse_robots(robots_body)
    admitted = admit_public_sitemap_locators(policy.sitemap_locators)
    assert [item.url for item in admitted] == ["https://jobs.example.test/sitemap.xml"]
    receipt = enumerate_official_channel(
        profile=_profile(),
        seeds=(_seed(sitemap_locator=None),),
        observations=(
            CapturedObservation(
                locator="https://jobs.example.test/robots.txt",
                status_code=200,
                body=robots_body,
                media_type="text/plain",
            ),
            CapturedObservation(
                locator="https://jobs.example.test/sitemap.xml",
                status_code=200,
                body=(FIXTURE_ROOT / "sitemap" / "urlset.xml").read_bytes(),
                media_type="application/xml",
            ),
            CapturedObservation(
                locator="https://jobs.example.test/catalog.json",
                status_code=200,
                body=(FIXTURE_ROOT / "parser" / "official-catalog.json").read_bytes(),
                media_type="application/json",
            ),
        ),
        observed_at=OBSERVED_AT,
    )
    locator_ids = {item.locator_id for item in receipt.request_receipts}
    assert "https://jobs.example.test/sitemap.xml" in locator_ids
    assert not any("127.0.0.1" in item for item in locator_ids)


def test_official_sitemap_index_is_one_hop_and_host_mismatch_is_dropped() -> None:
    index = (FIXTURE_ROOT / "sitemap" / "index.xml").read_bytes()
    child = (FIXTURE_ROOT / "sitemap" / "urlset.xml").read_bytes()
    mismatch = (FIXTURE_ROOT / "sitemap" / "host-mismatch.xml").read_bytes()
    receipt = enumerate_official_channel(
        profile=_profile(),
        seeds=(_seed(sitemap_locator="https://jobs.example.test/sitemap-index.xml"),),
        observations=(
            CapturedObservation(
                locator="https://jobs.example.test/robots.txt",
                status_code=404,
                body=None,
            ),
            CapturedObservation(
                locator="https://jobs.example.test/sitemap-index.xml",
                status_code=200,
                body=index,
                media_type="application/xml",
            ),
            CapturedObservation(
                locator="https://jobs.example.test/sitemap-jobs.xml",
                status_code=200,
                body=child,
                media_type="application/xml",
            ),
            CapturedObservation(
                locator="https://jobs.example.test/catalog.json",
                status_code=200,
                body=(FIXTURE_ROOT / "parser" / "official-catalog.json").read_bytes(),
                media_type="application/json",
            ),
            CapturedObservation(
                locator="https://other.example.test/companies/acme/jobs",
                status_code=200,
                body=mismatch,
                media_type="application/xml",
            ),
        ),
        observed_at=OBSERVED_AT,
    )
    urls = {item.identity.canonical_url for item in receipt.occurrences}
    assert "https://jobs.example.test/companies/acme/jobs" in urls
    assert not any("other.example.test" in url for url in urls)


def test_official_dtd_sitemap_is_parser_rejected() -> None:
    receipt = enumerate_official_channel(
        profile=_profile(),
        seeds=(_seed(sitemap_locator="https://jobs.example.test/dtd.xml"),),
        observations=(
            CapturedObservation(
                locator="https://jobs.example.test/robots.txt",
                status_code=404,
                body=None,
            ),
            CapturedObservation(
                locator="https://jobs.example.test/dtd.xml",
                status_code=200,
                body=(FIXTURE_ROOT / "parser" / "dtd.xml").read_bytes(),
                media_type="application/xml",
            ),
            CapturedObservation(
                locator="https://jobs.example.test/catalog.json",
                status_code=200,
                body=(FIXTURE_ROOT / "parser" / "official-catalog.json").read_bytes(),
                media_type="application/json",
            ),
        ),
        observed_at=OBSERVED_AT,
    )
    sitemap_index = receipt.operation_ids.index("official-catalog:sitemap")
    assert receipt.operation_outcomes[sitemap_index] == "failed"
    assert any(
        item.reason_code is BoundedReason.PARSER_REJECTED
        for item in receipt.request_receipts
    )


def test_official_conditional_not_modified_and_budget_exhaustion() -> None:
    catalog = (FIXTURE_ROOT / "parser" / "official-catalog.json").read_bytes()
    complete = enumerate_official_channel(
        profile=_profile(request_limit=8),
        seeds=(_seed(sitemap_locator=None),),
        observations=(
            CapturedObservation(
                locator="https://jobs.example.test/robots.txt",
                transport_state="verified_cache",
                status_code=200,
                body=(FIXTURE_ROOT / "robots" / "allow.txt").read_bytes(),
                media_type="text/plain",
                etag='W/"fixture-etag-v1"',
                last_modified="Wed, 20 Aug 2026 10:00:00 GMT",
                cached_age_seconds=60,
            ),
            CapturedObservation(
                locator="https://jobs.example.test/catalog.json",
                transport_state="not_modified",
                status_code=304,
                body=catalog,
                media_type="application/json",
                etag='W/"fixture-etag-v1"',
                last_modified="Wed, 20 Aug 2026 10:00:00 GMT",
            ),
        ),
        observed_at=OBSERVED_AT,
    )
    assert complete.accounting.channel_state == "complete"
    assert any(item.response_status == 304 for item in complete.request_receipts)

    exhausted = enumerate_official_channel(
        profile=_profile(request_limit=1, concurrency_limit=1),
        seeds=(_seed(sitemap_locator=None),),
        observations=(
            CapturedObservation(
                locator="https://jobs.example.test/robots.txt",
                status_code=200,
                body=(FIXTURE_ROOT / "robots" / "allow.txt").read_bytes(),
                media_type="text/plain",
            ),
            CapturedObservation(
                locator="https://jobs.example.test/catalog.json",
                status_code=200,
                body=catalog,
                media_type="application/json",
            ),
        ),
        observed_at=OBSERVED_AT,
    )
    assert exhausted.accounting.channel_state == "partial"
    assert exhausted.accounting.unstarted >= 1
    assert exhausted.accounting.unfinished_operation_ids
    assert exhausted.accounting.request_consumed == 1
    assert (
        exhausted.accounting.request_consumed + exhausted.accounting.request_remaining
        == exhausted.accounting.request_limit
    )


def test_official_html_parser_fixture_extracts_links() -> None:
    receipt = enumerate_official_channel(
        profile=_profile(parser_ids=("html-links-v1",)),
        seeds=(
            _seed(
                parser_id="html-links-v1",
                document_locator="https://jobs.example.test/companies/acme",
                sitemap_locator=None,
            ),
        ),
        observations=(
            CapturedObservation(
                locator="https://jobs.example.test/robots.txt",
                status_code=404,
                body=None,
            ),
            CapturedObservation(
                locator="https://jobs.example.test/companies/acme",
                status_code=200,
                body=(FIXTURE_ROOT / "parser" / "provider-page.html").read_bytes(),
                media_type="text/html",
            ),
        ),
        observed_at=OBSERVED_AT,
    )
    urls = {item.identity.canonical_url for item in receipt.occurrences}
    assert "https://jobs.example.test/companies/acme/jobs" in urls


def test_official_replay_is_byte_identical() -> None:
    observations = (
        CapturedObservation(
            locator="https://jobs.example.test/robots.txt",
            status_code=404,
            body=None,
        ),
        CapturedObservation(
            locator="https://jobs.example.test/catalog.json",
            status_code=200,
            body=(FIXTURE_ROOT / "parser" / "official-catalog.json").read_bytes(),
            media_type="application/json",
        ),
    )
    first = enumerate_official_channel(
        profile=_profile(),
        seeds=(_seed(sitemap_locator=None),),
        observations=observations,
        observed_at=OBSERVED_AT,
    )
    second = enumerate_official_channel(
        profile=_profile(),
        seeds=(_seed(sitemap_locator=None),),
        observations=observations,
        observed_at=OBSERVED_AT,
    )
    assert encode_channel_replay_receipt(first) == encode_channel_replay_receipt(second)
