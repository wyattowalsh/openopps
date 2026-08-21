"""Deterministic promotion authority, ledger, and recovery decision seams."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
import hashlib
from typing import Any
import unicodedata

from pydantic import ValidationError

from openopps.discovery.canonical import CanonicalJSONError, canonical_json_bytes
from openopps.discovery.models import (
    ApplyJournal,
    DiscoveryPromotionPolicyDecision,
    PromotionIntent,
    PromotionLedgerEvent,
)


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
