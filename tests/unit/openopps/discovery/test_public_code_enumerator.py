from __future__ import annotations

from datetime import UTC, datetime

from openopps.discovery.api import encode_channel_replay_receipt
from openopps.discovery.enumerators import CapturedObservation
from openopps.discovery.models import BoundedReason, ChannelBudget, ChannelProfile
from openopps.discovery.public_code import RepositorySeed, enumerate_public_code_channel


OBSERVED_AT = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
REVISION = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
ORIGIN = "https://raw.example.test:443"


def _profile(seed_ids: tuple[str, ...] = ("repo-a",), **budget: int) -> ChannelProfile:
    values = {
        "query_limit": 4,
        "request_limit": 10,
        "origin_limit": 3,
        "redirect_limit": 2,
        "page_limit": 3,
        "response_byte_limit": 5_000,
        "aggregate_byte_limit": 20_000,
        "candidate_limit": 10,
        "concurrency_limit": 2,
        "per_origin_concurrency_limit": 1,
        "retry_limit": 2,
        "parser_depth_limit": 8,
        "wall_clock_limit_ms": 5_000,
    }
    values.update(budget)
    return ChannelProfile(
        channel="public_code",
        budget=ChannelBudget(**values),
        seed_ids=seed_ids,
        allowed_origins=(ORIGIN,),
        allowed_query_keys=("ref",),
        parser_ids=("repository-record-v1",),
    )


def _seed(seed_id: str = "repo-a", **updates: object) -> RepositorySeed:
    values: dict[str, object] = {
        "seed_id": seed_id,
        "locator": "https://raw.example.test/repos/acme/data/catalog.json",
        "revision": REVISION,
        "path": "data/catalog.json",
        "claimed_license_locator": "https://raw.example.test/repos/acme/LICENSE",
    }
    values.update(updates)
    return RepositorySeed(**values)  # type: ignore[arg-type]


