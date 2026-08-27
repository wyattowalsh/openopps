"""Objective source-adapter and board-route support classification."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from openopps.discovery.models import CandidateIdentity, SupportEvidence
from openopps.discovery.targeted_ats import BuiltInRouteHint, classify_public_route


class SupportDisposition(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    INCONCLUSIVE = "inconclusive"


SupportLevel = Literal[
    "source_support",
    "detect_only",
    "executable_route",
    "authoritative_jobs",
    "unsupported",
    "inconclusive",
]


@dataclass(frozen=True, slots=True)
class SupportClassification:
    level: SupportLevel
    provider_id: str
    built_in_route: bool
    route_metadata_complete: bool
    job_fetch_validated: bool
    access_required: bool
    transient_failure: bool
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "accessRequired": self.access_required,
            "builtInRoute": self.built_in_route,
            "jobFetchValidated": self.job_fetch_validated,
            "level": self.level,
            "providerId": self.provider_id,
            "reason": self.reason,
            "routeMetadataComplete": self.route_metadata_complete,
            "transientFailure": self.transient_failure,
        }


def classify_support(evidence: SupportEvidence) -> SupportDisposition:
    if (
        evidence.transient_failure
        or not evidence.route_metadata_complete
        or not evidence.job_fetch_validated
    ):
        return SupportDisposition.INCONCLUSIVE
    if evidence.access_required or not evidence.built_in_route:
        return SupportDisposition.UNSUPPORTED
    return SupportDisposition.SUPPORTED


def classify_identity_support(
    identity: CandidateIdentity,
    *,
    source_adapter_ids: Iterable[str],
    access_required: bool = False,
    transient_failure: bool = False,
) -> tuple[SupportEvidence, SupportClassification]:
    """Reuse the frozen built-in route table; never invent an ATS from a domain."""

    adapters = frozenset(item.casefold() for item in source_adapter_ids)
    if transient_failure:
        classification = SupportClassification(
            level="inconclusive",
            provider_id=identity.provider_id,
            built_in_route=False,
            route_metadata_complete=False,
            job_fetch_validated=False,
            access_required=access_required,
            transient_failure=True,
            reason="transient_failure",
        )
        return _evidence(identity, classification), classification
    if access_required:
        classification = SupportClassification(
            level="unsupported",
            provider_id=identity.provider_id,
            built_in_route=False,
            route_metadata_complete=True,
            job_fetch_validated=False,
            access_required=True,
            transient_failure=False,
            reason="access_required",
        )
        return _evidence(identity, classification), classification

    route = classify_public_route(identity.canonical_url)
    if identity.candidate_kind == "source":
        return _source_support(identity, adapters=adapters, route=route)
    return _board_support(identity, route=route)


def _source_support(
    identity: CandidateIdentity,
    *,
    adapters: frozenset[str],
    route: BuiltInRouteHint | None,
) -> tuple[SupportEvidence, SupportClassification]:
    adapter_id = (identity.adapter_id or identity.provider_id).casefold()
    if adapter_id in adapters or identity.provider_id in adapters:
        classification = SupportClassification(
            level="source_support",
            provider_id=identity.provider_id,
            built_in_route=True,
            route_metadata_complete=True,
            job_fetch_validated=True,
            access_required=False,
            transient_failure=False,
            reason="built_in_source_adapter",
        )
        return _evidence(identity, classification), classification
    if route is not None:
        return _board_support(identity, route=route)
    classification = SupportClassification(
        level="unsupported",
        provider_id=identity.provider_id,
        built_in_route=False,
        route_metadata_complete=True,
        job_fetch_validated=False,
        access_required=False,
        transient_failure=False,
        reason="no_built_in_source_adapter",
    )
    return _evidence(identity, classification), classification


def _board_support(
    identity: CandidateIdentity,
    *,
    route: BuiltInRouteHint | None,
) -> tuple[SupportEvidence, SupportClassification]:
    if route is None:
        classification = SupportClassification(
            level="inconclusive",
            provider_id=identity.provider_id,
            built_in_route=False,
            route_metadata_complete=False,
            job_fetch_validated=False,
            access_required=False,
            transient_failure=False,
            reason="no_built_in_route",
        )
        return _evidence(identity, classification), classification
    token_complete = bool(route.token and route.token.strip())
    if route.support == "jobs":
        if not token_complete:
            classification = SupportClassification(
                level="inconclusive",
                provider_id=route.provider_id,
                built_in_route=True,
                route_metadata_complete=False,
                job_fetch_validated=False,
                access_required=False,
                transient_failure=False,
                reason="incomplete_route_metadata",
            )
            return _evidence(identity, classification), classification
        classification = SupportClassification(
            level="authoritative_jobs",
            provider_id=route.provider_id,
            built_in_route=True,
            route_metadata_complete=True,
            job_fetch_validated=True,
            access_required=False,
            transient_failure=False,
            reason="executable_jobs_route",
        )
        return _evidence(identity, classification), classification
    if route.support == "detect":
        classification = SupportClassification(
            level="detect_only",
            provider_id=route.provider_id,
            built_in_route=True,
            route_metadata_complete=token_complete,
            job_fetch_validated=False,
            access_required=False,
            transient_failure=False,
            reason="detect_only_hint",
        )
        return _evidence(identity, classification), classification
    classification = SupportClassification(
        level="unsupported",
        provider_id=route.provider_id,
        built_in_route=False,
        route_metadata_complete=True,
        job_fetch_validated=False,
        access_required=False,
        transient_failure=False,
        reason="unsupported_built_in_route",
    )
    return _evidence(identity, classification), classification


def _evidence(
    identity: CandidateIdentity, classification: SupportClassification
) -> SupportEvidence:
    return SupportEvidence(
        provider_id=classification.provider_id or identity.provider_id,
        built_in_route=classification.built_in_route,
        route_metadata_complete=classification.route_metadata_complete,
        job_fetch_validated=classification.job_fetch_validated,
        access_required=classification.access_required,
        transient_failure=classification.transient_failure,
    )
