from __future__ import annotations

from datetime import UTC, datetime
import json

from openopps.discovery.api import encode_channel_replay_receipt
from openopps.discovery.diagnostics import render_metric_attributes
from openopps.discovery.enumerators import CapturedObservation
from openopps.discovery.models import (
    BoundedReason,
    ChannelBudget,
    ChannelProfile,
    DiscoveryChannel,
)
from openopps.discovery.search import (
    SearchApiProfile,
    SearchQuerySet,
    enumerate_search_channel,
    search_metric_attributes,
)


OBSERVED_AT = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
API = "https://api.example.test/search"
ORIGIN = "https://api.example.test:443"
QUERIES = ("explicit board catalog", "public dataset registry")


def _profile(n: int = 2, **budget: int) -> ChannelProfile:
    values = {
        "query_limit": n,
        "request_limit": 12,
        "origin_limit": 3,
        "redirect_limit": 2,
        "page_limit": 3,
        "response_byte_limit": 8_000,
        "aggregate_byte_limit": 40_000,
        "candidate_limit": 20,
        "concurrency_limit": 2,
        "per_origin_concurrency_limit": 1,
        "retry_limit": 2,
        "parser_depth_limit": 8,
        "wall_clock_limit_ms": 5_000,
    }
    values.update(budget)
    return ChannelProfile(
        channel="search",
        budget=ChannelBudget(**values),
        seed_ids=tuple(f"query-{index:04d}" for index in range(n)),
        allowed_origins=(ORIGIN,),
        allowed_query_keys=("page", "q"),
        parser_ids=("search-api-v1",),
    )


def _page(
    *, next_page: str | None = None, extra: dict[str, object] | None = None
) -> bytes:
    payload: dict[str, object] = {
        "relatedQueries": ["do-not-expand-this"],
        "results": [
            {"url": "https://jobs.example.test/catalog.json"},
            {"url": "https://jobs.example.test/catalog.json"},
            {"url": "https://jobs.example.test/boards"},
        ],
    }
    if next_page is not None:
        payload["next"] = next_page
    if extra:
        payload.update(extra)
    return (json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n").encode()


def test_search_preserves_query_set_digest_and_excludes_raw_query_from_metrics() -> (
    None
):
    query_set = SearchQuerySet(queries=QUERIES)
    receipt = enumerate_search_channel(
        profile=_profile(),
        query_set=query_set,
        api=SearchApiProfile(profile_id="public-search", locator=API),
        observations=(
            CapturedObservation(
                locator=API,
                status_code=200,
                body=_page(),
                media_type="application/json",
            ),
        ),
        observed_at=OBSERVED_AT,
    )
    assert receipt.accounting.planned_operations == 2
    claims = [
        claim.value
        for claim in receipt.provenance_claims
        if claim.field_name == "querySetSha256"
    ]
    assert query_set.digest in claims
    attributes = search_metric_attributes(receipt, query_set=query_set)
    rendered = " ".join(str(value) for value in attributes.values())
    for query in QUERIES:
        assert query not in rendered
    assert attributes["openopps.discovery.identity.sha256"] == query_set.digest
    dumped = encode_channel_replay_receipt(receipt).decode("utf-8")
    assert (
        "do-not-expand-this" not in dumped
        or dumped.count("jobs.example.test/catalog.json") >= 1
    )
    urls = [item.identity.canonical_url for item in receipt.occurrences]
    assert urls.count("https://jobs.example.test/catalog.json") == 4
    assert "https://jobs.example.test/boards" in urls
    assert len(set(urls)) == 2


def test_search_does_not_expand_related_queries_and_paginates_within_budget() -> None:
    query_set = SearchQuerySet(queries=("explicit board catalog",))
    receipt = enumerate_search_channel(
        profile=_profile(1, page_limit=2),
        query_set=query_set,
        api=SearchApiProfile(profile_id="public-search", locator=API),
        observations=(
            CapturedObservation(
                locator=API,
                status_code=200,
                body=_page(next_page="https://api.example.test/search?page=2"),
                media_type="application/json",
            ),
            CapturedObservation(
                locator="https://api.example.test/search?page=2",
                status_code=200,
                body=_page(),
                media_type="application/json",
            ),
        ),
        observed_at=OBSERVED_AT,
    )
    kinds = [item.attempt_kind for item in receipt.request_receipts]
    assert "pagination" in kinds
    assert receipt.accounting.channel_state in {"complete", "partial"}


def test_search_auth_required_and_unavailable_block_without_scrape_fallback() -> None:
    html = (
        b"<html><a href='https://jobs.example.test/catalog.json'>scrape me</a></html>"
    )
    query_set = SearchQuerySet(queries=("explicit board catalog",))
    auth = enumerate_search_channel(
        profile=_profile(1),
        query_set=query_set,
        api=SearchApiProfile(
            profile_id="github-code",
            locator=API,
            auth_required=True,
        ),
        observations=(
            CapturedObservation(
                locator=API,
                status_code=200,
                body=html,
                media_type="text/html",
            ),
        ),
        observed_at=OBSERVED_AT,
    )
    assert auth.operation_outcomes == ("blocked",)
    assert auth.request_receipts == ()
    assert auth.occurrences == ()

    missing = enumerate_search_channel(
        profile=_profile(1),
        query_set=query_set,
        api=SearchApiProfile(profile_id="public-search", locator=API, available=False),
        observations=(),
        observed_at=OBSERVED_AT,
    )
    assert missing.operation_outcomes == ("blocked",)
    assert missing.occurrences == ()


def test_search_quota_duplicate_partial_and_credential_absence() -> None:
    query_set = SearchQuerySet(queries=QUERIES)
    quota = enumerate_search_channel(
        profile=_profile(),
        query_set=query_set,
        api=SearchApiProfile(profile_id="public-search", locator=API),
        observations=(CapturedObservation(locator=API, status_code=429, body=None),),
        observed_at=OBSERVED_AT,
    )
    assert "rate_limited" in quota.operation_outcomes

    partial = enumerate_search_channel(
        profile=_profile(),
        query_set=query_set,
        api=SearchApiProfile(profile_id="public-search", locator=API),
        observations=(
            CapturedObservation(
                locator=API,
                status_code=200,
                body=_page(next_page="https://api.example.test/search?page=2"),
                media_type="application/json",
            ),
        ),
        observed_at=OBSERVED_AT,
    )
    assert partial.accounting.channel_state in {"partial", "complete", "failed"}
    assert any(
        item.reason_code is BoundedReason.EVIDENCE_INCOMPLETE
        for item in partial.request_receipts
    )

    attributes = render_metric_attributes(
        channel=DiscoveryChannel.SEARCH,
        terminal_state="complete",
        reason_code=BoundedReason.NONE,
        complete=True,
        identity_digest=query_set.digest,
    )
    assert "GH_TOKEN" not in attributes
    assert query_set.digest == attributes["openopps.discovery.identity.sha256"]
