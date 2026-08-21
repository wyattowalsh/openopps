"""Order-independent candidate liveness, support, policy, and disposition."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

from openopps.discovery.models import (
    EvaluationAxes,
    LivenessEvidence,
    PolicyAxisSet,
    SupportEvidence,
)


class CandidateDisposition(StrEnum):
    ALREADY_APPROVED = "already_approved"
    PROMOTABLE = "promotable"
    BLOCKED = "blocked"
    UNSUPPORTED = "unsupported"
    INCONCLUSIVE = "inconclusive"


class PolicyDisposition(StrEnum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    UNRESOLVED = "unresolved"


class LivenessDisposition(StrEnum):
    LIVE = "live"
    INCONCLUSIVE = "inconclusive"


class SupportDisposition(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    INCONCLUSIVE = "inconclusive"


def evaluate_disposition(axes: EvaluationAxes) -> CandidateDisposition:
    """Apply the normative monotonic precedence independent of input order."""

    if axes.policy == "blocked":
        return CandidateDisposition.BLOCKED
    if (
        axes.liveness == "inconclusive"
        or axes.support == "inconclusive"
        or axes.policy == "unresolved"
        or axes.taxonomy == "incomplete"
    ):
        return CandidateDisposition.INCONCLUSIVE
    if axes.support == "unsupported":
        return CandidateDisposition.UNSUPPORTED
    if axes.already_approved:
        return CandidateDisposition.ALREADY_APPROVED
    return CandidateDisposition.PROMOTABLE


def evaluate_policy(
    axes: PolicyAxisSet,
    *,
    deny_overlay_matches: Iterable[str] = (),
    untrusted_observations: Iterable[str] = (),
) -> PolicyDisposition:
    """Require all five positive axes; observations never grant permission."""

    del untrusted_observations
    if tuple(deny_overlay_matches):
        return PolicyDisposition.BLOCKED
    states = (
        axes.access,
        axes.license,
        axes.redistribution,
        axes.sync,
        axes.publication,
    )
    if "blocked" in states:
        return PolicyDisposition.BLOCKED
    if "unresolved" in states:
        return PolicyDisposition.UNRESOLVED
    return PolicyDisposition.ALLOWED


def classify_liveness(evidence: LivenessEvidence) -> LivenessDisposition:
    if evidence.response_class == "expected_payload" and evidence.expected_structure:
        return LivenessDisposition.LIVE
    return LivenessDisposition.INCONCLUSIVE


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
