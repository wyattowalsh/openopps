"""Stable join of independent channel replay receipts (E451-E455)."""

from __future__ import annotations

from collections.abc import Sequence
from hashlib import sha256
from dataclasses import dataclass
from typing import Literal

from openopps.discovery.api import encode_channel_replay_receipt
from openopps.discovery.canonical import canonical_json_bytes, decode_canonical_json
from openopps.discovery.enumerators import CHANNEL_ORDER, EnumeratorError
from openopps.discovery.models import (
    CandidateOccurrence,
    ChannelReplayReceipt,
    ObservedResource,
    ProvenanceClaim,
)


WholeRunState = Literal["complete", "partial", "failed"]


@dataclass(frozen=True, slots=True)
class MergedDiscoveryReceipt:
    """Deterministic merge of finite independently replayable channels."""

    schema_version: Literal[1]
    whole_run_state: WholeRunState
    input_set_sha256: str
    receipts: tuple[ChannelReplayReceipt, ...]
    occurrences: tuple[CandidateOccurrence, ...]
    resources: tuple[ObservedResource, ...]
    provenance_claims: tuple[ProvenanceClaim, ...]
    provenance_edges: tuple[tuple[str, str], ...]


class MergeError(EnumeratorError):
    """Rejected merge: duplicate identity, conflicting provenance, or counters."""


def merge_channel_receipts(
    receipts: Sequence[ChannelReplayReceipt],
) -> MergedDiscoveryReceipt:
    """Merge receipts in stable channel and identity order."""

    values = tuple(receipts)
    if not values:
        raise MergeError("merge_empty")
    identities: list[str] = []
    by_channel: dict[str, list[ChannelReplayReceipt]] = {
        channel: [] for channel in CHANNEL_ORDER
    }
    for receipt in values:
        if not isinstance(receipt, ChannelReplayReceipt):
            raise MergeError("merge_receipt_type")
        identity = _receipt_identity(receipt)
        if identity in identities:
            raise MergeError("duplicate_receipt")
        identities.append(identity)
        if receipt.channel not in by_channel:
            raise MergeError("merge_channel")
        if by_channel[receipt.channel]:
            raise MergeError("duplicate_receipt")
        _assert_receipt_counters(receipt)
        by_channel[receipt.channel].append(receipt)
    ordered = tuple(
        receipt for channel in CHANNEL_ORDER for receipt in by_channel[channel]
    )
    resources = _merge_resources(ordered)
    claims = _merge_claims(ordered, resources)
    occurrences = _merge_occurrences(ordered, resources, claims)
    edges = tuple(
        sorted(
            {
                (occurrence.occurrence_id, provenance_id)
                for occurrence in occurrences
                for provenance_id in occurrence.provenance_ids
            }
        )
    )
    states = tuple(receipt.accounting.channel_state for receipt in ordered)
    if all(state == "complete" for state in states):
        whole_run_state: WholeRunState = "complete"
    elif all(state == "failed" for state in states):
        whole_run_state = "failed"
    else:
        whole_run_state = "partial"
    input_set_sha256 = sha256(
        canonical_json_bytes(
            {
                "receiptIdentities": [
                    _receipt_identity(receipt) for receipt in ordered
                ],
                "schemaVersion": 1,
            }
        )
    ).hexdigest()
    return MergedDiscoveryReceipt(
        schema_version=1,
        whole_run_state=whole_run_state,
        input_set_sha256=input_set_sha256,
        receipts=ordered,
        occurrences=occurrences,
        resources=resources,
        provenance_claims=claims,
        provenance_edges=edges,
    )


