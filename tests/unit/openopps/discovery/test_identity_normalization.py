"""V501-V506 identity normalization, catalog comparison, and explicit collisions."""

from __future__ import annotations

from openopps.discovery.identity import (
    RawOccurrenceInput,
    admit_raw_occurrences,
    normalized_candidates_from_resolution,
    normalize_candidate_identity,
    resolve_candidate_identities,
    validate_taxonomy,
)
from openopps.discovery.models import CandidateOccurrence


def _identity(**updates: object):
    values: dict[str, object] = {
        "key": "acme",
        "url": "https://jobs.example.test/acme",
        "provider_id": "greenhouse",
        "provider_token": "acme",
        "owner": "official",
    }
    values.update(updates)
    return normalize_candidate_identity(**values)


def _occurrence(identity, occurrence_id: str, *provenance: str) -> CandidateOccurrence:
    return CandidateOccurrence(
        occurrence_id=occurrence_id,
        channel="official",
        identity=identity,
        provenance_ids=provenance or (f"resource-{occurrence_id}",),
    )


def test_normalize_public_locator_and_provider_token() -> None:
    identity = _identity(
        key=" Acme ",
        url="https://JOBS.example.test:443/acme",
        provider_id="GreenHouse",
        owner=" Official ",
    )
    assert identity.key == "acme"
    assert identity.canonical_url == "https://jobs.example.test/acme"
    assert identity.provider_id == "greenhouse"
    assert identity.provider_token == "acme"
    assert identity.owner == "official"


def test_proposed_keys_do_not_silently_resolve_collisions() -> None:
    left = _identity(key="same", url="https://one.example.test/jobs")
    right = _identity(key="same", url="https://two.example.test/jobs")
    result = resolve_candidate_identities(
        (_occurrence(left, "left"), _occurrence(right, "right")),
        approved_catalog=(),
    )
    assert result.collisions[0].resolved is False
    assert "exact_key" in result.collisions[0].reasons
    assert result.promotable_candidates == ()


def test_every_approved_source_is_compared_for_exact_and_canonical_identity() -> None:
    approved = (
        _identity(
            key="alpha", url="https://alpha.example.test/jobs", provider_token="a"
        ),
        _identity(key="beta", url="https://beta.example.test/jobs", provider_token="b"),
        _identity(
            key="gamma",
            url="https://JOBS.example.test:443/acme",
            provider_token="acme",
        ),
    )
    colliding = _identity()
    exact = _identity(
        key="alpha", url="https://alpha.example.test/jobs", provider_token="a"
    )
    collided = resolve_candidate_identities(
        (_occurrence(colliding, "candidate"),),
        approved_catalog=approved,
    )
    assert collided.already_approved == 0
    assert collided.quarantined_candidates == 1
    assert collided.collisions[0].resolved is False
    assert "canonical_url" in collided.collisions[0].reasons
    assert collided.promotable_candidates == ()

    matched = resolve_candidate_identities(
        (_occurrence(exact, "approved"),),
        approved_catalog=approved,
    )
    assert matched.already_approved == 1
    assert matched.quarantined_candidates == 0
    assert matched.unique_candidates == 1


def test_duplicate_occurrences_preserve_union_of_provenance_edges() -> None:
    identity = _identity()
    result = resolve_candidate_identities(
        (
            _occurrence(identity, "first", "resource-a"),
            _occurrence(identity, "repeat", "resource-b"),
        ),
        approved_catalog=(),
    )
    grouped = normalized_candidates_from_resolution(result)
    assert result.duplicate_occurrences == 1
    assert result.unique_candidates == 1
    assert grouped[0].occurrence_ids == ("first", "repeat")
    assert grouped[0].provenance_ids == ("resource-a", "resource-b")


def test_taxonomy_requires_all_eight_fields() -> None:
    required = {
        "providerType": "job_board",
        "coverageMode": "portfolio_jobs",
        "accessType": "public_json_api",
        "licenseStatus": "official_public",
        "refreshCadence": "daily",
        "sourceCategory": "employer",
        "sourceAttribution": "Example public careers site.",
        "inclusionReason": "Verified generic public route.",
    }
    assert validate_taxonomy(required).complete is True
    missing = dict(required)
    missing.pop("inclusionReason")
    result = validate_taxonomy(missing)
    assert result.complete is False
    assert result.missing_fields == ("inclusionReason",)


def test_owner_and_provider_conflicts_stay_explicit() -> None:
    left = _identity(key="same", owner="official", provider_id="greenhouse")
    right = _identity(
        key="same",
        url="https://other.example.test/jobs",
        owner="community",
        provider_id="lever",
        provider_token="other",
    )
    result = resolve_candidate_identities(
        (_occurrence(left, "left"), _occurrence(right, "right")),
        approved_catalog=(),
    )
    reasons = set(result.collisions[0].reasons)
    assert "exact_key" in reasons
    assert "owner" in reasons
    assert "provider" in reasons
    assert result.collisions[0].resolved is False


def test_invalid_locators_are_counted_and_not_normalized() -> None:
    valid, invalid = admit_raw_occurrences(
        (
            RawOccurrenceInput(
                occurrence_id="good",
                channel="official",
                key="acme",
                url="https://jobs.example.test/acme",
                provider_id="greenhouse",
                owner="official",
                provenance_ids=("resource-good",),
                provider_token="acme",
            ),
            RawOccurrenceInput(
                occurrence_id="bad",
                channel="official",
                key="local",
                url="http://127.0.0.1/jobs",
                provider_id="greenhouse",
                owner="official",
                provenance_ids=("resource-bad",),
            ),
        )
    )
    result = resolve_candidate_identities(
        valid, approved_catalog=(), invalid_occurrence_ids=invalid
    )
    assert invalid == ("bad",)
    assert result.observed_occurrences == 2
    assert result.invalid_occurrences == 1
    assert result.normalized_occurrences == 1
    assert result.observed_occurrences == (
        result.invalid_occurrences + result.normalized_occurrences
    )
