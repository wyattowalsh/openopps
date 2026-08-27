"""Order-independent candidate liveness, support, policy, and quarantine join."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

from openopps.discovery.bundle import (
    BundleResource,
    BundleVerificationPolicy,
    compute_manifest_id,
    compute_member_set_sha256,
    verify_bundle,
    write_bundle,
)
from openopps.discovery.canonical import canonical_json_bytes
from openopps.discovery.enumerators import CapturedObservation
from openopps.discovery.identity import (
    IdentityResolution,
    RawOccurrenceInput,
    admit_raw_occurrences,
    normalized_candidates_from_resolution,
    resolve_candidate_identities,
    validate_taxonomy,
)
from openopps.discovery.liveness import (
    LivenessProbeRecord,
    LivenessTransportClient,
    classify_liveness,
    probe_liveness,
)
from openopps.discovery.models import (
    BoundedReason,
    CandidateIdentity,
    CandidateOccurrence,
    EvaluationAxes,
    EvaluationDisposition,
    NormalizedCandidate,
    PolicyAxisSet,
    ScoutCandidateAccounting,
    SupportEvidence,
    SupportState,
    TerminalEvaluation,
)
from openopps.discovery.policy import (
    DiscoveryPolicyBinding,
    V7PolicyDigestBinding,
    bind_candidate_policy,
    encode_discovery_policy_binding,
    evaluate_policy,
)
from openopps.discovery.support import (
    SupportClassification,
    classify_identity_support,
    classify_support,
)


EVALUATION_BUNDLE_PROFILE = ("quarantine-evaluation", "v1")
__all__ = (
    "EVALUATION_BUNDLE_PROFILE",
    "EVALUATION_TOOL_VERSION",
    "EvaluatedCandidate",
    "EvaluationJoinResult",
    "FabricatedEvaluationError",
    "classify_liveness",
    "classify_support",
    "evaluate_disposition",
    "evaluate_occurrences",
    "evaluate_policy",
    "reject_fabricated_evaluation_payload",
    "write_evaluation_bundle",
)
EVALUATION_TOOL_VERSION = "0.1.0"
FORBIDDEN_AUTHORITY_FIELDS = frozenset(
    {
        "approved",
        "disposition",
        "eligibleForReview",
        "grantsAuthority",
        "reviewReceipt",
        "reviewer",
        "revocation",
        "signature",
    }
)


@dataclass(frozen=True, slots=True)
class EvaluatedCandidate:
    candidate: NormalizedCandidate
    evaluation: TerminalEvaluation
    liveness: LivenessProbeRecord
    support: SupportClassification
    policy: DiscoveryPolicyBinding

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate": self.candidate.model_dump(
                mode="json", by_alias=True, round_trip=True
            ),
            "evaluation": self.evaluation.model_dump(
                mode="json", by_alias=True, round_trip=True
            ),
            "liveness": self.liveness.as_dict(),
            "policy": self.policy.as_dict(),
            "support": self.support.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class EvaluationJoinResult:
    identity: IdentityResolution
    candidates: tuple[EvaluatedCandidate, ...]
    accounting: ScoutCandidateAccounting
    bytes: bytes


class FabricatedEvaluationError(ValueError):
    """Hostile or agent-fabricated authority fields are not evaluation input."""


def evaluate_disposition(axes: EvaluationAxes) -> EvaluationDisposition:
    """Apply the normative monotonic precedence independent of input order."""

    if axes.policy == "blocked":
        return EvaluationDisposition.BLOCKED
    if (
        axes.liveness == "inconclusive"
        or axes.support == "inconclusive"
        or axes.policy == "unresolved"
        or axes.taxonomy == "incomplete"
    ):
        return EvaluationDisposition.INCONCLUSIVE
    if axes.support == "unsupported":
        return EvaluationDisposition.UNSUPPORTED
    if axes.already_approved:
        return EvaluationDisposition.ALREADY_APPROVED
    return EvaluationDisposition.PROMOTABLE


def reject_fabricated_evaluation_payload(payload: object) -> None:
    """Prompt-injected approval, review, and disposition fields stay inert."""

    pending: list[object] = [payload]
    seen = 0
    while pending:
        item = pending.pop()
        seen += 1
        if seen > 10_000:
            raise FabricatedEvaluationError("fabricated_payload_budget")
        if isinstance(item, Mapping):
            names = {str(key) for key in item}
            if names & FORBIDDEN_AUTHORITY_FIELDS:
                raise FabricatedEvaluationError("fabricated_authority_field")
            pending.extend(item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend(item)


def evaluate_occurrences(
    occurrences: Iterable[CandidateOccurrence] | Iterable[RawOccurrenceInput],
    *,
    approved_catalog: Iterable[CandidateIdentity],
    taxonomies: Mapping[str, Mapping[str, object]],
    v7_binding: V7PolicyDigestBinding,
    evidence_bytes: bytes,
    observed_at: datetime,
    source_adapter_ids: Iterable[str],
    observations: Mapping[str, CapturedObservation] | None = None,
    transport_client: LivenessTransportClient | None = None,
    untrusted_payloads: Iterable[object] = (),
    positive_policy_axes: PolicyAxisSet | None = None,
) -> EvaluationJoinResult:
    """Normalize, evaluate, and conserve one finite occurrence set."""

    for payload in untrusted_payloads:
        reject_fabricated_evaluation_payload(payload)
    normalized, invalid_ids = _admit_occurrence_inputs(occurrences)
    identity = resolve_candidate_identities(
        normalized,
        approved_catalog=approved_catalog,
        invalid_occurrence_ids=invalid_ids,
    )
    collided = {
        candidate_identity
        for collision in identity.collisions
        for candidate_identity in collision.identities
    }
    approved = set(approved_catalog)
    evaluated: list[EvaluatedCandidate] = []
    captured = observations or {}
    adapters = tuple(source_adapter_ids)
    unique_normalized = normalized_candidates_from_resolution(identity)
    by_identity = {item.identity: item for item in unique_normalized}
    for resolved in identity.candidates:
        candidate = by_identity[resolved.identity]
        taxonomy_values = dict(taxonomies.get(resolved.identity.key, {}))
        taxonomy = (
            validate_taxonomy(taxonomy_values)
            if taxonomy_values
            else validate_taxonomy({})
        )
        support_evidence, support = classify_identity_support(
            resolved.identity,
            source_adapter_ids=adapters,
        )
        support_state = _support_state(support, support_evidence)
        extra_providers = ()
        if support.provider_id.casefold() != resolved.identity.provider_id.casefold():
            extra_providers = (support.provider_id,)
        complete = (
            taxonomy.complete
            and resolved.identity not in collided
            and not extra_providers
        )
        policy = bind_candidate_policy(
            provider_id=resolved.identity.provider_id,
            source_key=resolved.identity.key,
            taxonomy=taxonomy_values,
            v7=v7_binding,
            evidence_bytes=evidence_bytes,
            extra_provider_ids=extra_providers,
        )
        axes_for_policy = policy.axes
        if positive_policy_axes is not None and not policy.deny_matches:
            axes_for_policy = positive_policy_axes
            policy = DiscoveryPolicyBinding(
                v7=policy.v7,
                deny_matches=policy.deny_matches,
                axes=axes_for_policy,
                attribution_requirements=policy.attribution_requirements,
                promotion_requirement=policy.promotion_requirement,
                untrusted_observations=policy.untrusted_observations,
            )
        policy_state = evaluate_policy(
            axes_for_policy,
            deny_overlay_matches=policy.deny_matches,
            untrusted_observations=policy.untrusted_observations,
        )
        observation = captured.get(resolved.identity.canonical_url)
        _evidence, probe = probe_liveness(
            resolved.identity.canonical_url,
            observed_at=observed_at,
            provider_id=resolved.identity.provider_id,
            observation=observation,
            transport_client=transport_client,
        )
        liveness_state = classify_liveness(_evidence).value
        axes = EvaluationAxes(
            liveness=liveness_state,
            support=support_state,
            policy=policy_state.value,
            taxonomy="complete" if complete else "incomplete",
            already_approved=resolved.identity in approved,
        )
        disposition = evaluate_disposition(axes)
        evaluation = TerminalEvaluation(
            candidate_id=candidate.candidate_id,
            axes=axes,
            disposition=disposition.value,
            eligible_for_review=disposition is EvaluationDisposition.PROMOTABLE,
            reason_codes=_reason_codes(
                axes,
                probe=probe,
                support=support,
                collided=resolved.identity in collided,
            ),
        )
        evaluated.append(
            EvaluatedCandidate(
                candidate=candidate,
                evaluation=evaluation,
                liveness=probe,
                support=support,
                policy=policy,
            )
        )
    ordered = tuple(sorted(evaluated, key=lambda item: item.candidate.candidate_id))
    accounting = _scout_accounting(identity, ordered)
    payload = {
        "accounting": accounting.model_dump(
            mode="json", by_alias=True, round_trip=True
        ),
        "candidates": [item.as_dict() for item in ordered],
        "schemaVersion": 1,
    }
    return EvaluationJoinResult(
        identity=identity,
        candidates=ordered,
        accounting=accounting,
        bytes=canonical_json_bytes(payload),
    )


def write_evaluation_bundle(
    output_root: Path,
    result: EvaluationJoinResult,
    *,
    v7_binding: V7PolicyDigestBinding,
    observed_at: datetime,
    configuration_sha256: str,
    execution_id: str,
    now: datetime | None = None,
) -> Path:
    """Write one exact quarantine evaluation graph beneath the owned output root."""

    resources, members = _bundle_members(result, v7_binding=v7_binding)
    observed = observed_at.astimezone(UTC)
    stamp = observed.strftime("%Y-%m-%dT%H:%M:%S")
    if observed.microsecond:
        stamp = observed.strftime("%Y-%m-%dT%H:%M:%S.%f")
    manifest: dict[str, object] = {
        "configurationSha256": configuration_sha256,
        "executionId": execution_id,
        "manifestId": "",
        "memberCount": len(members),
        "members": members,
        "memberSetSha256": compute_member_set_sha256(members),
        "observedAt": f"{stamp}Z",
        "profileId": EVALUATION_BUNDLE_PROFILE[0],
        "profileVersion": EVALUATION_BUNDLE_PROFILE[1],
        "runState": "complete",
        "schemaVersion": "openopps.discovery.bundle.v1",
        "toolVersion": EVALUATION_TOOL_VERSION,
    }
    manifest["manifestId"] = compute_manifest_id(manifest)
    clock = now or observed_at
    policy = BundleVerificationPolicy(
        max_evidence_age=timedelta(hours=48),
        now=clock.astimezone(UTC),
        replayed_manifest_ids=frozenset(),
        revoked_manifest_ids=frozenset(),
        supported_profiles=frozenset({EVALUATION_BUNDLE_PROFILE}),
        supported_schema_versions=frozenset({"openopps.discovery.bundle.v1"}),
        required_member_roles=frozenset({"evidence"}),
        supported_member_roles=frozenset({"evidence"}),
        canonical_json_roles=frozenset(),
    )
    published = write_bundle(
        output_root,
        manifest=manifest,
        resources=resources,
        verification_policy=policy,
    )
    verify_bundle(published, policy=policy)
    return published


def _bundle_members(
    result: EvaluationJoinResult,
    *,
    v7_binding: V7PolicyDigestBinding,
) -> tuple[tuple[BundleResource, ...], list[dict[str, object]]]:
    files: dict[str, bytes] = {
        "accounting/scout-candidate-accounting.json": canonical_json_bytes(
            result.accounting.model_dump(mode="json", by_alias=True, round_trip=True)
        ),
        "evaluations/join.json": result.bytes,
        "policy/v7-digest-binding.json": canonical_json_bytes(v7_binding.as_dict()),
    }
    if result.candidates:
        files["policy/discovery-policy-binding.json"] = encode_discovery_policy_binding(
            result.candidates[0].policy
        )
    resources: list[BundleResource] = []
    members: list[dict[str, object]] = []
    for path in sorted(files):
        data = files[path]
        digest = sha256(data).hexdigest()
        resources.append(
            BundleResource(
                data=data,
                media_type="application/json",
                path=path,
                provenance_id=f"sha256:{digest}",
                role="evidence",
            )
        )
        members.append(
            {
                "mediaType": "application/json",
                "path": path,
                "provenanceId": f"sha256:{digest}",
                "role": "evidence",
                "sha256": digest,
                "sizeBytes": len(data),
            }
        )
    return tuple(resources), members


def _admit_occurrence_inputs(
    occurrences: Iterable[CandidateOccurrence] | Iterable[RawOccurrenceInput],
) -> tuple[tuple[CandidateOccurrence, ...], tuple[str, ...]]:
    values = tuple(occurrences)
    if values and isinstance(values[0], RawOccurrenceInput):
        raw_records: list[RawOccurrenceInput] = []
        for item in values:
            if isinstance(item, RawOccurrenceInput):
                raw_records.append(item)
        return admit_raw_occurrences(raw_records)
    normalized: list[CandidateOccurrence] = []
    for item in values:
        if isinstance(item, CandidateOccurrence):
            normalized.append(item)
    return tuple(normalized), ()


def _support_state(
    classification: SupportClassification, evidence: SupportEvidence
) -> SupportState:
    del evidence
    if classification.transient_failure or classification.level == "inconclusive":
        return "inconclusive"
    if classification.level == "detect_only":
        return "inconclusive"
    if classification.access_required or classification.level == "unsupported":
        return "unsupported"
    if classification.level in {
        "source_support",
        "executable_route",
        "authoritative_jobs",
    }:
        if not classification.route_metadata_complete:
            return "inconclusive"
        return "supported"
    return "inconclusive"


def _reason_codes(
    axes: EvaluationAxes,
    *,
    probe: LivenessProbeRecord,
    support: SupportClassification,
    collided: bool,
) -> tuple[BoundedReason, ...]:
    disposition = evaluate_disposition(axes)
    if disposition is EvaluationDisposition.PROMOTABLE:
        return ()
    codes: list[BoundedReason] = []
    if axes.policy == "blocked":
        for name in ("access", "license", "redistribution", "sync", "publication"):
            if getattr(axes, "policy") == "blocked":
                break
        codes.append(BoundedReason.ACCESS_BLOCKED)
        if "license" in (support.reason,):
            codes.append(BoundedReason.LICENSE_BLOCKED)
    if axes.policy == "unresolved":
        codes.append(BoundedReason.POLICY_UNRESOLVED)
    if axes.liveness == "inconclusive":
        codes.append(
            probe.reason_code
            if probe.reason_code is not BoundedReason.NONE
            else BoundedReason.EVIDENCE_INCOMPLETE
        )
    if axes.support == "inconclusive":
        codes.append(BoundedReason.SUPPORT_UNRESOLVED)
    if axes.support == "unsupported":
        codes.append(BoundedReason.UNSUPPORTED_ROUTE)
    if axes.taxonomy == "incomplete":
        codes.append(BoundedReason.EVIDENCE_INCOMPLETE)
    if collided:
        codes.append(BoundedReason.COLLISION_UNRESOLVED)
    if axes.already_approved and disposition is EvaluationDisposition.ALREADY_APPROVED:
        codes.append(BoundedReason.NONE)
    unique = tuple(sorted(set(codes), key=lambda item: item.value))
    if not unique:
        return (BoundedReason.EVIDENCE_INCOMPLETE,)
    return unique


def _scout_accounting(
    identity: IdentityResolution,
    evaluated: Sequence[EvaluatedCandidate],
) -> ScoutCandidateAccounting:
    dispositions = [item.evaluation.disposition for item in evaluated]
    already = sum(item == "already_approved" for item in dispositions)
    promotable = sum(item == "promotable" for item in dispositions)
    blocked = sum(item == "blocked" for item in dispositions)
    unsupported = sum(item == "unsupported" for item in dispositions)
    inconclusive = sum(item == "inconclusive" for item in dispositions)
    quarantined = promotable + blocked + unsupported + inconclusive
    return ScoutCandidateAccounting(
        observed_candidate_occurrences=identity.observed_occurrences,
        invalid_occurrences=identity.invalid_occurrences,
        normalized_occurrences=identity.normalized_occurrences,
        duplicate_occurrences=identity.duplicate_occurrences,
        unique_candidates=identity.unique_candidates,
        already_approved=already,
        quarantined_candidates=quarantined,
        promotable=promotable,
        blocked=blocked,
        unsupported=unsupported,
        inconclusive=inconclusive,
    )
