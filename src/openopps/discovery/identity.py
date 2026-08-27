"""Candidate identity normalization, collision retention, and taxonomy closure."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal
from urllib.parse import urlsplit

from openopps.discovery.canonical import canonical_json_bytes
from openopps.discovery.models import (
    CandidateIdentity,
    CandidateOccurrence,
    NormalizedCandidate,
)
from openopps.discovery.transport import (
    DiscoveryTransportError,
    validate_public_locator,
)


REQUIRED_TAXONOMY_FIELDS = (
    "providerType",
    "coverageMode",
    "accessType",
    "licenseStatus",
    "refreshCadence",
    "sourceCategory",
    "sourceAttribution",
    "inclusionReason",
)


@dataclass(frozen=True, slots=True)
class IdentityCollision:
    candidate_keys: tuple[str, ...]
    reasons: tuple[str, ...]
    resolved: bool = False
    identities: tuple[CandidateIdentity, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolvedCandidate:
    identity: CandidateIdentity
    occurrence_ids: tuple[str, ...]
    provenance_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IdentityResolution:
    observed_occurrences: int
    invalid_occurrences: int
    normalized_occurrences: int
    duplicate_occurrences: int
    unique_candidates: int
    already_approved: int
    quarantined_candidates: int
    candidates: tuple[ResolvedCandidate, ...]
    collisions: tuple[IdentityCollision, ...]
    promotable_candidates: tuple[CandidateIdentity, ...]


@dataclass(frozen=True, slots=True)
class TaxonomyValidation:
    complete: bool
    missing_fields: tuple[str, ...]
    source_year: int | None


@dataclass(frozen=True, slots=True)
class RawOccurrenceInput:
    """Pre-normalization occurrence. Invalid locators stay in the invalid set."""

    occurrence_id: str
    channel: Literal["official", "public_code", "search", "targeted_ats"]
    key: str
    url: str
    provider_id: str
    owner: str
    provenance_ids: tuple[str, ...]
    provider_token: str | None = None
    candidate_kind: Literal["source", "board_route", "dataset", "catalog"] = "source"
    adapter_id: str | None = None


def normalize_candidate_identity(
    *,
    key: str,
    url: str,
    provider_id: str,
    provider_token: str | None,
    owner: str,
    candidate_kind: Literal["source", "board_route", "dataset", "catalog"] = "source",
    adapter_id: str | None = None,
) -> CandidateIdentity:
    """Normalize stable fields without performing network access."""

    normalized_key = key.strip().lower()
    normalized_provider = provider_id.strip().lower()
    normalized_owner = owner.strip().lower()
    normalized_token = provider_token.strip() if provider_token else None
    normalized_adapter = adapter_id.strip().casefold() if adapter_id else None
    if not normalized_key or not normalized_provider or not normalized_owner:
        raise ValueError("candidate identity fields must be non-empty")
    locator = validate_public_locator(url)
    return CandidateIdentity(
        key=normalized_key,
        url=url,
        canonical_url=locator.url,
        provider_id=normalized_provider,
        provider_token=normalized_token,
        owner=normalized_owner,
        candidate_kind=candidate_kind,
        adapter_id=normalized_adapter,
    )


def _collision_reasons(
    left: CandidateIdentity, right: CandidateIdentity
) -> tuple[str, ...]:
    reasons: list[str] = []
    if left.key == right.key:
        reasons.append("exact_key")
    if left.url == right.url:
        reasons.append("exact_url")
    if left.canonical_url == right.canonical_url:
        reasons.append("canonical_url")
    same_domain = (
        urlsplit(left.canonical_url).hostname == urlsplit(right.canonical_url).hostname
    )
    provider_tokens_prove_distinct = (
        left.provider_id == right.provider_id
        and left.provider_token is not None
        and right.provider_token is not None
        and left.provider_token != right.provider_token
    )
    if same_domain and not provider_tokens_prove_distinct:
        reasons.append("domain")
    if (
        left.provider_id == right.provider_id
        and left.provider_token is not None
        and left.provider_token == right.provider_token
    ):
        reasons.append("provider_token")
    if reasons:
        if left.owner != right.owner:
            reasons.append("owner")
        if left.provider_id != right.provider_id:
            reasons.append("provider")
    return tuple(reasons)


def _identity_sort_key(identity: CandidateIdentity) -> tuple[str, ...]:
    return (
        identity.key,
        identity.canonical_url,
        identity.provider_id,
        identity.provider_token or "",
        identity.owner,
    )


def resolve_candidate_identities(
    occurrences: Iterable[CandidateOccurrence],
    *,
    approved_catalog: Iterable[CandidateIdentity],
    invalid_occurrence_ids: Iterable[str] = (),
) -> IdentityResolution:
    """Deduplicate exact identities and retain every ambiguous collision."""

    occurrence_values = tuple(occurrences)
    occurrence_ids = tuple(item.occurrence_id for item in occurrence_values)
    invalid_ids = tuple(invalid_occurrence_ids)
    if len(set(occurrence_ids)) != len(occurrence_ids):
        raise ValueError("candidate occurrence IDs must be unique")
    if any(not item for item in invalid_ids) or len(set(invalid_ids)) != len(
        invalid_ids
    ):
        raise ValueError("invalid occurrence IDs must be unique")
    if set(invalid_ids) & set(occurrence_ids):
        raise ValueError("invalid occurrence IDs collide with normalized IDs")
    unique = tuple(
        sorted({item.identity for item in occurrence_values}, key=_identity_sort_key)
    )
    resolved_candidates = tuple(
        ResolvedCandidate(
            identity=identity,
            occurrence_ids=tuple(
                sorted(
                    item.occurrence_id
                    for item in occurrence_values
                    if item.identity == identity
                )
            ),
            provenance_ids=tuple(
                sorted(
                    {
                        provenance_id
                        for item in occurrence_values
                        if item.identity == identity
                        for provenance_id in item.provenance_ids
                    }
                )
            ),
        )
        for identity in unique
    )
    approved = tuple(approved_catalog)
    approved_set = set(approved)
    collision_reasons: dict[tuple[CandidateIdentity, CandidateIdentity], set[str]] = (
        defaultdict(set)
    )
    comparison_pool = (*unique, *approved)
    for index, left in enumerate(comparison_pool):
        for right in comparison_pool[index + 1 :]:
            if left == right:
                continue
            reasons = _collision_reasons(left, right)
            if reasons:
                pair = (
                    (left, right)
                    if _identity_sort_key(left) <= _identity_sort_key(right)
                    else (right, left)
                )
                collision_reasons[pair].update(reasons)
    collisions = tuple(
        IdentityCollision(
            candidate_keys=tuple(identity.key for identity in pair),
            reasons=tuple(sorted(reasons)),
            identities=pair,
        )
        for pair, reasons in sorted(
            collision_reasons.items(),
            key=lambda item: tuple(_identity_sort_key(value) for value in item[0]),
        )
    )
    collided = {identity for pair in collision_reasons for identity in pair}
    candidates = tuple(identity for identity in unique if identity not in approved_set)
    promotable = tuple(identity for identity in candidates if identity not in collided)
    already_approved = sum(identity in approved_set for identity in unique)
    return IdentityResolution(
        observed_occurrences=len(occurrence_values) + len(invalid_ids),
        invalid_occurrences=len(invalid_ids),
        normalized_occurrences=len(occurrence_values),
        duplicate_occurrences=len(occurrence_values) - len(unique),
        unique_candidates=len(unique),
        already_approved=already_approved,
        quarantined_candidates=len(candidates),
        candidates=resolved_candidates,
        collisions=collisions,
        promotable_candidates=promotable,
    )


def validate_taxonomy(values: Mapping[str, object]) -> TaxonomyValidation:
    """Require all eight standard fields while keeping sourceYear optional."""

    unknown = set(values) - {*REQUIRED_TAXONOMY_FIELDS, "sourceYear"}
    if unknown:
        raise ValueError("taxonomy contains unknown fields")
    missing = tuple(
        field
        for field in REQUIRED_TAXONOMY_FIELDS
        if not isinstance(values.get(field), str) or not str(values[field]).strip()
    )
    source_year = values.get("sourceYear")
    if source_year is not None and (
        isinstance(source_year, bool)
        or not isinstance(source_year, int)
        or source_year < 1900
        or source_year > 9999
    ):
        raise ValueError("sourceYear must be a four-digit integer")
    return TaxonomyValidation(
        complete=not missing,
        missing_fields=missing,
        source_year=source_year,
    )


def admit_raw_occurrences(
    records: Iterable[RawOccurrenceInput],
) -> tuple[tuple[CandidateOccurrence, ...], tuple[str, ...]]:
    """Normalize public locators; invalid records remain explicitly invalid."""

    values = tuple(records)
    ids = tuple(item.occurrence_id for item in values)
    if any(not item for item in ids) or len(set(ids)) != len(ids):
        raise ValueError("raw occurrence IDs must be unique")
    valid: list[CandidateOccurrence] = []
    invalid: list[str] = []
    for item in values:
        try:
            identity = normalize_candidate_identity(
                key=item.key,
                url=item.url,
                provider_id=item.provider_id,
                provider_token=item.provider_token,
                owner=item.owner,
                candidate_kind=item.candidate_kind,
                adapter_id=item.adapter_id,
            )
        except (ValueError, DiscoveryTransportError):
            invalid.append(item.occurrence_id)
            continue
        valid.append(
            CandidateOccurrence(
                occurrence_id=item.occurrence_id,
                channel=item.channel,
                identity=identity,
                provenance_ids=item.provenance_ids,
            )
        )
    return tuple(valid), tuple(invalid)


def candidate_identity_id(identity: CandidateIdentity) -> str:
    """Stable content identity for one normalized candidate."""

    payload = canonical_json_bytes(
        identity.model_dump(mode="json", by_alias=True, round_trip=True)
    )
    return sha256(payload).hexdigest()


def normalized_candidates_from_resolution(
    resolution: IdentityResolution,
) -> tuple[NormalizedCandidate, ...]:
    """Group duplicate occurrences while preserving sorted provenance edges."""

    collision_ids_by_identity: dict[CandidateIdentity, list[str]] = defaultdict(list)
    for collision in resolution.collisions:
        collision_id = sha256(
            canonical_json_bytes(
                {
                    "keys": list(collision.candidate_keys),
                    "reasons": list(collision.reasons),
                }
            )
        ).hexdigest()
        for identity in collision.identities:
            collision_ids_by_identity[identity].append(collision_id)
    return tuple(
        NormalizedCandidate(
            candidate_id=candidate_identity_id(item.identity),
            identity=item.identity,
            occurrence_ids=item.occurrence_ids,
            provenance_ids=item.provenance_ids,
            collision_ids=tuple(sorted(set(collision_ids_by_identity[item.identity]))),
        )
        for item in resolution.candidates
    )