def _record(**updates: object) -> bytes:
    payload = {
        "licenseUrl": "https://raw.example.test/repos/acme/LICENSE",
        "path": "data/catalog.json",
        "revision": REVISION,
        "sources": [{"url": "https://jobs.example.test/catalog.json"}],
    }
    payload.update(updates)
    import json

    return (json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n").encode()


def test_public_code_preserves_revision_path_license_and_digest_separately() -> None:
    body = _record()
    receipt = enumerate_public_code_channel(
        profile=_profile(),
        seeds=(_seed(),),
        observations=(
            CapturedObservation(
                locator="https://raw.example.test/repos/acme/data/catalog.json",
                status_code=200,
                body=body,
                media_type="application/json",
            ),
        ),
        observed_at=OBSERVED_AT,
    )
    fields = {claim.field_name: claim for claim in receipt.provenance_claims}
    assert fields["repositoryRevision"].value == REVISION
    assert fields["repositoryRevision"].source == "local_observation"
    assert fields["repositoryPath"].value == "data/catalog.json"
    assert fields["contentDigest"].source == "local_observation"
    assert fields["claimedLicenseLocator"].source == "remote_assertion"
    assert fields["claimedLicenseLocator"].accepted is False
    assert receipt.resources[0].content_sha256 == fields["contentDigest"].value
    occurrence = receipt.occurrences[0]
    assert fields["repositoryRevision"].claim_id in occurrence.provenance_ids
    assert fields["claimedLicenseLocator"].claim_id in occurrence.provenance_ids


def test_public_code_rejects_archives_executables_dependencies_and_remote_parsers() -> (
    None
):
    archive = enumerate_public_code_channel(
        profile=_profile(),
        seeds=(_seed(path="data/catalog.zip"),),
        observations=(
            CapturedObservation(
                locator="https://raw.example.test/repos/acme/data/catalog.json",
                status_code=200,
                body=b"PK\x03\x04not-a-real-zip",
                media_type="application/zip",
            ),
        ),
        observed_at=OBSERVED_AT,
    )
    assert archive.operation_outcomes == ("blocked",)
    executable = enumerate_public_code_channel(
        profile=_profile(),
        seeds=(_seed(path="scripts/run.sh"),),
        observations=(
            CapturedObservation(
                locator="https://raw.example.test/repos/acme/data/catalog.json",
                status_code=200,
                body=b"#!/bin/sh\necho hi\n",
                media_type="text/x-sh",
            ),
        ),
        observed_at=OBSERVED_AT,
    )
    assert executable.operation_outcomes == ("blocked",)
    deps = enumerate_public_code_channel(
        profile=_profile(),
        seeds=(_seed(path="package.json"),),
        observations=(
            CapturedObservation(
                locator="https://raw.example.test/repos/acme/data/catalog.json",
                status_code=200,
                body=b'{"dependencies":{"left-pad":"1.0.0"}}\n',
                media_type="application/json",
            ),
        ),
        observed_at=OBSERVED_AT,
    )
    assert deps.operation_outcomes == ("blocked",)
    remote_parser = enumerate_public_code_channel(
        profile=_profile(),
        seeds=(_seed(),),
        observations=(
            CapturedObservation(
                locator="https://raw.example.test/repos/acme/data/catalog.json",
                status_code=200,
                body=_record(parserId="evil-parser"),
                media_type="application/json",
            ),
        ),
        observed_at=OBSERVED_AT,
    )
    assert remote_parser.operation_outcomes == ("blocked",)
    assert (
        remote_parser.request_receipts[0].reason_code is BoundedReason.PARSER_REJECTED
    )


def test_public_code_rate_limit_truncation_stale_revision_duplicate_malformed() -> None:
    rate = enumerate_public_code_channel(
        profile=_profile(),
        seeds=(_seed(),),
        observations=(
            CapturedObservation(
                locator="https://raw.example.test/repos/acme/data/catalog.json",
                status_code=429,
                body=None,
            ),
        ),
        observed_at=OBSERVED_AT,
    )
    assert rate.operation_outcomes == ("rate_limited",)

    truncated = enumerate_public_code_channel(
        profile=_profile(response_byte_limit=8),
        seeds=(_seed(),),
        observations=(
            CapturedObservation(
                locator="https://raw.example.test/repos/acme/data/catalog.json",
                status_code=200,
                body=_record(),
                media_type="application/json",
            ),
        ),
        observed_at=OBSERVED_AT,
    )
    assert truncated.operation_outcomes == ("failed",)
    assert truncated.request_receipts[0].reason_code is BoundedReason.CONTENT_REJECTED

    stale = enumerate_public_code_channel(
        profile=_profile(),
        seeds=(_seed(),),
        observations=(
            CapturedObservation(
                locator="https://raw.example.test/repos/acme/data/catalog.json",
                status_code=200,
                body=_record(revision="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"),
                media_type="application/json",
            ),
        ),
        observed_at=OBSERVED_AT,
    )
    assert stale.request_receipts[0].reason_code is BoundedReason.EVIDENCE_STALE

    malformed = enumerate_public_code_channel(
        profile=_profile(),
        seeds=(_seed(),),
        observations=(
            CapturedObservation(
                locator="https://raw.example.test/repos/acme/data/catalog.json",
                status_code=200,
                body=b"{not json",
                media_type="application/json",
            ),
        ),
        observed_at=OBSERVED_AT,
    )
    assert malformed.operation_outcomes == ("failed",)

    duplicate = enumerate_public_code_channel(
        profile=_profile(seed_ids=("repo-a", "repo-b")),
        seeds=(
            _seed(),
            _seed(seed_id="repo-b"),
        ),
        observations=(
            CapturedObservation(
                locator="https://raw.example.test/repos/acme/data/catalog.json",
                status_code=200,
                body=_record(),
                media_type="application/json",
            ),
        ),
        observed_at=OBSERVED_AT,
    )
    assert duplicate.accounting.succeeded == 2
    assert len(duplicate.occurrences) == 2
    assert len({item.occurrence_id for item in duplicate.occurrences}) == 2
    first = encode_channel_replay_receipt(duplicate)
    second = encode_channel_replay_receipt(
        enumerate_public_code_channel(
            profile=_profile(seed_ids=("repo-a", "repo-b")),
            seeds=(_seed(), _seed(seed_id="repo-b")),
            observations=(
                CapturedObservation(
                    locator="https://raw.example.test/repos/acme/data/catalog.json",
                    status_code=200,
                    body=_record(),
                    media_type="application/json",
                ),
            ),
            observed_at=OBSERVED_AT,
        )
    )
    assert first == second
