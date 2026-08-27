from __future__ import annotations

from datetime import UTC, datetime
import json

import pytest

from openopps.discovery.enumerators import CapturedObservation
from openopps.discovery.merge import (
    MergeError,
    encode_merged_discovery_receipt,
    merge_channel_receipts,
)
from openopps.discovery.models import ChannelBudget, ChannelProfile
from openopps.discovery.official import OfficialSeed, enumerate_official_channel
from openopps.discovery.public_code import RepositorySeed, enumerate_public_code_channel
from openopps.discovery.search import (
    SearchApiProfile,
    SearchQuerySet,
    enumerate_search_channel,
)
from openopps.discovery.targeted_ats import (
    EmployerTarget,
    enumerate_targeted_ats_channel,
)


OBSERVED_AT = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
REVISION = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def _budget(**updates: int) -> ChannelBudget:
    values = {
        "query_limit": 2,
        "request_limit": 8,
        "origin_limit": 4,
        "redirect_limit": 2,
        "page_limit": 2,
        "response_byte_limit": 20_000,
        "aggregate_byte_limit": 80_000,
        "candidate_limit": 20,
        "concurrency_limit": 2,
        "per_origin_concurrency_limit": 1,
        "retry_limit": 2,
        "parser_depth_limit": 8,
        "wall_clock_limit_ms": 5_000,
    }
    values.update(updates)
    return ChannelBudget(**values)


def _official(*, failed: bool = False):
    body = (
        b"{not-json"
        if failed
        else b'{"items":[{"jobs":"https://jobs.example.test/companies/acme/jobs","name":"Acme","provider":"example-provider"}],"next":null}\n'
    )
    return enumerate_official_channel(
        profile=ChannelProfile(
            channel="official",
            budget=_budget(),
            seed_ids=("official-catalog",),
            allowed_origins=("https://jobs.example.test:443",),
            allowed_query_keys=("page",),
            parser_ids=("official-json-v1",),
        ),
        seeds=(
            OfficialSeed(
                seed_id="official-catalog",
                document_locator="https://jobs.example.test/catalog.json",
                parser_id="official-json-v1",
                robots_locator="https://jobs.example.test/robots.txt",
            ),
        ),
        observations=(
            CapturedObservation(
                locator="https://jobs.example.test/robots.txt",
                status_code=404,
                body=None,
            ),
            CapturedObservation(
                locator="https://jobs.example.test/catalog.json",
                status_code=200,
                body=body,
                media_type="application/json",
            ),
        ),
        observed_at=OBSERVED_AT,
    )


def _code():
    payload = {
        "licenseUrl": "https://raw.example.test/LICENSE",
        "path": "data/catalog.json",
        "revision": REVISION,
    }
    return enumerate_public_code_channel(
        profile=ChannelProfile(
            channel="public_code",
            budget=_budget(),
            seed_ids=("repo-a",),
            allowed_origins=("https://raw.example.test:443",),
            allowed_query_keys=("ref",),
            parser_ids=("repository-record-v1",),
        ),
        seeds=(
            RepositorySeed(
                seed_id="repo-a",
                locator="https://raw.example.test/data/catalog.json",
                revision=REVISION,
                path="data/catalog.json",
                claimed_license_locator="https://raw.example.test/LICENSE",
            ),
        ),
        observations=(
            CapturedObservation(
                locator="https://raw.example.test/data/catalog.json",
                status_code=200,
                body=(
                    json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n"
                ).encode(),
                media_type="application/json",
            ),
        ),
        observed_at=OBSERVED_AT,
    )


def _search():
    return enumerate_search_channel(
        profile=ChannelProfile(
            channel="search",
            budget=_budget(query_limit=1),
            seed_ids=("query-0000",),
            allowed_origins=("https://api.example.test:443",),
            allowed_query_keys=("q",),
            parser_ids=("search-api-v1",),
        ),
        query_set=SearchQuerySet(queries=("explicit board catalog",)),
        api=SearchApiProfile(
            profile_id="public-search",
            locator="https://api.example.test/search",
        ),
        observations=(
            CapturedObservation(
                locator="https://api.example.test/search",
                status_code=200,
                body=b'{"results":[{"url":"https://jobs.example.test/boards"}]}\n',
                media_type="application/json",
            ),
        ),
        observed_at=OBSERVED_AT,
    )