def encode_merged_discovery_receipt(merged: MergedDiscoveryReceipt) -> bytes:
    """Canonical merge bytes independent of channel completion order."""

    return canonical_json_bytes(
        {
            "inputSetSha256": merged.input_set_sha256,
            "occurrences": [
                occurrence.model_dump(mode="json", by_alias=True, round_trip=True)
                for occurrence in merged.occurrences
            ],
            "provenanceClaims": [
                claim.model_dump(mode="json", by_alias=True, round_trip=True)
                for claim in merged.provenance_claims
            ],
            "provenanceEdges": [list(edge) for edge in merged.provenance_edges],
            "receipts": [
                decode_canonical_json(encode_channel_replay_receipt(receipt))
                for receipt in merged.receipts
            ],
            "resources": [
                resource.model_dump(mode="json", by_alias=True, round_trip=True)
                for resource in merged.resources
            ],
            "schemaVersion": merged.schema_version,
            "wholeRunState": merged.whole_run_state,
        }
    )


def _receipt_identity(receipt: ChannelReplayReceipt) -> str:
    return sha256(encode_channel_replay_receipt(receipt)).hexdigest()


def _assert_receipt_counters(receipt: ChannelReplayReceipt) -> None:
    accounting = receipt.accounting
    if accounting.planned_operations != len(receipt.operation_ids):
        raise MergeError("mismatched_counters")
    if accounting.request_consumed != len(receipt.request_receipts):
        raise MergeError("mismatched_counters")
    if accounting.admitted_bytes != sum(
        item.admitted_bytes for item in receipt.request_receipts
    ):
        raise MergeError("mismatched_counters")


def _merge_resources(
    receipts: Sequence[ChannelReplayReceipt],
) -> tuple[ObservedResource, ...]:
    merged: dict[str, ObservedResource] = {}
    for receipt in receipts:
        for resource in receipt.resources:
            existing = merged.get(resource.resource_id)
            if existing is None:
                merged[resource.resource_id] = resource
                continue
            if existing.content_sha256 != resource.content_sha256:
                raise MergeError("conflicting_provenance")
            if existing.final_locator != resource.final_locator:
                raise MergeError("conflicting_provenance")
    return tuple(merged[item] for item in sorted(merged))


def _merge_claims(
    receipts: Sequence[ChannelReplayReceipt],
    resources: Sequence[ObservedResource],
) -> tuple[ProvenanceClaim, ...]:
    resource_ids = {item.resource_id for item in resources}
    merged: dict[str, ProvenanceClaim] = {}
    for receipt in receipts:
        for claim in receipt.provenance_claims:
            if claim.resource_id not in resource_ids:
                raise MergeError("conflicting_provenance")
            existing = merged.get(claim.claim_id)
            if existing is None:
                merged[claim.claim_id] = claim
                continue
            if existing != claim:
                raise MergeError("conflicting_provenance")
    return tuple(merged[item] for item in sorted(merged))


def _merge_occurrences(
    receipts: Sequence[ChannelReplayReceipt],
    resources: Sequence[ObservedResource],
    claims: Sequence[ProvenanceClaim],
) -> tuple[CandidateOccurrence, ...]:
    admitted = {item.resource_id for item in resources} | {
        item.claim_id for item in claims
    }
    merged: dict[str, CandidateOccurrence] = {}
    for receipt in receipts:
        for occurrence in receipt.occurrences:
            missing = set(occurrence.provenance_ids) - admitted
            if missing:
                raise MergeError("conflicting_provenance")
            existing = merged.get(occurrence.occurrence_id)
            if existing is None:
                merged[occurrence.occurrence_id] = occurrence
                continue
            if existing.identity != occurrence.identity:
                raise MergeError("conflicting_provenance")
            merged[occurrence.occurrence_id] = CandidateOccurrence(
                occurrence_id=existing.occurrence_id,
                channel=existing.channel,
                identity=existing.identity,
                provenance_ids=tuple(
                    sorted(
                        set(existing.provenance_ids) | set(occurrence.provenance_ids)
                    )
                ),
            )
    return tuple(
        merged[item]
        for item in sorted(
            merged,
            key=lambda occurrence_id: (
                merged[occurrence_id].channel,
                merged[occurrence_id].identity.key,
                merged[occurrence_id].identity.canonical_url,
                occurrence_id,
            ),
        )
    )
