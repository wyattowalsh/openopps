"""Strict immutable models for quarantined discovery contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Literal
import unicodedata

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


SHA256_PATTERN = r"^[0-9a-f]{64}$"
GIT_SHA_PATTERN = r"^[0-9a-f]{40}$"
StrictNonNegativeInt = Annotated[int, Field(strict=True, ge=0)]


class DiscoveryChannel(StrEnum):
    OFFICIAL = "official"
    PUBLIC_CODE = "public_code"
    SEARCH = "search"
    TARGETED_ATS = "targeted_ats"


class CandidateKind(StrEnum):
    SOURCE = "source"
    BOARD_ROUTE = "board_route"
    DATASET = "dataset"
    CATALOG = "catalog"


class ProcessingLifecycle(StrEnum):
    DISCOVERED = "discovered"
    EVALUATED = "evaluated"


class EvaluationDisposition(StrEnum):
    ALREADY_APPROVED = "already_approved"
    PROMOTABLE = "promotable"
    BLOCKED = "blocked"
    UNSUPPORTED = "unsupported"
    INCONCLUSIVE = "inconclusive"


class BoundedReason(StrEnum):
    NONE = "none"
    ACCESS_BLOCKED = "access_blocked"
    AUTH_REQUIRED = "auth_required"
    BUDGET_EXHAUSTED = "budget_exhausted"
    CANDIDATE_LIMIT = "candidate_limit"
    COLLISION_UNRESOLVED = "collision_unresolved"
    CONTENT_REJECTED = "content_rejected"
    DNS_REJECTED = "dns_rejected"
    EVIDENCE_INCOMPLETE = "evidence_incomplete"
    EVIDENCE_STALE = "evidence_stale"
    IDENTITY_UNRESOLVED = "identity_unresolved"
    LICENSE_BLOCKED = "license_blocked"
    PARSER_REJECTED = "parser_rejected"
    POLICY_UNRESOLVED = "policy_unresolved"
    PUBLICATION_BLOCKED = "publication_blocked"
    RATE_LIMITED = "rate_limited"
    REDIRECT_REJECTED = "redirect_rejected"
    REDISTRIBUTION_BLOCKED = "redistribution_blocked"
    SECRET_DETECTED = "secret_detected"
    SUPPORT_UNRESOLVED = "support_unresolved"
    SYNC_BLOCKED = "sync_blocked"
    TIMED_OUT = "timed_out"
    TRANSPORT_REJECTED = "transport_rejected"
    UNSUPPORTED_ROUTE = "unsupported_route"


LivenessState = Literal["live", "inconclusive"]
SupportState = Literal["supported", "unsupported", "inconclusive"]
PolicyState = Literal["allowed", "blocked", "unresolved"]
TaxonomyState = Literal["complete", "incomplete"]
SourceDisposition = Literal[
    "succeeded",
    "failed",
    "timed_out",
    "fresh_skipped",
    "policy_blocked",
    "rate_limited",
    "cancelled",
    "unstarted",
]
RouteDisposition = Literal[
    "succeeded",
    "failed",
    "timed_out",
    "fresh_skipped",
    "deferred",
    "duplicate_skipped",
    "missing_metadata",
    "policy_blocked",
    "rate_limited",
    "cancelled",
    "unstarted",
]
ChannelOperationOutcome = Literal[
    "succeeded",
    "blocked",
    "rate_limited",
    "timed_out",
    "failed",
    "cancelled",
    "unstarted",
]
PromotionOperation = Literal[
    "access",
    "license",
    "publication",
    "redistribution",
    "sync",
]


def _validate_required_operations(
    value: tuple[PromotionOperation, ...],
) -> tuple[PromotionOperation, ...]:
    if value != tuple(sorted(set(value))):
        raise ValueError("required operations must be sorted and unique")
    return value


RequiredPromotionOperations = Annotated[
    tuple[PromotionOperation, ...],
    Field(min_length=1),
    AfterValidator(_validate_required_operations),
]


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class StrictDiscoveryModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        extra="forbid",
        frozen=True,
        strict=True,
        populate_by_name=True,
        ser_json_bytes="base64",
        validate_default=True,
        val_json_bytes="base64",
        hide_input_in_errors=True,
    )


class CandidateIdentity(StrictDiscoveryModel):
    key: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=2_000)
    canonical_url: str = Field(min_length=1, max_length=2_000)
    provider_id: str = Field(min_length=1, max_length=200)
    provider_token: str | None = Field(default=None, min_length=1, max_length=500)
    owner: str = Field(min_length=1, max_length=200)
    candidate_kind: Literal["source", "board_route", "dataset", "catalog"] = "source"
    adapter_id: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_normalized_identity(self) -> CandidateIdentity:
        from openopps.discovery.transport import validate_public_locator

        if self.key != self.key.strip().casefold():
            raise ValueError("candidate key must be normalized")
        if self.provider_id != self.provider_id.strip().casefold():
            raise ValueError("candidate provider must be normalized")
        if self.owner != self.owner.strip().casefold():
            raise ValueError("candidate owner must be normalized")
        if (
            self.adapter_id is not None
            and self.adapter_id != self.adapter_id.strip().casefold()
        ):
            raise ValueError("candidate adapter must be normalized")
        if (
            self.provider_token is not None
            and self.provider_token != self.provider_token.strip()
        ):
            raise ValueError("candidate provider token must be trimmed")
        if validate_public_locator(self.url).url != self.canonical_url:
            raise ValueError("candidate locator identity is not canonical")
        return self


class CandidateOccurrence(StrictDiscoveryModel):
    occurrence_id: str = Field(min_length=1, max_length=500)
    channel: Literal["official", "public_code", "search", "targeted_ats"]
    identity: CandidateIdentity
    provenance_ids: tuple[str, ...] = Field(min_length=1)

    @field_validator("provenance_ids")
    @classmethod
    def validate_provenance(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        del cls
        if any(not item for item in value):
            raise ValueError("provenance_ids must be non-empty strings")
        if len(set(value)) != len(value):
            raise ValueError("provenance_ids must be unique")
        return tuple(sorted(value))


class EvaluationAxes(StrictDiscoveryModel):
    liveness: LivenessState
    support: SupportState
    policy: PolicyState
    taxonomy: TaxonomyState
    already_approved: bool = False


class PolicyAxisSet(StrictDiscoveryModel):
    access: PolicyState
    license: PolicyState
    redistribution: PolicyState
    sync: PolicyState
    publication: PolicyState


class LivenessEvidence(StrictDiscoveryModel):
    response_class: str = Field(min_length=1, max_length=100)
    expected_structure: bool
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def normalize_observed_at(cls, value: datetime) -> datetime:
        del cls
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        return value.astimezone(UTC)


class SupportEvidence(StrictDiscoveryModel):
    provider_id: str = Field(min_length=1, max_length=200)
    built_in_route: bool
    route_metadata_complete: bool
    job_fetch_validated: bool
    access_required: bool
    transient_failure: bool


class SourceOutcome(StrictDiscoveryModel):
    source_id: str = Field(min_length=1, max_length=500)
    disposition: SourceDisposition
    started: bool
    authoritative: bool = False
    freshness_context_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_start_state(self) -> SourceOutcome:
        if self.disposition == "unstarted" and self.started:
            raise ValueError("unstarted source must not be started")
        if self.disposition == "cancelled" and not self.started:
            raise ValueError("cancelled source must have started")
        if self.disposition not in {"unstarted"} and not self.started:
            raise ValueError(f"{self.disposition} source must have started")
        if self.disposition == "fresh_skipped":
            if not self.authoritative or self.freshness_context_digest is None:
                raise ValueError(
                    "fresh-skipped source requires authoritative freshness context"
                )
        elif self.freshness_context_digest is not None:
            raise ValueError("only fresh-skipped source may carry freshness context")
        return self


class RouteOutcome(StrictDiscoveryModel):
    route_id: str = Field(min_length=1, max_length=500)
    disposition: RouteDisposition
    representative_id: str | None = Field(default=None, min_length=1, max_length=500)
    started: bool
    authoritative: bool = False
    freshness_context_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_start_and_representative(self) -> RouteOutcome:
        if self.disposition == "unstarted" and self.started:
            raise ValueError("unstarted route must not be started")
        if self.disposition == "cancelled" and not self.started:
            raise ValueError("cancelled route must have started")
        if self.disposition != "unstarted" and not self.started:
            raise ValueError(f"{self.disposition} route must have started")
        if self.disposition == "duplicate_skipped":
            if self.representative_id is None:
                raise ValueError("duplicate route requires a representative")
        elif self.representative_id is not None:
            raise ValueError("only duplicate routes may name a representative")
        if self.disposition == "fresh_skipped":
            if not self.authoritative or self.freshness_context_digest is None:
                raise ValueError(
                    "fresh-skipped route requires authoritative freshness context"
                )
        elif self.freshness_context_digest is not None:
            raise ValueError("only fresh-skipped route may carry freshness context")
        return self


class ChannelBudget(StrictDiscoveryModel):
    """Finite immutable limits for one discovery channel."""

    query_limit: int = Field(strict=True, ge=0, le=1_000)
    request_limit: int = Field(strict=True, ge=0, le=5_000)
    origin_limit: int = Field(strict=True, ge=0, le=500)
    redirect_limit: int = Field(strict=True, ge=0, le=10)
    page_limit: int = Field(strict=True, ge=0, le=1_000)
    response_byte_limit: int = Field(strict=True, ge=0, le=10_485_760)
    aggregate_byte_limit: int = Field(strict=True, ge=0, le=268_435_456)
    candidate_limit: int = Field(strict=True, ge=0, le=10_000)
    concurrency_limit: int = Field(strict=True, ge=0, le=64)
    per_origin_concurrency_limit: int = Field(strict=True, ge=0, le=16)
    retry_limit: int = Field(strict=True, ge=0, le=10)
    parser_depth_limit: int = Field(strict=True, ge=0, le=128)
    wall_clock_limit_ms: int = Field(strict=True, ge=0, le=1_800_000)

    @model_validator(mode="after")
    def validate_budget_relationships(self) -> ChannelBudget:
        if self.concurrency_limit > self.request_limit:
            raise ValueError("channel concurrency cannot exceed request limit")
        if self.per_origin_concurrency_limit > self.concurrency_limit:
            raise ValueError("per-origin concurrency cannot exceed channel concurrency")
        return self


class WholeRunBudget(StrictDiscoveryModel):
    """Finite immutable limits shared by all channels in one invocation."""

    request_limit: int = Field(strict=True, ge=0, le=20_000)
    aggregate_byte_limit: int = Field(strict=True, ge=0, le=1_073_741_824)
    candidate_limit: int = Field(strict=True, ge=0, le=40_000)
    concurrency_limit: int = Field(strict=True, ge=0, le=128)
    wall_clock_limit_ms: int = Field(strict=True, ge=0, le=3_600_000)

    @model_validator(mode="after")
    def validate_budget_relationships(self) -> WholeRunBudget:
        if self.concurrency_limit > self.request_limit:
            raise ValueError("whole-run concurrency cannot exceed request limit")
        return self


class ChannelProfile(StrictDiscoveryModel):
    channel: Literal["official", "public_code", "search", "targeted_ats"]
    budget: ChannelBudget
    seed_ids: tuple[str, ...]
    allowed_origins: tuple[str, ...]
    allowed_query_keys: tuple[str, ...]
    parser_ids: tuple[str, ...]

    @model_validator(mode="after")
    def validate_profile_arrays(self) -> ChannelProfile:
        for label, values in (
            ("seed", self.seed_ids),
            ("origin", self.allowed_origins),
            ("query key", self.allowed_query_keys),
            ("parser", self.parser_ids),
        ):
            if any(not item for item in values) or values != tuple(sorted(set(values))):
                raise ValueError(f"profile {label} values must be sorted and unique")
        return self


class TrustedDiscoveryProfile(StrictDiscoveryModel):
    schema_version: Literal[1] = 1
    profile_id: str = Field(min_length=1, max_length=200)
    profile_version: str = Field(min_length=1, max_length=100)
    whole_run_budget: WholeRunBudget
    channels: tuple[ChannelProfile, ...] = Field(min_length=1)
    profile_digest: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_channels(self) -> TrustedDiscoveryProfile:
        identities = tuple(channel.channel for channel in self.channels)
        if identities != tuple(sorted(set(identities))):
            raise ValueError("profile channels must be sorted and unique")
        if sum(channel.budget.request_limit for channel in self.channels) < (
            self.whole_run_budget.request_limit
        ):
            raise ValueError("whole-run request budget exceeds channel capacity")
        return self


class ObservedResource(StrictDiscoveryModel):
    resource_id: str = Field(min_length=1, max_length=500)
    role: str = Field(min_length=1, max_length=100)
    media_type: str = Field(min_length=1, max_length=200)
    content_sha256: str = Field(pattern=SHA256_PATTERN)
    size_bytes: StrictNonNegativeInt
    observed_at: datetime
    final_locator: str = Field(min_length=1, max_length=2_000)
    validated_address: str = Field(min_length=1, max_length=100)
    etag: str | None = Field(default=None, min_length=1, max_length=500)
    last_modified: str | None = Field(default=None, min_length=1, max_length=500)

    @field_validator("observed_at")
    @classmethod
    def normalize_observed_at(cls, value: datetime) -> datetime:
        del cls
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("resource observation time must be timezone-aware")
        return value.astimezone(UTC)


class RedirectHop(StrictDiscoveryModel):
    ordinal: StrictNonNegativeInt
    source_locator: str = Field(min_length=1, max_length=2_000)
    target_locator: str = Field(min_length=1, max_length=2_000)
    status_code: int = Field(strict=True, ge=300, le=399)
    cross_origin: bool


class RequestReceipt(StrictDiscoveryModel):
    request_id: str = Field(min_length=1, max_length=500)
    attempt_kind: Literal["initial", "pagination", "redirect", "retry"]
    outcome: Literal[
        "succeeded",
        "blocked",
        "rate_limited",
        "timed_out",
        "failed",
        "cancelled",
    ]
    locator_id: str = Field(min_length=1, max_length=500)
    resource_id: str | None = Field(default=None, min_length=1, max_length=500)
    response_status: int | None = Field(default=None, strict=True, ge=100, le=599)
    admitted_bytes: StrictNonNegativeInt
    elapsed_ms: StrictNonNegativeInt
    validated_addresses: tuple[str, ...] = ()
    redirect_hops: tuple[RedirectHop, ...] = ()
    reason_code: BoundedReason = BoundedReason.NONE

    @model_validator(mode="after")
    def validate_receipt_arrays(self) -> RequestReceipt:
        if self.validated_addresses != tuple(sorted(set(self.validated_addresses))):
            raise ValueError("validated addresses must be sorted and unique")
        ordinals = tuple(hop.ordinal for hop in self.redirect_hops)
        if ordinals != tuple(range(len(ordinals))):
            raise ValueError("redirect hop ordinals must be contiguous")
        if self.outcome == "succeeded" and self.reason_code != BoundedReason.NONE:
            raise ValueError("successful request cannot carry a failure reason")
        if self.outcome != "succeeded" and self.reason_code == BoundedReason.NONE:
            raise ValueError("unsuccessful request requires a bounded reason")
        return self


class ProvenanceClaim(StrictDiscoveryModel):
    claim_id: str = Field(min_length=1, max_length=500)
    resource_id: str = Field(min_length=1, max_length=500)
    field_name: str = Field(min_length=1, max_length=200)
    value: str | None = Field(default=None, max_length=4_000)
    source: Literal["local_observation", "remote_assertion"]
    accepted: bool = False

    @model_validator(mode="after")
    def separate_remote_authority(self) -> ProvenanceClaim:
        if self.source == "remote_assertion" and self.accepted:
            raise ValueError("remote assertions cannot become accepted local authority")
        return self


class CandidateTaxonomy(StrictDiscoveryModel):
    provider_type: str | None = Field(default=None, min_length=1, max_length=200)
    coverage_mode: str | None = Field(default=None, min_length=1, max_length=200)
    access_type: str | None = Field(default=None, min_length=1, max_length=200)
    license_status: str | None = Field(default=None, min_length=1, max_length=200)
    refresh_cadence: str | None = Field(default=None, min_length=1, max_length=200)
    source_category: str | None = Field(default=None, min_length=1, max_length=200)
    source_attribution: str | None = Field(default=None, min_length=1, max_length=1_000)
    inclusion_reason: str | None = Field(default=None, min_length=1, max_length=1_000)
    source_year: int | None = Field(default=None, strict=True, ge=1900, le=9999)
    evidence_claim_ids: tuple[str, ...] = ()

    @field_validator("evidence_claim_ids")
    @classmethod
    def canonical_evidence_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        del cls
        if any(not item for item in value) or len(set(value)) != len(value):
            raise ValueError("taxonomy evidence IDs must be non-empty and unique")
        return tuple(sorted(value))

    @property
    def complete(self) -> bool:
        return all(
            value is not None
            for name, value in self.model_dump().items()
            if name not in {"source_year", "evidence_claim_ids"}
        )


class NormalizedCandidate(StrictDiscoveryModel):
    candidate_id: str = Field(min_length=1, max_length=500)
    identity: CandidateIdentity
    occurrence_ids: tuple[str, ...] = Field(min_length=1)
    provenance_ids: tuple[str, ...] = Field(min_length=1)
    collision_ids: tuple[str, ...] = ()
    superseded_by: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_semantic_arrays(self) -> NormalizedCandidate:
        for label, values in (
            ("occurrence", self.occurrence_ids),
            ("provenance", self.provenance_ids),
            ("collision", self.collision_ids),
        ):
            if any(not item for item in values) or len(set(values)) != len(values):
                raise ValueError(f"{label} IDs must be non-empty and unique")
            if values != tuple(sorted(values)):
                raise ValueError(f"{label} IDs must be canonically sorted")
        if self.superseded_by == self.candidate_id:
            raise ValueError("candidate cannot supersede itself")
        return self


class CandidateCollision(StrictDiscoveryModel):
    collision_id: str = Field(min_length=1, max_length=500)
    candidate_ids: tuple[str, ...] = Field(min_length=2)
    reasons: tuple[
        Literal["exact_key", "exact_url", "canonical_url", "domain", "provider_token"],
        ...,
    ] = Field(min_length=1)
    resolved: Literal[False] = False

    @model_validator(mode="after")
    def validate_collision_arrays(self) -> CandidateCollision:
        if self.candidate_ids != tuple(sorted(set(self.candidate_ids))):
            raise ValueError("collision candidate IDs must be sorted and unique")
        if self.reasons != tuple(sorted(set(self.reasons))):
            raise ValueError("collision reasons must be sorted and unique")
        return self


class TerminalEvaluation(StrictDiscoveryModel):
    candidate_id: str = Field(min_length=1, max_length=500)
    lifecycle: Literal["evaluated"] = "evaluated"
    axes: EvaluationAxes
    disposition: Literal[
        "already_approved", "promotable", "blocked", "unsupported", "inconclusive"
    ]
    eligible_for_review: bool
    reason_codes: tuple[BoundedReason, ...]
    superseded_by: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_disposition_derivation(self) -> TerminalEvaluation:
        if self.axes.policy == "blocked":
            expected = "blocked"
        elif (
            self.axes.liveness == "inconclusive"
            or self.axes.support == "inconclusive"
            or self.axes.policy == "unresolved"
            or self.axes.taxonomy == "incomplete"
        ):
            expected = "inconclusive"
        elif self.axes.support == "unsupported":
            expected = "unsupported"
        elif self.axes.already_approved:
            expected = "already_approved"
        else:
            expected = "promotable"
        if self.disposition != expected:
            raise ValueError("evaluation disposition does not match independent axes")
        if self.eligible_for_review != (self.disposition == "promotable"):
            raise ValueError("review eligibility does not match disposition")
        if self.reason_codes != tuple(sorted(set(self.reason_codes))):
            raise ValueError("evaluation reasons must be sorted and unique")
        if self.disposition != "promotable" and not self.reason_codes:
            raise ValueError("non-promotable evaluation requires a bounded reason")
        return self


class ScoutCandidate(StrictDiscoveryModel):
    schema_version: Literal[1] = 1
    enumerator_version: str = Field(min_length=1, max_length=100)
    channel: Literal["official", "public_code", "search", "targeted_ats"]
    candidate: NormalizedCandidate
    taxonomy: CandidateTaxonomy
    resources: tuple[ObservedResource, ...]
    receipts: tuple[RequestReceipt, ...]
    provenance_claims: tuple[ProvenanceClaim, ...]
    evaluation: TerminalEvaluation

    @model_validator(mode="after")
    def validate_candidate_closure(self) -> ScoutCandidate:
        if self.evaluation.candidate_id != self.candidate.candidate_id:
            raise ValueError("candidate evaluation identity does not match")
        for values, attribute, label in (
            (self.resources, "resource_id", "resource"),
            (self.receipts, "request_id", "request"),
            (self.provenance_claims, "claim_id", "provenance claim"),
        ):
            identities = tuple(getattr(item, attribute) for item in values)
            if identities != tuple(sorted(set(identities))):
                raise ValueError(f"{label} identities must be sorted and unique")
        return self


class ChannelOperationAccounting(StrictDiscoveryModel):
    channel: Literal["official", "public_code", "search", "targeted_ats"]
    channel_state: Literal["complete", "partial", "failed", "cancelled", "nonterminal"]
    planned_operations: StrictNonNegativeInt
    succeeded: StrictNonNegativeInt
    blocked: StrictNonNegativeInt
    rate_limited: StrictNonNegativeInt
    timed_out: StrictNonNegativeInt
    failed: StrictNonNegativeInt
    cancelled: StrictNonNegativeInt
    unstarted: StrictNonNegativeInt
    request_limit: StrictNonNegativeInt
    request_consumed: StrictNonNegativeInt
    request_in_flight: StrictNonNegativeInt
    request_remaining: StrictNonNegativeInt
    byte_limit: StrictNonNegativeInt
    admitted_bytes: StrictNonNegativeInt
    remaining_bytes: StrictNonNegativeInt
    unfinished_operation_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_accounting_conservation(self) -> ChannelOperationAccounting:
        terminal_total = sum(
            (
                self.succeeded,
                self.blocked,
                self.rate_limited,
                self.timed_out,
                self.failed,
                self.cancelled,
                self.unstarted,
            )
        )
        if self.planned_operations != terminal_total:
            raise ValueError("planned operation denominator is not conserved")
        if self.request_limit != (
            self.request_consumed + self.request_in_flight + self.request_remaining
        ):
            raise ValueError("request budget is not conserved")
        if self.byte_limit != self.admitted_bytes + self.remaining_bytes:
            raise ValueError("byte budget is not conserved")
        if self.channel_state != "nonterminal" and self.request_in_flight:
            raise ValueError("terminal channel cannot retain in-flight requests")
        if self.unfinished_operation_ids != tuple(
            sorted(set(self.unfinished_operation_ids))
        ):
            raise ValueError("unfinished operation IDs must be sorted and unique")
        if self.channel_state == "complete" and self.unfinished_operation_ids:
            raise ValueError("complete channel cannot retain unfinished work")
        return self


class ChannelReplayReceipt(StrictDiscoveryModel):
    """Closed, replayable output and exact accounting for one channel run."""

    schema_version: Literal[1]
    enumerator_version: str = Field(min_length=1, max_length=100)
    channel: Literal["official", "public_code", "search", "targeted_ats"]
    input_set_sha256: str = Field(pattern=SHA256_PATTERN)
    operation_ids: tuple[str, ...]
    operation_outcomes: tuple[ChannelOperationOutcome, ...]
    operation_request_ids: tuple[tuple[str, ...], ...]
    occurrences: tuple[CandidateOccurrence, ...]
    resources: tuple[ObservedResource, ...]
    request_receipts: tuple[RequestReceipt, ...]
    provenance_claims: tuple[ProvenanceClaim, ...]
    accounting: ChannelOperationAccounting

    @model_validator(mode="after")
    def validate_replay_closure(self) -> ChannelReplayReceipt:
        if self.accounting.channel != self.channel:
            raise ValueError("channel accounting tag does not match receipt")
        if self.accounting.channel_state == "nonterminal":
            raise ValueError("nonterminal channel cannot emit a replay receipt")

        if any(
            not item or len(item) > 500 for item in self.operation_ids
        ) or self.operation_ids != tuple(sorted(set(self.operation_ids))):
            raise ValueError("operation IDs must be sorted, unique, and bounded")
        if len(self.operation_outcomes) != len(self.operation_ids):
            raise ValueError("operation outcomes must align with operation IDs")
        if len(self.operation_request_ids) != len(self.operation_ids):
            raise ValueError("operation request IDs must align with operation IDs")
        if self.accounting.planned_operations != len(self.operation_ids):
            raise ValueError("planned operations do not match operation IDs")

        identity_fields = (
            (self.occurrences, "occurrence_id", "occurrence"),
            (self.resources, "resource_id", "resource"),
            (self.request_receipts, "request_id", "request receipt"),
            (self.provenance_claims, "claim_id", "provenance claim"),
        )
        for values, attribute, label in identity_fields:
            identities = tuple(getattr(item, attribute) for item in values)
            if identities != tuple(sorted(set(identities))):
                raise ValueError(f"{label} identities must be sorted and unique")

        if any(occurrence.channel != self.channel for occurrence in self.occurrences):
            raise ValueError("occurrence channel tag does not match receipt")

        resource_ids = {resource.resource_id for resource in self.resources}
        claim_ids = {claim.claim_id for claim in self.provenance_claims}
        if resource_ids & claim_ids:
            raise ValueError("resource and provenance claim IDs must be unambiguous")
        admitted_provenance_ids = resource_ids | claim_ids
        if any(
            provenance_id not in admitted_provenance_ids
            for occurrence in self.occurrences
            for provenance_id in occurrence.provenance_ids
        ):
            raise ValueError("occurrence provenance does not resolve")
        if any(
            receipt.resource_id is not None and receipt.resource_id not in resource_ids
            for receipt in self.request_receipts
        ):
            raise ValueError("request receipt resource does not resolve")
        if any(
            claim.resource_id not in resource_ids for claim in self.provenance_claims
        ):
            raise ValueError("provenance claim resource does not resolve")

        request_by_id = {
            receipt.request_id: receipt for receipt in self.request_receipts
        }
        assigned_request_ids: list[str] = []
        unstarted_operation_ids: list[str] = []
        for operation_id, outcome, request_ids in zip(
            self.operation_ids,
            self.operation_outcomes,
            self.operation_request_ids,
            strict=True,
        ):
            if any(
                not request_id for request_id in request_ids
            ) or request_ids != tuple(sorted(set(request_ids))):
                raise ValueError(
                    "operation request IDs must be sorted and unique per operation"
                )
            assigned_request_ids.extend(request_ids)
            if outcome == "unstarted":
                unstarted_operation_ids.append(operation_id)
                if request_ids:
                    raise ValueError("unstarted operation cannot have request receipts")
                continue
            if outcome == "succeeded" and not request_ids:
                raise ValueError("successful operation requires a request receipt")
            if request_ids:
                try:
                    assigned_outcomes = {
                        request_by_id[request_id].outcome for request_id in request_ids
                    }
                except KeyError as error:
                    raise ValueError("operation request ID does not resolve") from error
                if outcome not in assigned_outcomes:
                    raise ValueError(
                        "operation outcome is not represented by its request receipts"
                    )

        request_ids = tuple(request_by_id)
        if len(assigned_request_ids) != len(set(assigned_request_ids)):
            raise ValueError("request receipt cannot be assigned more than once")
        if tuple(sorted(assigned_request_ids)) != request_ids:
            raise ValueError("every request receipt must be assigned exactly once")

        outcome_fields: tuple[tuple[ChannelOperationOutcome, str], ...] = (
            ("succeeded", "succeeded"),
            ("blocked", "blocked"),
            ("rate_limited", "rate_limited"),
            ("timed_out", "timed_out"),
            ("failed", "failed"),
            ("cancelled", "cancelled"),
            ("unstarted", "unstarted"),
        )
        if any(
            getattr(self.accounting, field) != self.operation_outcomes.count(outcome)
            for outcome, field in outcome_fields
        ):
            raise ValueError("operation outcomes do not match channel accounting")
        if self.accounting.unfinished_operation_ids != tuple(unstarted_operation_ids):
            raise ValueError("unfinished operation IDs must identify unstarted work")
        if self.accounting.request_consumed != len(self.request_receipts):
            raise ValueError(
                "request receipts do not match consumed request accounting"
            )
        if self.accounting.admitted_bytes != sum(
            receipt.admitted_bytes for receipt in self.request_receipts
        ):
            raise ValueError("request receipt bytes do not match admitted accounting")
        return self


class ScoutCandidateAccounting(StrictDiscoveryModel):
    observed_candidate_occurrences: StrictNonNegativeInt
    invalid_occurrences: StrictNonNegativeInt
    normalized_occurrences: StrictNonNegativeInt
    duplicate_occurrences: StrictNonNegativeInt
    unique_candidates: StrictNonNegativeInt
    already_approved: StrictNonNegativeInt
    quarantined_candidates: StrictNonNegativeInt
    promotable: StrictNonNegativeInt
    blocked: StrictNonNegativeInt
    unsupported: StrictNonNegativeInt
    inconclusive: StrictNonNegativeInt

    @model_validator(mode="after")
    def validate_candidate_conservation(self) -> ScoutCandidateAccounting:
        if self.observed_candidate_occurrences != (
            self.invalid_occurrences + self.normalized_occurrences
        ):
            raise ValueError("observed occurrence denominator is not conserved")
        if self.normalized_occurrences != (
            self.duplicate_occurrences + self.unique_candidates
        ):
            raise ValueError("normalized occurrence denominator is not conserved")
        if self.unique_candidates != (
            self.already_approved + self.quarantined_candidates
        ):
            raise ValueError("unique candidate denominator is not conserved")
        if self.quarantined_candidates != (
            self.promotable + self.blocked + self.unsupported + self.inconclusive
        ):
            raise ValueError("quarantined candidate denominator is not conserved")
        return self


class BundleMemberManifest(StrictDiscoveryModel):
    path: str = Field(min_length=1, max_length=1_000)
    media_type: str = Field(alias="mediaType", min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=100)
    provenance_id: str = Field(alias="provenanceId", min_length=1, max_length=500)
    sha256: str = Field(pattern=SHA256_PATTERN)
    size_bytes: StrictNonNegativeInt = Field(alias="sizeBytes")


class DiscoveryBundleManifest(StrictDiscoveryModel):
    schema_version: Literal["openopps.discovery.bundle.v1"] = Field(
        alias="schemaVersion"
    )
    profile_id: str = Field(alias="profileId", min_length=1, max_length=200)
    profile_version: str = Field(alias="profileVersion", min_length=1, max_length=100)
    tool_version: str = Field(alias="toolVersion", min_length=1, max_length=100)
    execution_id: str = Field(alias="executionId", min_length=1, max_length=500)
    manifest_id: str = Field(alias="manifestId", pattern=SHA256_PATTERN)
    configuration_sha256: str = Field(
        alias="configurationSha256", pattern=SHA256_PATTERN
    )
    observed_at: str = Field(
        alias="observedAt",
        pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{6})?Z$",
    )
    run_state: Literal["complete"] = Field(alias="runState")
    members: tuple[BundleMemberManifest, ...]
    member_count: StrictNonNegativeInt = Field(alias="memberCount")
    member_set_sha256: str = Field(alias="memberSetSha256", pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_manifest_arrays(self) -> DiscoveryBundleManifest:
        paths = tuple(member.path for member in self.members)
        if paths != tuple(sorted(set(paths))):
            raise ValueError("bundle members must be path-sorted and unique")
        if self.member_count != len(self.members):
            raise ValueError("bundle member count does not match members")
        try:
            observed = datetime.fromisoformat(
                self.observed_at.removesuffix("Z") + "+00:00"
            )
        except ValueError as error:
            raise ValueError("bundle observation time is invalid") from error
        if observed.utcoffset() != UTC.utcoffset(observed):
            raise ValueError("bundle observation time must be UTC")
        return self


class PromotionSelection(StrictDiscoveryModel):
    manifest_digest: str = Field(pattern=SHA256_PATTERN)
    candidate_ids: tuple[str, ...] = Field(min_length=0)
    selection_digest: str = Field(pattern=SHA256_PATTERN)

    @field_validator("candidate_ids")
    @classmethod
    def validate_candidate_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        del cls
        if any(not item for item in value) or value != tuple(sorted(set(value))):
            raise ValueError("promotion candidate IDs must be sorted and unique")
        return value


class RepositoryCASState(StrictDiscoveryModel):
    head_sha: str = Field(pattern=GIT_SHA_PATTERN)
    catalog_fingerprint: str = Field(pattern=SHA256_PATTERN)
    ledger_tail_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    recovery_journal_digests: tuple[str, ...] = ()
    owned_paths_clean: bool

    @field_validator("recovery_journal_digests")
    @classmethod
    def validate_recovery_digests(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        del cls
        if value != tuple(sorted(set(value))):
            raise ValueError("recovery journal digests must be sorted and unique")
        return value


class DiscoveryPromotionPolicyDecision(StrictDiscoveryModel):
    schema_version: Literal[1]
    decision_id: str = Field(min_length=1, max_length=200)
    promotion_intent_digest: str = Field(pattern=SHA256_PATTERN)
    head_sha: str = Field(pattern=GIT_SHA_PATTERN)
    manifest_digest: str = Field(pattern=SHA256_PATTERN)
    selection_digest: str = Field(pattern=SHA256_PATTERN)
    resources_digest: str = Field(pattern=SHA256_PATTERN)
    profile_digest: str = Field(pattern=SHA256_PATTERN)
    policy_inputs_digest: str = Field(pattern=SHA256_PATTERN)
    catalog_before_digest: str = Field(pattern=SHA256_PATTERN)
    catalog_after_digest: str = Field(pattern=SHA256_PATTERN)
    promotion_digest: str = Field(pattern=SHA256_PATTERN)
    required_operations: RequiredPromotionOperations


class EvidenceOnlyDecisionReceipt(StrictDiscoveryModel):
    schema_version: Literal[1] = 1
    decision_id: str = Field(min_length=1, max_length=200)
    promotion_intent_digest: str = Field(pattern=SHA256_PATTERN)
    decision_digest: str = Field(pattern=SHA256_PATTERN)
    validator_version: str = Field(min_length=1, max_length=100)
    validated_at: datetime
    grants_authority: Literal[False] = False

    @field_validator("validated_at")
    @classmethod
    def normalize_validated_at(cls, value: datetime) -> datetime:
        del cls
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("decision receipt time must be timezone-aware")
        return value.astimezone(UTC)


class ApprovedIngestionSelectorEnvelope(StrictDiscoveryModel):
    schema_version: Literal[1] = 1
    source_keys: tuple[str, ...] = Field(min_length=1)
    source_count: int = Field(strict=True, ge=1)
    source_key_digest: str = Field(pattern=SHA256_PATTERN)
    packaged_catalog_fingerprint: str = Field(pattern=SHA256_PATTERN)
    catalog_content_digest: str = Field(pattern=SHA256_PATTERN)
    catalog_tree_digest: str = Field(pattern=SHA256_PATTERN)
    v7_policy_code_digest: str = Field(pattern=SHA256_PATTERN)
    v7_policy_schema_digest: str = Field(pattern=SHA256_PATTERN)
    v7_policy_evidence_digest: str = Field(pattern=SHA256_PATTERN)
    v7_policy_corpus_digest: str = Field(pattern=SHA256_PATTERN)
    supplementary_policy_digest: str = Field(pattern=SHA256_PATTERN)
    promotion_digest: str = Field(pattern=SHA256_PATTERN)
    envelope_id: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_source_key_set(self) -> ApprovedIngestionSelectorEnvelope:
        if self.source_keys != tuple(sorted(set(self.source_keys))):
            raise ValueError("approved source keys must be sorted and unique")
        if self.source_count != len(self.source_keys):
            raise ValueError("approved source count does not match source keys")
        return self


class PromotionIntent(StrictDiscoveryModel):
    head_sha: str = Field(pattern=GIT_SHA_PATTERN)
    manifest_digest: str = Field(pattern=SHA256_PATTERN)
    selection_digest: str = Field(pattern=SHA256_PATTERN)
    resources_digest: str = Field(pattern=SHA256_PATTERN)
    profile_digest: str = Field(pattern=SHA256_PATTERN)
    policy_inputs_digest: str = Field(pattern=SHA256_PATTERN)
    catalog_before_digest: str = Field(pattern=SHA256_PATTERN)
    catalog_after_digest: str = Field(pattern=SHA256_PATTERN)
    promotion_digest: str = Field(pattern=SHA256_PATTERN)
    required_operations: RequiredPromotionOperations


class PromotionLedgerEvent(StrictDiscoveryModel):
    schema_version: Literal[1] = 1
    sequence: int = Field(ge=1)
    decision_id: str = Field(min_length=1, max_length=200)
    state: Literal["reserved", "applied", "revoked"]
    promotion_intent_digest: str = Field(pattern=SHA256_PATTERN)
    head_sha: str = Field(pattern=GIT_SHA_PATTERN)
    manifest_digest: str = Field(pattern=SHA256_PATTERN)
    selection_digest: str = Field(pattern=SHA256_PATTERN)
    resources_digest: str = Field(pattern=SHA256_PATTERN)
    profile_digest: str = Field(pattern=SHA256_PATTERN)
    policy_inputs_digest: str = Field(pattern=SHA256_PATTERN)
    catalog_before_digest: str = Field(pattern=SHA256_PATTERN)
    catalog_after_digest: str = Field(pattern=SHA256_PATTERN)
    promotion_digest: str = Field(pattern=SHA256_PATTERN)
    required_operations: RequiredPromotionOperations
    predecessor_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    event_digest: str = Field(pattern=SHA256_PATTERN)


class JournalFileState(StrictDiscoveryModel):
    exists: bool
    mode: int = Field(ge=0, le=0o7777)
    content: bytes
    sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_digest(self) -> JournalFileState:
        import hashlib

        if hashlib.sha256(self.content).hexdigest() != self.sha256:
            raise ValueError("journal file content does not match sha256")
        if not self.exists and (self.mode != 0 or self.content):
            raise ValueError(
                "absent journal file state must have zero mode and no content"
            )
        if self.exists and self.mode == 0:
            raise ValueError("existing journal file state must preserve a mode")
        return self


class ApplyJournalEntry(StrictDiscoveryModel):
    path: str = Field(min_length=1, max_length=1_000)
    before: JournalFileState
    after: JournalFileState


class ApplyJournal(StrictDiscoveryModel):
    schema_version: Literal[1]
    phase: Literal["prepared", "applying", "finalizing"]
    promotion_intent_digest: str = Field(pattern=SHA256_PATTERN)
    lock_nonce: str = Field(min_length=1, max_length=200)
    head_sha: str = Field(pattern=GIT_SHA_PATTERN)
    entries: tuple[ApplyJournalEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_entries(self) -> ApplyJournal:
        paths = tuple(entry.path for entry in self.entries)
        if len(set(paths)) != len(paths):
            raise ValueError("journal entry paths must be unique")
        for path in paths:
            components = path.split("/")
            if (
                path.startswith("/")
                or path.endswith("/")
                or "\\" in path
                or "%" in path
                or any(component in {"", ".", ".."} for component in components)
                or PurePosixPath(path).is_absolute()
            ):
                raise ValueError("journal entry path must be repository-relative")
        portable_paths = tuple(
            unicodedata.normalize("NFC", path).casefold() for path in paths
        )
        if len(set(portable_paths)) != len(portable_paths):
            raise ValueError("journal entry paths must be portable-name unique")
        if paths != tuple(sorted(paths)):
            raise ValueError("journal entry paths must be deterministically sorted")
        return self