def _ats():
    return enumerate_targeted_ats_channel(
        profile=ChannelProfile(
            channel="targeted_ats",
            budget=_budget(),
            seed_ids=("acme-board",),
            allowed_origins=("https://boards.greenhouse.io:443",),
            allowed_query_keys=("board",),
            parser_ids=("html-links-v1",),
        ),
        targets=(
            EmployerTarget(
                target_id="acme-board",
                public_page_locator="https://boards.greenhouse.io/acme",
            ),
        ),
        observations=(
            CapturedObservation(
                locator="https://boards.greenhouse.io/acme",
                status_code=200,
                body=b"<!doctype html><html><body><p>Greenhouse</p></body></html>",
                media_type="text/html",
            ),
        ),
        observed_at=OBSERVED_AT,
    )


def test_merge_is_stable_across_completion_order_and_preserves_provenance_edges() -> (
    None
):
    official = _official()
    code = _code()
    search = _search()
    ats = _ats()
    forward = merge_channel_receipts((official, code, search, ats))
    reverse = merge_channel_receipts((ats, search, code, official))
    assert encode_merged_discovery_receipt(forward) == encode_merged_discovery_receipt(
        reverse
    )
    assert [item.channel for item in forward.receipts] == [
        "official",
        "public_code",
        "search",
        "targeted_ats",
    ]
    expected_edges = {
        (occurrence.occurrence_id, provenance_id)
        for receipt in (official, code, search, ats)
        for occurrence in receipt.occurrences
        for provenance_id in occurrence.provenance_ids
    }
    assert set(forward.provenance_edges) == expected_edges
    assert forward.whole_run_state == "complete"


def test_merge_rejects_duplicate_receipts_and_conflicting_provenance() -> None:
    official = _official()
    with pytest.raises(MergeError, match="duplicate_receipt"):
        merge_channel_receipts((official, official))
    left = _official()
    right = _code()
    colliding = right.model_copy(
        update={
            "resources": (
                right.resources[0].model_copy(
                    update={
                        "resource_id": left.resources[0].resource_id,
                        "content_sha256": "b" * 64,
                    }
                ),
            ),
            "provenance_claims": tuple(
                claim.model_copy(update={"resource_id": left.resources[0].resource_id})
                for claim in right.provenance_claims
            ),
            "occurrences": tuple(
                occurrence.model_copy(
                    update={
                        "provenance_ids": tuple(
                            left.resources[0].resource_id
                            if item == right.resources[0].resource_id
                            else item
                            for item in occurrence.provenance_ids
                        )
                    }
                )
                for occurrence in right.occurrences
            ),
            "request_receipts": tuple(
                receipt.model_copy(
                    update={
                        "resource_id": left.resources[0].resource_id
                        if receipt.resource_id == right.resources[0].resource_id
                        else receipt.resource_id
                    }
                )
                for receipt in right.request_receipts
            ),
        }
    )
    with pytest.raises(MergeError, match="conflicting_provenance"):
        merge_channel_receipts((left, colliding))


def test_isolated_channel_failure_keeps_unrelated_channels_and_marks_partial() -> None:
    merged = merge_channel_receipts(
        (_official(failed=True), _code(), _search(), _ats())
    )
    states = {item.channel: item.accounting.channel_state for item in merged.receipts}
    assert states["official"] in {"failed", "partial"}
    assert states["public_code"] == "complete"
    assert states["search"] == "complete"
    assert states["targeted_ats"] == "complete"
    assert merged.whole_run_state == "partial"
    assert any(item.channel == "public_code" for item in merged.occurrences)
    assert any(item.channel == "search" for item in merged.occurrences)
