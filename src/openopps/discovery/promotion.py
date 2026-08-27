"""Deterministic promotion authority, ledger, and recovery decision seams."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
import hashlib
import json
from pathlib import Path
from typing import Any, Literal
import unicodedata

from pydantic import ValidationError

from openopps.discovery.bundle import BundleVerificationPolicy, VerifiedBundle, verify_bundle
from openopps.discovery.canonical import CanonicalJSONError, canonical_json_bytes
from openopps.discovery.identity import candidate_identity_id, normalize_candidate_identity
from openopps.discovery.inventory import read_packaged_catalog_bytes
from openopps.discovery.models import (
    ApplyJournal,
    ApprovedIngestionSelectorEnvelope,
    CandidateIdentity,
    DiscoveryPromotionPolicyDecision,
    EvidenceOnlyDecisionReceipt,
    PromotionIntent,
    PromotionLedgerEvent,
    PromotionSelection,
    TerminalEvaluation,
)
from openopps.discovery.policy import V7PolicyDigestBinding


_FORBIDDEN_CANDIDATE_AUTHORITY_MARKERS = frozenset(
    {
        "approval",
        "approved",
        "decisionprovenance",
        "maintainerdecision",
        "receipt",
        "review",
        "reviewer",
        "revocation",
        "revoked",
        "signature",
    }
)


class CandidateAuthorityError(ValueError):
    """Candidate data attempted to carry maintainer review authority."""


class PromotionDecisionError(ValueError):
    """A separately authored decision is missing exact reviewed provenance."""


class PromotionLedgerError(ValueError):
    """The append-only decision ledger cannot be proven closed."""


class RecoveryAction(StrEnum):
    FINALIZE = "finalize"
    RESTORE_AND_REVOKE = "restore_and_revoke"


def validate_candidate_manifest_authority(payload: Mapping[str, object]) -> None:
    """Reject review authority at every depth of untrusted candidate data."""

    def visit(value: object) -> None:
        if isinstance(value, Mapping):
            for field, nested in value.items():
                normalized = "".join(
                    character
                    for character in unicodedata.normalize(
                        "NFKC", str(field)
                    ).casefold()
                    if character.isalnum()
                )
                if any(
                    marker in normalized
                    for marker in _FORBIDDEN_CANDIDATE_AUTHORITY_MARKERS
                ):
                    raise CandidateAuthorityError(
                        "candidate authority field is forbidden"
                    )
                visit(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                visit(nested)

    visit(payload)


def compute_promotion_intent_digest(intent: PromotionIntent) -> str:
    """Hash canonical semantic intent fields, which cannot contain this digest."""

    return hashlib.sha256(
        canonical_json_bytes(intent.model_dump(mode="json", by_alias=True))
    ).hexdigest()


def validate_promotion_decision(
    payload: Mapping[str, object],
    *,
    expected_intent: PromotionIntent,
    invocation_mode: str,
) -> Mapping[str, object]:
    if invocation_mode != "maintainer":
        raise PromotionDecisionError(
            "only maintainer invocation may author a positive decision"
        )
    expected = expected_intent.model_dump(mode="json", by_alias=True)
    for field, value in expected.items():
        if field not in payload or payload[field] != value:
            raise PromotionDecisionError(f"decision {field} does not match review")
    expected_digest = compute_promotion_intent_digest(expected_intent)
    if payload.get("promotionIntentDigest") != expected_digest:
        raise PromotionDecisionError("promotionIntentDigest does not match review")
    decision_id = payload.get("decisionId")
    if not isinstance(decision_id, str) or not decision_id:
        raise PromotionDecisionError("decisionId is required")
    try:
        decision = DiscoveryPromotionPolicyDecision.model_validate_json(
            canonical_json_bytes(payload),
            strict=True,
            by_alias=True,
            by_name=False,
        )
    except (CanonicalJSONError, ValidationError):
        raise PromotionDecisionError(
            "decision violates the canonical promotion policy contract"
        ) from None
    decision_intent = PromotionIntent.model_validate(
        {field: getattr(decision, field) for field in PromotionIntent.model_fields},
        strict=True,
    )
    if decision_intent != expected_intent:
        raise PromotionDecisionError("decision intent does not match review")
    return decision.model_dump(mode="json", by_alias=True)


def _event_payload(event: PromotionLedgerEvent) -> dict[str, Any]:
    payload = event.model_dump(mode="json", by_alias=True)
    payload.pop("eventDigest")
    return payload


def _event_digest(event: PromotionLedgerEvent) -> str:
    return hashlib.sha256(canonical_json_bytes(_event_payload(event))).hexdigest()


def _validate_sequence(events: Sequence[PromotionLedgerEvent]) -> None:
    states: dict[str, tuple[str, str]] = {}
    intents: dict[str, str] = {}
    previous: str | None = None
    for expected_sequence, event in enumerate(events, start=1):
        if event.sequence != expected_sequence:
            raise PromotionLedgerError("ledger sequence is not contiguous")
        if event.predecessor_digest != previous:
            raise PromotionLedgerError("ledger predecessor hash chain is open")
        if _event_digest(event) != event.event_digest:
            raise PromotionLedgerError("ledger event digest does not match bytes")
        event_intent = PromotionIntent(
            head_sha=event.head_sha,
            manifest_digest=event.manifest_digest,
            selection_digest=event.selection_digest,
            resources_digest=event.resources_digest,
            profile_digest=event.profile_digest,
            policy_inputs_digest=event.policy_inputs_digest,
            catalog_before_digest=event.catalog_before_digest,
            catalog_after_digest=event.catalog_after_digest,
            promotion_digest=event.promotion_digest,
            required_operations=event.required_operations,
        )
        if (
            compute_promotion_intent_digest(event_intent)
            != event.promotion_intent_digest
        ):
            raise PromotionLedgerError(
                "ledger promotion intent digest does not match reviewed components"
            )
        prior = states.get(event.decision_id)
        if prior is None:
            if event.state != "reserved":
                raise PromotionLedgerError("decision must begin with reserved")
            owner = intents.get(event.promotion_intent_digest)
            if owner is not None and owner != event.decision_id:
                raise PromotionLedgerError("promotion intent replay")
            intents[event.promotion_intent_digest] = event.decision_id
        else:
            prior_state, prior_intent = prior
            if event.promotion_intent_digest != prior_intent:
                raise PromotionLedgerError(
                    "decision intent changed across ledger events"
                )
            allowed = {
                "reserved": {"applied", "revoked"},
                "applied": {"revoked"},
                "revoked": set(),
            }[prior_state]
            if event.state not in allowed:
                raise PromotionLedgerError(
                    "ledger decision state transition is invalid"
                )
        states[event.decision_id] = (event.state, event.promotion_intent_digest)
        previous = event.event_digest


def validate_ledger_chain(
    events: Sequence[PromotionLedgerEvent],
    *,
    reachable_history: Sequence[PromotionLedgerEvent],
) -> None:
    """Validate current plus reachable history as one immutable chain."""

    combined = (*reachable_history, *events)
    _validate_sequence(combined)


def _latest_states(
    events: Sequence[PromotionLedgerEvent],
) -> dict[str, PromotionLedgerEvent]:
    result: dict[str, PromotionLedgerEvent] = {}
    for event in events:
        result[event.decision_id] = event
    return result


def append_ledger_event(
    *,
    current_events: Sequence[PromotionLedgerEvent],
    reachable_history: Sequence[PromotionLedgerEvent],
    decision_id: str,
    intent: PromotionIntent,
    state: str,
) -> PromotionLedgerEvent:
    combined = (*reachable_history, *current_events)
    _validate_sequence(combined)
    if state not in {"reserved", "applied", "revoked"}:
        raise PromotionLedgerError("ledger state is unsupported")
    intent_digest = compute_promotion_intent_digest(intent)
    latest = _latest_states(combined)
    prior = latest.get(decision_id)
    if state == "reserved":
        for event in latest.values():
            if (
                event.state == "reserved"
                and event.head_sha == intent.head_sha
                and event.catalog_before_digest == intent.catalog_before_digest
            ):
                raise PromotionLedgerError(
                    "nonterminal reservation owns this HEAD and catalog tuple"
                )
        if prior is not None:
            raise PromotionLedgerError("decision replay is forbidden")
        if any(event.promotion_intent_digest == intent_digest for event in combined):
            raise PromotionLedgerError("promotion intent replay is forbidden")
    else:
        if prior is None:
            raise PromotionLedgerError("decision has no reservation")
        if prior.promotion_intent_digest != intent_digest:
            raise PromotionLedgerError(
                "decision promotion intent does not match reservation"
            )
        allowed = {
            "reserved": {"applied", "revoked"},
            "applied": {"revoked"},
            "revoked": set(),
        }[prior.state]
        if state not in allowed:
            raise PromotionLedgerError("ledger decision state transition is invalid")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "sequence": len(combined) + 1,
        "decision_id": decision_id,
        "state": state,
        "promotion_intent_digest": intent_digest,
        **intent.model_dump(mode="python"),
        "predecessor_digest": combined[-1].event_digest if combined else None,
        "event_digest": "0" * 64,
    }
    provisional = PromotionLedgerEvent.model_validate(payload)
    payload["event_digest"] = _event_digest(provisional)
    return PromotionLedgerEvent.model_validate(payload)


def choose_recovery_action(
    journal: ApplyJournal,
    observed_path_state: Mapping[str, Mapping[str, object]],
) -> RecoveryAction:
    expected_paths = {entry.path for entry in journal.entries}
    if set(observed_path_state) != expected_paths:
        return RecoveryAction.RESTORE_AND_REVOKE
    for entry in journal.entries:
        observed = observed_path_state[entry.path]
        expected = {
            "exists": entry.after.exists,
            "mode": entry.after.mode,
            "sha256": entry.after.sha256,
        }
        if dict(observed) != expected:
            return RecoveryAction.RESTORE_AND_REVOKE
    return RecoveryAction.FINALIZE


def transition_journal(journal: ApplyJournal, next_phase: str) -> ApplyJournal:
    transitions = {"prepared": "applying", "applying": "finalizing"}
    if transitions.get(journal.phase) != next_phase:
        raise ValueError("journal phase transition is invalid")
    return journal.model_copy(update={"phase": next_phase})


def validate_applied_commit(
    journal: ApplyJournal,
    *,
    changed_paths: frozenset[str],
    reservation_parent_present: bool,
) -> None:
    expected_paths = frozenset(entry.path for entry in journal.entries)
    if changed_paths != expected_paths:
        raise ValueError("applied commit path closure does not match journal")
    if not reservation_parent_present:
        raise ValueError("applied commit reservation parent is missing")


VALIDATOR_VERSION = "openopps.discovery.promotion/1"
ENVELOPE_FORBIDDEN_CLASSES = frozenset(
    {
        "absent",
        "blocked",
        "duplicate",
        "non_owned",
        "persisted_only",
        "quarantined",
        "v7_public_selector_substitution",
    }
)
RECEIPT_GRANTS_AUTHORITY = False


class PromotionPreviewError(ValueError):
    """Preview, selection, or collision validation cannot close."""


class EnvelopeValidationError(ValueError):
    """The private approved-ingestion envelope is not an exact closed set."""


@dataclass(frozen=True, slots=True)
class PromotionCandidate:
    identity: CandidateIdentity
    evaluation: TerminalEvaluation

    @property
    def candidate_id(self) -> str:
        return candidate_identity_id(self.identity)


@dataclass(frozen=True, slots=True)
class ProposedSourceRecord:
    key: str
    url: str
    provider_id: str
    version: Mapping[str, object]
    raw_metadata: Mapping[str, object]
    package_owner: str

    def as_catalog_entry(self) -> dict[str, object]:
        metadata = {
            **dict(self.raw_metadata),
            "packageOwner": self.package_owner,
        }
        return {
            "key": self.key,
            "provider_id": self.provider_id,
            "raw_metadata": metadata,
            "url": self.url,
            "version": dict(self.version),
        }


@dataclass(frozen=True, slots=True)
class PromotionPreview:
    selection: PromotionSelection
    catalog_before_digest: str
    catalog_after_digest: str
    source_key_digest: str
    policy_inputs_digest: str
    promotion_digest: str
    proposed_records: tuple[ProposedSourceRecord, ...]
    catalog_after: bytes
    delta: bytes
    intent: PromotionIntent


def build_promotion_selection(
    manifest_digest: str,
    candidate_ids: Sequence[str],
) -> PromotionSelection:
    """P601: selection contains only verified manifest and candidate identities."""

    identities = tuple(candidate_ids)
    if identities != tuple(sorted(set(identities))):
        raise PromotionPreviewError("candidate IDs must be sorted and unique")
    if any(not item for item in identities):
        raise PromotionPreviewError("candidate IDs must be non-empty")
    digest = hashlib.sha256(
        canonical_json_bytes(
            {
                "candidateIds": list(identities),
                "manifestDigest": manifest_digest,
            }
        )
    ).hexdigest()
    return PromotionSelection(
        manifest_digest=manifest_digest,
        candidate_ids=identities,
        selection_digest=digest,
    )


def reverify_promotion_bundle(
    root: Path,
    *,
    policy: BundleVerificationPolicy,
    expected_manifest_digest: str,
) -> VerifiedBundle:
    """P602: reverify canonical bundle bytes before selection."""

    verified = verify_bundle(root, policy=policy)
    if verified.manifest_id != expected_manifest_digest:
        raise PromotionPreviewError("manifest digest does not match selection")
    return verified


def revalidate_selected_candidates(
    candidates: Sequence[PromotionCandidate],
    *,
    selected_ids: Sequence[str],
) -> tuple[PromotionCandidate, ...]:
    """P603: selected candidates stay live, supported, complete, and collision-free.

    Positive policy allow is not granted here. Production allow is a separately
    authored DiscoveryPromotionPolicyDecision. This seam never accepts
    positive_policy_axes.
    """

    selected = tuple(selected_ids)
    by_id = {item.candidate_id: item for item in candidates}
    if len(by_id) != len(tuple(candidates)):
        raise PromotionPreviewError("promotion candidates must be unique")
    if set(selected) != set(by_id) or selected != tuple(sorted(selected)):
        raise PromotionPreviewError("selection does not match candidate identities")
    ordered: list[PromotionCandidate] = []
    for candidate_id in selected:
        item = by_id[candidate_id]
        if item.evaluation.candidate_id != candidate_id:
            raise PromotionPreviewError("evaluation identity does not match candidate")
        evaluation = item.evaluation
        if evaluation.disposition != "promotable" or not evaluation.eligible_for_review:
            raise PromotionPreviewError("selected candidate is not eligible for review")
        if evaluation.axes.liveness != "live":
            raise PromotionPreviewError("selected candidate is not live")
        if evaluation.axes.support != "supported":
            raise PromotionPreviewError("selected candidate is not supported")
        if evaluation.axes.taxonomy != "complete":
            raise PromotionPreviewError("selected candidate taxonomy is incomplete")
        if evaluation.axes.policy == "blocked":
            raise PromotionPreviewError("selected candidate is policy blocked")
        ordered.append(item)
    identities = tuple(item.identity for item in ordered)
    for index, left in enumerate(identities):
        for right in identities[index + 1 :]:
            reasons = _identity_collision_reasons(left, right)
            if reasons:
                raise PromotionPreviewError("selected candidates collide")
    return tuple(ordered)


def _identity_collision_reasons(
    left: CandidateIdentity,
    right: CandidateIdentity,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if left.key == right.key:
        reasons.append("exact_key")
    if left.url == right.url:
        reasons.append("exact_url")
    if left.canonical_url == right.canonical_url:
        reasons.append("canonical_url")
    if (
        left.provider_id == right.provider_id
        and left.provider_token is not None
        and right.provider_token is not None
        and left.provider_token == right.provider_token
        and left.key != right.key
    ):
        reasons.append("provider_token")
    return tuple(reasons)


def bind_catalog_fingerprints(catalog_before: bytes) -> tuple[str, str, tuple[str, ...]]:
    """P604: bind catalog-before fingerprint and sorted source keys."""

    readback = read_packaged_catalog_bytes(catalog_before)
    file_digest = hashlib.sha256(catalog_before).hexdigest()
    payload = json.loads(catalog_before.decode("utf-8"))
    keys = tuple(str(entry["key"]) for entry in payload["entries"])
    return readback.fingerprint, file_digest, keys


def bind_policy_input_digests(
    v7: V7PolicyDigestBinding,
    *,
    positive_decision_digest: str | None = None,
) -> str:
    """P605: bind read-only v7 policy digests plus optional decision digest."""

    payload = dict(v7.as_dict())
    payload["positiveDecisionDigest"] = positive_decision_digest
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def render_proposed_source_records(
    candidates: Sequence[PromotionCandidate],
    *,
    package_owner: str,
) -> tuple[ProposedSourceRecord, ...]:
    """P606: render proposed catalog records in memory with package ownership."""

    if not package_owner:
        raise PromotionPreviewError("package owner is required")
    records: list[ProposedSourceRecord] = []
    for item in candidates:
        records.append(
            ProposedSourceRecord(
                key=item.identity.key,
                url=item.identity.url,
                provider_id=item.identity.provider_id,
                version={},
                raw_metadata={"owner": item.identity.owner},
                package_owner=package_owner,
            )
        )
    return tuple(records)


def reject_promotion_collisions(
    proposed: Sequence[ProposedSourceRecord],
    *,
    existing_identities: Sequence[CandidateIdentity],
    existing_owner_by_key: Mapping[str, str],
) -> None:
    """P607: reject key, URL, canonical URL, provider-token, and owner collisions."""

    proposed_identities: list[CandidateIdentity] = []
    for record in proposed:
        identity = normalize_candidate_identity(
            key=record.key,
            url=record.url,
            provider_id=record.provider_id,
            provider_token=None,
            owner=str(record.raw_metadata.get("owner") or "proposed"),
        )
        if record.key in existing_owner_by_key:
            existing_owner = existing_owner_by_key[record.key]
            if existing_owner != record.package_owner:
                raise PromotionPreviewError("module-owner collision")
            raise PromotionPreviewError("key collision")
        for existing in existing_identities:
            if _identity_collision_reasons(identity, existing):
                raise PromotionPreviewError("catalog identity collision")
        for prior in proposed_identities:
            if _identity_collision_reasons(identity, prior):
                raise PromotionPreviewError("proposed identity collision")
        proposed_identities.append(identity)


def _packaged_fingerprint(entries: Sequence[Mapping[str, object]]) -> str:
    payload = json.dumps(
        list(entries),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def render_catalog_after(
    catalog_before: bytes,
    proposed: Sequence[ProposedSourceRecord],
) -> bytes:
    payload = json.loads(catalog_before.decode("utf-8"))
    entries = [dict(entry) for entry in payload["entries"]]
    entries.extend(record.as_catalog_entry() for record in proposed)
    entries.sort(key=lambda entry: str(entry["key"]))
    fingerprint = _packaged_fingerprint(entries)
    rendered = {
        "count": len(entries),
        "entries": entries,
        "fingerprint": fingerprint,
        "version": payload["version"],
    }
    encoded = json.dumps(
        rendered,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    read_packaged_catalog_bytes(encoded)
    return encoded


def compute_promotion_digests(
    *,
    catalog_before: bytes,
    catalog_after: bytes,
    selection: PromotionSelection,
    policy_inputs_digest: str,
) -> dict[str, str]:
    """P608: catalog-after, source-key, selection, and promotion digests."""

    after = read_packaged_catalog_bytes(catalog_after)
    payload = json.loads(catalog_after.decode("utf-8"))
    keys = [str(entry["key"]) for entry in payload["entries"]]
    source_key_digest = hashlib.sha256(canonical_json_bytes(keys)).hexdigest()
    catalog_after_digest = hashlib.sha256(catalog_after).hexdigest()
    catalog_before_digest = hashlib.sha256(catalog_before).hexdigest()
    promotion_digest = hashlib.sha256(
        canonical_json_bytes(
            {
                "catalogAfterDigest": catalog_after_digest,
                "catalogBeforeDigest": catalog_before_digest,
                "manifestDigest": selection.manifest_digest,
                "policyInputsDigest": policy_inputs_digest,
                "selectionDigest": selection.selection_digest,
                "sourceKeyDigest": source_key_digest,
            }
        )
    ).hexdigest()
    return {
        "catalogAfterDigest": catalog_after_digest,
        "catalogBeforeDigest": catalog_before_digest,
        "catalogFingerprint": after.fingerprint,
        "promotionDigest": promotion_digest,
        "selectionDigest": selection.selection_digest,
        "sourceKeyDigest": source_key_digest,
    }


def render_preview_delta(
    before_bytes: Mapping[str, bytes | None],
    after_bytes: Mapping[str, bytes | None],
) -> bytes:
    """P609: reviewable dry-run repository delta without editing files."""

    paths = tuple(sorted(set(before_bytes) | set(after_bytes)))
    changes = []
    for path in paths:
        before = before_bytes.get(path)
        after = after_bytes.get(path)
        changes.append(
            {
                "afterSha256": None if after is None else hashlib.sha256(after).hexdigest(),
                "afterSize": 0 if after is None else len(after),
                "beforeSha256": (
                    None if before is None else hashlib.sha256(before).hexdigest()
                ),
                "beforeSize": 0 if before is None else len(before),
                "path": path,
            }
        )
    return canonical_json_bytes({"changes": changes, "schemaVersion": 1})


def preview_promotion(
    *,
    manifest_digest: str,
    candidates: Sequence[PromotionCandidate],
    catalog_before: bytes,
    v7: V7PolicyDigestBinding,
    head_sha: str,
    package_owner: str,
    existing_identities: Sequence[CandidateIdentity],
    existing_owner_by_key: Mapping[str, str],
    resources_digest: str,
    profile_digest: str,
    extra_after_paths: Mapping[str, bytes] | None = None,
    extra_before_paths: Mapping[str, bytes | None] | None = None,
    required_operations: tuple[
        Literal["access", "license", "publication", "redistribution", "sync"],
        ...,
    ] = (
        "access",
        "license",
        "publication",
        "redistribution",
        "sync",
    ),
) -> PromotionPreview:
    """Deterministic non-mutating promotion preview."""

    ordered_ids = tuple(sorted(item.candidate_id for item in candidates))
    selection = build_promotion_selection(manifest_digest, ordered_ids)
    selected = revalidate_selected_candidates(candidates, selected_ids=ordered_ids)
    proposed = render_proposed_source_records(selected, package_owner=package_owner)
    reject_promotion_collisions(
        proposed,
        existing_identities=existing_identities,
        existing_owner_by_key=existing_owner_by_key,
    )
    catalog_after = (
        catalog_before
        if not proposed
        else render_catalog_after(catalog_before, proposed)
    )
    policy_inputs_digest = bind_policy_input_digests(v7)
    digests = compute_promotion_digests(
        catalog_before=catalog_before,
        catalog_after=catalog_after,
        selection=selection,
        policy_inputs_digest=policy_inputs_digest,
    )
    catalog_path = (
        "src/openopps/providers/sources/data/portfolio_source_catalog.json"
    )
    after_paths: dict[str, bytes | None] = {
        catalog_path: catalog_after,
        **dict(extra_after_paths or {}),
    }
    before_paths: dict[str, bytes | None] = {
        catalog_path: catalog_before,
        **{path: None for path in (extra_after_paths or ())},
        **dict(extra_before_paths or {}),
    }
    delta = render_preview_delta(before_paths, after_paths)
    intent = PromotionIntent(
        head_sha=head_sha,
        manifest_digest=manifest_digest,
        selection_digest=selection.selection_digest,
        resources_digest=resources_digest,
        profile_digest=profile_digest,
        policy_inputs_digest=policy_inputs_digest,
        catalog_before_digest=digests["catalogBeforeDigest"],
        catalog_after_digest=digests["catalogAfterDigest"],
        promotion_digest=digests["promotionDigest"],
        required_operations=required_operations,
    )
    return PromotionPreview(
        selection=selection,
        catalog_before_digest=digests["catalogBeforeDigest"],
        catalog_after_digest=digests["catalogAfterDigest"],
        source_key_digest=digests["sourceKeyDigest"],
        policy_inputs_digest=policy_inputs_digest,
        promotion_digest=digests["promotionDigest"],
        proposed_records=proposed,
        catalog_after=catalog_after,
        delta=delta,
        intent=intent,
    )


def build_evidence_receipt(
    decision: Mapping[str, object],
    *,
    validated_at: datetime,
) -> EvidenceOnlyDecisionReceipt:
    """P610: generated receipt is evidence, not authority."""

    dumped = dict(decision)
    decision_digest = hashlib.sha256(canonical_json_bytes(dumped)).hexdigest()
    return EvidenceOnlyDecisionReceipt(
        schema_version=1,
        decision_id=str(dumped["decisionId"]),
        promotion_intent_digest=str(dumped["promotionIntentDigest"]),
        decision_digest=decision_digest,
        validator_version=VALIDATOR_VERSION,
        validated_at=validated_at.astimezone(UTC),
        grants_authority=False,
    )


def compute_envelope_id(payload: Mapping[str, object]) -> str:
    body = {key: value for key, value in payload.items() if key != "envelopeId"}
    return hashlib.sha256(canonical_json_bytes(body)).hexdigest()


def build_approved_envelope(
    *,
    source_keys: Sequence[str],
    packaged_catalog_fingerprint: str,
    catalog_content_digest: str,
    catalog_tree_digest: str,
    v7: V7PolicyDigestBinding,
    supplementary_policy_digest: str,
    promotion_digest: str,
    key_classes: Mapping[str, str] | None = None,
) -> ApprovedIngestionSelectorEnvelope:
    """P614/P615: private envelope; rejects quarantined and selector substitution."""

    keys = tuple(source_keys)
    validate_envelope_keys(keys, key_classes=key_classes or {})
    source_key_digest = hashlib.sha256(canonical_json_bytes(list(keys))).hexdigest()
    if v7.public_selector_sha256 is not None and v7.public_selector_sha256 == promotion_digest:
        raise EnvelopeValidationError("v7 public selector substitution is forbidden")
    provisional = {
        "schemaVersion": 1,
        "sourceKeys": list(keys),
        "sourceCount": len(keys),
        "sourceKeyDigest": source_key_digest,
        "packagedCatalogFingerprint": packaged_catalog_fingerprint,
        "catalogContentDigest": catalog_content_digest,
        "catalogTreeDigest": catalog_tree_digest,
        "v7PolicyCodeDigest": v7.policy_code_sha256,
        "v7PolicySchemaDigest": v7.policy_schema_sha256,
        "v7PolicyEvidenceDigest": v7.policy_evidence_sha256,
        "v7PolicyCorpusDigest": v7.policy_corpus_sha256,
        "supplementaryPolicyDigest": supplementary_policy_digest,
        "promotionDigest": promotion_digest,
    }
    envelope_id = compute_envelope_id(provisional)
    return ApprovedIngestionSelectorEnvelope.model_validate_json(
        canonical_json_bytes({**provisional, "envelopeId": envelope_id}),
        strict=True,
        by_alias=True,
        by_name=False,
    )


def validate_envelope_keys(
    source_keys: Sequence[str],
    *,
    key_classes: Mapping[str, str],
) -> None:
    """Reject persisted-only, quarantined, blocked, absent, duplicate, or non-owned keys."""

    keys = tuple(source_keys)
    if keys != tuple(sorted(set(keys))):
        raise EnvelopeValidationError("envelope source keys must be sorted and unique")
    if not keys:
        raise EnvelopeValidationError("envelope source keys are absent")
    for key in keys:
        classification = key_classes.get(key, "owned")
        if classification in ENVELOPE_FORBIDDEN_CLASSES:
            raise EnvelopeValidationError("envelope source key class is forbidden")
        if classification == "v7_public_selector":
            raise EnvelopeValidationError("v7 public selector substitution is forbidden")
