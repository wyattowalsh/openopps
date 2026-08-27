"""Bounded public code and dataset enumerator (E421-E426)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
import re

from openopps.discovery.enumerators import (
    CapturedObservation,
    ChannelRunBuilder,
    EnumeratorError,
    add_local_claim,
    add_remote_claim,
    admit_observation_resource,
    canonical_locator,
    digest_input_set,
    json_contains_remote_parser_identifier,
    lookup_observation,
    media_is_archive,
    media_is_executable,
    observation_digest,
    observation_map,
    occurrence_from_locator,
    origin_allowed,
    parse_bounded_json,
    path_is_dependency_manifest,
    request_outcome_from_observation,
    require_channel_profile,
    require_observed_at,
)
from openopps.discovery.models import (
    BoundedReason,
    ChannelProfile,
    ChannelReplayReceipt,
)


PUBLIC_CODE_ENUMERATOR_VERSION = "public-code-fixture-v1"
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class RepositorySeed:
    """Maintainer-owned public repository or dataset seed."""

    seed_id: str
    locator: str
    revision: str
    path: str
    claimed_license_locator: str | None = None
    candidate_kind: Literal["source", "dataset", "catalog"] = "dataset"


def enumerate_public_code_channel(
    *,
    profile: ChannelProfile,
    seeds: Sequence[RepositorySeed],
    observations: Sequence[CapturedObservation] | Mapping[str, CapturedObservation],
    observed_at: datetime,
) -> ChannelReplayReceipt:
    """Replay finite public code/dataset discovery without live network access."""

    profile = require_channel_profile(profile, "public_code")
    observed_at = require_observed_at(observed_at)
    seed_values = _validate_seeds(profile, seeds)
    captured = observation_map(observations)
    input_digest = digest_input_set(
        {
            "allowedOrigins": list(profile.allowed_origins),
            "enumeratorVersion": PUBLIC_CODE_ENUMERATOR_VERSION,
            "observations": [
                observation_digest(captured[key]) for key in sorted(captured)
            ],
            "parserIds": list(profile.parser_ids),
            "seedIds": list(profile.seed_ids),
            "seeds": [
                {
                    "candidateKind": seed.candidate_kind,
                    "claimedLicenseLocator": seed.claimed_license_locator,
                    "locator": seed.locator,
                    "path": seed.path,
                    "revision": seed.revision,
                    "seedId": seed.seed_id,
                }
                for seed in seed_values
            ],
        }
    )
    builder = ChannelRunBuilder(
        channel="public_code",
        enumerator_version=PUBLIC_CODE_ENUMERATOR_VERSION,
        input_set_sha256=input_digest,
        budget=profile.budget,
        observed_at=observed_at,
    )
    selected = seed_values[: profile.budget.query_limit]
    for seed in selected:
        builder.plan(f"{seed.seed_id}:record")
    seen_identities: set[tuple[str, str]] = set()
    for seed in selected:
        _run_record(
            builder,
            profile=profile,
            seed=seed,
            captured=captured,
            seen_identities=seen_identities,
        )
    return builder.close()


def _validate_seeds(
    profile: ChannelProfile,
    seeds: Sequence[RepositorySeed],
) -> tuple[RepositorySeed, ...]:
    if not seeds:
        raise EnumeratorError("repository_seeds")
    ordered = tuple(sorted(seeds, key=lambda seed: seed.seed_id))
    identities = tuple(seed.seed_id for seed in ordered)
    if identities != tuple(sorted(set(identities))) or identities != profile.seed_ids:
        raise EnumeratorError("repository_seeds")
    for seed in ordered:
        if seed.candidate_kind not in {"dataset", "catalog", "source"}:
            raise EnumeratorError("repository_kind")
        if _GIT_SHA.fullmatch(seed.revision) is None:
            raise EnumeratorError("repository_revision")
        if not seed.path or "\\" in seed.path or ".." in seed.path.split("/"):
            raise EnumeratorError("repository_path")
        canonical_locator(seed.locator)
        if seed.claimed_license_locator is not None:
            canonical_locator(seed.claimed_license_locator)
    return ordered


def _run_record(
    builder: ChannelRunBuilder,
    *,
    profile: ChannelProfile,
    seed: RepositorySeed,
    captured: Mapping[str, CapturedObservation],
    seen_identities: set[tuple[str, str]],
) -> None:
    operation_id = f"{seed.seed_id}:record"
    locator = canonical_locator(seed.locator)
    if not origin_allowed(profile, locator) or not builder.can_admit_origin(
        locator.origin
    ):
        builder.finish(operation_id, "blocked")
        return
    if not builder.can_start():
        return
    observation = lookup_observation(captured, locator)
    if observation is None:
        builder.add_request(
            operation_id,
            attempt_kind="initial",
            outcome="failed",
            locator=locator,
            resource_id=None,
            response_status=None,
            admitted_bytes=0,
            elapsed_ms=0,
            reason_code=BoundedReason.EVIDENCE_INCOMPLETE,
        )
        builder.finish(operation_id, "failed")
        return
    outcome, reason = request_outcome_from_observation(observation)
    if outcome != "succeeded":
        builder.add_request(
            operation_id,
            attempt_kind="initial",
            outcome=outcome,
            locator=locator,
            resource_id=None,
            response_status=observation.status_code,
            admitted_bytes=0,
            elapsed_ms=observation.elapsed_ms,
            reason_code=reason,
            validated_address=observation.validated_address,
        )
        builder.finish(
            operation_id,
            "rate_limited"
            if outcome == "rate_limited"
            else ("blocked" if outcome == "blocked" else "failed"),
        )
        return
    body = observation.body
    if not isinstance(body, bytes):
        builder.add_request(
            operation_id,
            attempt_kind="initial",
            outcome="failed",
            locator=locator,
            resource_id=None,
            response_status=observation.status_code,
            admitted_bytes=0,
            elapsed_ms=observation.elapsed_ms,
            reason_code=BoundedReason.EVIDENCE_INCOMPLETE,
            validated_address=observation.validated_address,
        )
        builder.finish(operation_id, "failed")
        return
    if len(body) > profile.budget.response_byte_limit:
        builder.add_request(
            operation_id,
            attempt_kind="initial",
            outcome="failed",
            locator=locator,
            resource_id=None,
            response_status=observation.status_code,
            admitted_bytes=0,
            elapsed_ms=observation.elapsed_ms,
            reason_code=BoundedReason.CONTENT_REJECTED,
            validated_address=observation.validated_address,
        )
        builder.finish(operation_id, "failed")
        return
    media_type = observation.media_type or "application/octet-stream"
    if (
        media_is_archive(media_type, seed.path)
        or media_is_executable(media_type, seed.path)
        or path_is_dependency_manifest(seed.path)
    ):
        builder.add_request(
            operation_id,
            attempt_kind="initial",
            outcome="blocked",
            locator=locator,
            resource_id=None,
            response_status=observation.status_code,
            admitted_bytes=0,
            elapsed_ms=observation.elapsed_ms,
            reason_code=BoundedReason.CONTENT_REJECTED,
            validated_address=observation.validated_address,
        )
        builder.finish(operation_id, "blocked")
        return
    remote_revision = None
    remote_path = None
    remote_license = seed.claimed_license_locator
    if media_type.endswith("json") or media_type.endswith("+json"):
        try:
            payload = parse_bounded_json(
                body,
                depth_limit=profile.budget.parser_depth_limit,
            )
        except EnumeratorError:
            builder.add_request(
                operation_id,
                attempt_kind="initial",
                outcome="failed",
                locator=locator,
                resource_id=None,
                response_status=observation.status_code,
                admitted_bytes=0,
                elapsed_ms=observation.elapsed_ms,
                reason_code=BoundedReason.PARSER_REJECTED,
                validated_address=observation.validated_address,
            )
            builder.finish(operation_id, "failed")
            return
        if json_contains_remote_parser_identifier(payload):
            builder.add_request(
                operation_id,
                attempt_kind="initial",
                outcome="blocked",
                locator=locator,
                resource_id=None,
                response_status=observation.status_code,
                admitted_bytes=0,
                elapsed_ms=observation.elapsed_ms,
                reason_code=BoundedReason.PARSER_REJECTED,
                validated_address=observation.validated_address,
            )
            builder.finish(operation_id, "blocked")
            return
        if isinstance(payload, dict):
            revision_value = payload.get("revision")
            path_value = payload.get("path")
            license_value = payload.get("licenseUrl")
            if isinstance(revision_value, str):
                remote_revision = revision_value
            if isinstance(path_value, str):
                remote_path = path_value
            if isinstance(license_value, str):
                remote_license = license_value
    if remote_revision is not None and remote_revision != seed.revision:
        builder.add_request(
            operation_id,
            attempt_kind="initial",
            outcome="failed",
            locator=locator,
            resource_id=None,
            response_status=observation.status_code,
            admitted_bytes=0,
            elapsed_ms=observation.elapsed_ms,
            reason_code=BoundedReason.EVIDENCE_STALE,
            validated_address=observation.validated_address,
        )
        builder.finish(operation_id, "failed")
        return
    resource = admit_observation_resource(
        builder,
        observation,
        locator,
        role="repository-evidence",
        media_type=media_type,
    )
    if resource is None:
        builder.add_request(
            operation_id,
            attempt_kind="initial",
            outcome="blocked",
            locator=locator,
            resource_id=None,
            response_status=observation.status_code,
            admitted_bytes=0,
            elapsed_ms=observation.elapsed_ms,
            reason_code=BoundedReason.SECRET_DETECTED,
            validated_address=observation.validated_address,
        )
        builder.finish(operation_id, "blocked")
        return
    builder.add_request(
        operation_id,
        attempt_kind="initial",
        outcome="succeeded",
        locator=locator,
        resource_id=resource.resource_id,
        response_status=observation.status_code,
        admitted_bytes=resource.size_bytes,
        elapsed_ms=observation.elapsed_ms,
        reason_code=BoundedReason.NONE,
        validated_address=observation.validated_address,
    )
    revision_claim = add_local_claim(
        builder,
        resource_id=resource.resource_id,
        field_name="repositoryRevision",
        value=seed.revision,
    )
    path_claim = add_local_claim(
        builder,
        resource_id=resource.resource_id,
        field_name="repositoryPath",
        value=seed.path,
    )
    digest_claim = add_local_claim(
        builder,
        resource_id=resource.resource_id,
        field_name="contentDigest",
        value=resource.content_sha256,
    )
    provenance_ids = [
        resource.resource_id,
        revision_claim.claim_id,
        path_claim.claim_id,
        digest_claim.claim_id,
    ]
    if remote_revision is not None:
        provenance_ids.append(
            add_remote_claim(
                builder,
                resource_id=resource.resource_id,
                field_name="claimedRevision",
                value=remote_revision,
            ).claim_id
        )
    if remote_path is not None:
        provenance_ids.append(
            add_remote_claim(
                builder,
                resource_id=resource.resource_id,
                field_name="claimedPath",
                value=remote_path,
            ).claim_id
        )
    if remote_license is not None:
        provenance_ids.append(
            add_remote_claim(
                builder,
                resource_id=resource.resource_id,
                field_name="claimedLicenseLocator",
                value=remote_license,
            ).claim_id
        )
    identity_key = (locator.url, seed.path)
    occurrence_id = f"public-code:{seed.seed_id}"
    if identity_key in seen_identities:
        occurrence_id = f"public-code:{seed.seed_id}:duplicate"
    seen_identities.add(identity_key)
    builder.add_occurrence(
        occurrence_from_locator(
            occurrence_id=occurrence_id,
            channel="public_code",
            locator=locator,
            provider_id="public-code",
            owner="public-code",
            candidate_kind=seed.candidate_kind,
            provenance_ids=tuple(provenance_ids),
            key=seed.seed_id,
        )
    )
    builder.finish(operation_id, "succeeded")
