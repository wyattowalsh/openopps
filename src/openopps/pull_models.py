from __future__ import annotations

from enum import IntEnum, StrEnum
from types import MappingProxyType
from typing import Annotated, cast
from urllib.parse import urlsplit, urlunsplit

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveInt,
    StringConstraints,
    ValidationInfo,
    computed_field,
    field_validator,
    model_validator,
)

from openopps.models import JobRecord, JsonDict, validate_public_https_url


class PullOperation(StrEnum):
    """User-requested or resolved URL-pull operation."""

    AUTO = "auto"
    LIST = "list"
    GET = "get"


class PullOutputFormat(StrEnum):
    """Supported URL-pull rendering modes."""

    AUTO = "auto"
    PRETTY = "pretty"
    JSON = "json"
    JSONL = "jsonl"
    TABLE = "table"


class DiscoveryMethod(StrEnum):
    """Bounded evidence path that selected a provider URL target."""

    NATIVE_URL = "native_url"
    REDIRECT = "redirect"
    CANONICAL_LINK = "canonical_link"
    METADATA_LINK = "metadata_link"
    JSON_LD = "json_ld"
    EMBEDDED_URL = "embedded_url"
    PAGE_LINK = "page_link"
    SLUG_PROBE = "slug_probe"


class PullRetrievalMechanism(StrEnum):
    """Provider-neutral mechanism that produced a successful pull result."""

    LIST = "list"
    NATIVE_GET = "native_get"
    BOARD_SCAN_GET = "board_scan_get"


class PullTerminalState(StrEnum):
    """Closed terminal states shared by successful and failed URL pulls."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PullPersistenceHandoffState(StrEnum):
    """Bounded terminal truth about the optional persistence handoff."""

    NOT_REQUESTED = "not_requested"
    NOT_ATTEMPTED = "not_attempted"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PullMembershipScope(StrEnum):
    """Membership visibility proven by a complete provider list traversal."""

    LISTED = "listed"
    ALL_PUBLIC = "all_public"


class PullDetailCoverageStatus(StrEnum):
    """Deterministic summary derived from preserved detail outcome counts."""

    NOT_REQUESTED = "not_requested"
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class PullErrorCode(StrEnum):
    """Closed machine-readable domain failures for URL pulls."""

    UNRECOGNIZED_TARGET = "unrecognized_target"
    UNSUPPORTED_TARGET = "unsupported_target"
    UNSUPPORTED_OPERATION = "unsupported_operation"
    AMBIGUOUS_TARGET = "ambiguous_target"
    POSTING_NOT_FOUND = "posting_not_found"
    INCOMPLETE_RESULT = "incomplete_result"
    NON_AUTHORITATIVE = "non_authoritative"
    REQUIRED_DETAIL_MISSING = "required_detail_missing"
    UNSAFE_URL = "unsafe_url"
    BUDGET_EXCEEDED = "budget_exceeded"
    RESPONSE_TOO_LARGE = "response_too_large"
    TRANSPORT_FAILED = "transport_failed"
    PROVIDER_FAILED = "provider_failed"
    RATE_LIMITED = "rate_limited"
    PERSISTENCE_FAILED = "persistence_failed"


class PullCoverageClass(StrEnum):
    """Offline placement of one URL pull relative to packaged and catalog coverage."""

    CATALOG_ROUTE = "catalog_route"
    OVERLAY_PACKAGED = "overlay_packaged"
    URL_PULL_RESERVED = "url_pull_reserved"
    EPHEMERAL_NEW = "ephemeral_new"
    NOT_APPLICABLE = "not_applicable"


class PullPersistenceFailureReason(StrEnum):
    """Closed reason for a persistence_failed terminal; never exception text."""

    PERSISTENCE_UNAVAILABLE = "persistence_unavailable"
    LEDGER_WRITE_FAILED = "ledger_write_failed"


_SUCCESS_COVERAGE_CLASSES = frozenset(
    {
        PullCoverageClass.CATALOG_ROUTE,
        PullCoverageClass.OVERLAY_PACKAGED,
        PullCoverageClass.URL_PULL_RESERVED,
        PullCoverageClass.EPHEMERAL_NEW,
    }
)


class PullProcessStatus(IntEnum):
    """Stable URL-pull process statuses; status 2 remains a CLI usage error."""

    TARGET_FAILED = 3
    UNSUPPORTED = 4
    EVIDENCE_FAILED = 5
    SAFETY_REJECTED = 6
    BUDGET_EXCEEDED = 7
    UPSTREAM_FAILED = 8
    PERSISTENCE_FAILED = 9


_ERROR_PROCESS_STATUSES = MappingProxyType(
    {
        PullErrorCode.UNRECOGNIZED_TARGET: PullProcessStatus.TARGET_FAILED,
        PullErrorCode.UNSUPPORTED_TARGET: PullProcessStatus.UNSUPPORTED,
        PullErrorCode.UNSUPPORTED_OPERATION: PullProcessStatus.UNSUPPORTED,
        PullErrorCode.AMBIGUOUS_TARGET: PullProcessStatus.TARGET_FAILED,
        PullErrorCode.POSTING_NOT_FOUND: PullProcessStatus.TARGET_FAILED,
        PullErrorCode.INCOMPLETE_RESULT: PullProcessStatus.EVIDENCE_FAILED,
        PullErrorCode.NON_AUTHORITATIVE: PullProcessStatus.EVIDENCE_FAILED,
        PullErrorCode.REQUIRED_DETAIL_MISSING: PullProcessStatus.EVIDENCE_FAILED,
        PullErrorCode.UNSAFE_URL: PullProcessStatus.SAFETY_REJECTED,
        PullErrorCode.BUDGET_EXCEEDED: PullProcessStatus.BUDGET_EXCEEDED,
        PullErrorCode.RESPONSE_TOO_LARGE: PullProcessStatus.BUDGET_EXCEEDED,
        PullErrorCode.TRANSPORT_FAILED: PullProcessStatus.UPSTREAM_FAILED,
        PullErrorCode.PROVIDER_FAILED: PullProcessStatus.UPSTREAM_FAILED,
        PullErrorCode.RATE_LIMITED: PullProcessStatus.UPSTREAM_FAILED,
        PullErrorCode.PERSISTENCE_FAILED: PullProcessStatus.PERSISTENCE_FAILED,
    }
)


def process_status_for_error(code: PullErrorCode) -> PullProcessStatus:
    """Return the exhaustive stable process status for a pull-domain failure."""

    return _ERROR_PROCESS_STATUSES[code]


class PullDomainError(RuntimeError):
    """Bounded user-facing URL-pull failure without raw upstream exception text."""

    def __init__(
        self,
        code: PullErrorCode,
        message: str,
        *,
        hint: str,
        observability: PullTerminalObservability | None = None,
    ) -> None:
        clean_message = message.strip()
        clean_hint = hint.strip()
        if not clean_message:
            raise ValueError("pull error message must not be empty")
        if not clean_hint:
            raise ValueError("pull error hint must not be empty")
        super().__init__(clean_message)
        self.code = code
        self.hint = clean_hint
        self.observability = observability

    def attach_observability(
        self,
        observability: PullTerminalObservability,
    ) -> PullDomainError:
        """Attach service-owned bounded terminal evidence without changing the error."""

        if not isinstance(observability, PullTerminalObservability):
            raise TypeError("observability must be PullTerminalObservability")
        self.observability = observability
        return self

    @property
    def process_status(self) -> PullProcessStatus:
        return process_status_for_error(self.code)

    @property
    def exit_code(self) -> int:
        return int(self.process_status)


class _PullModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        populate_by_name=True,
        revalidate_instances="always",
        str_strip_whitespace=True,
        validate_default=True,
    )


def sanitize_public_pull_url(url: str) -> str:
    """Validate and canonicalize safe pull URL identity without query or fragment."""

    normalized = url.strip()
    validate_public_https_url(normalized)
    parsed = urlsplit(normalized)
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path or "/",
            "",
            "",
        )
    )


SanitizedPublicHttpsUrlStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000),
    AfterValidator(sanitize_public_pull_url),
]
BoundedIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]


class PullProvenance(_PullModel):
    """Sanitized bounded evidence explaining URL target and operation selection."""

    requested_url: SanitizedPublicHttpsUrlStr
    resolved_url: SanitizedPublicHttpsUrlStr
    discovery_method: DiscoveryMethod
    provider_id: BoundedIdentifier
    requested_operation: PullOperation
    resolved_operation: PullOperation
    board_identity: BoundedIdentifier
    posting_identity: BoundedIdentifier | None = None
    visited_urls: tuple[SanitizedPublicHttpsUrlStr, ...] = Field(
        default=(), max_length=64
    )
    probed_slugs: tuple[BoundedIdentifier, ...] = Field(default=(), max_length=64)

    @field_validator("visited_urls", "probed_slugs")
    @classmethod
    def _validate_unique_trace(
        cls, value: tuple[str, ...], info: ValidationInfo
    ) -> tuple[str, ...]:
        del cls
        if len(set(value)) != len(value):
            field_name = info.field_name
            label = "visited URLs" if field_name == "visited_urls" else "probed slugs"
            raise ValueError(f"{label} must be unique")
        return value

    @model_validator(mode="after")
    def _validate_resolved_identity(self) -> PullProvenance:
        if self.resolved_operation == PullOperation.AUTO:
            raise ValueError("resolved operation must be list or get")
        if (
            self.resolved_operation == PullOperation.GET
            and self.posting_identity is None
        ):
            raise ValueError("resolved get requires a posting identity")
        if (
            self.resolved_operation == PullOperation.LIST
            and self.posting_identity is not None
        ):
            raise ValueError("resolved list must not carry a posting identity")
        if (
            self.requested_operation != PullOperation.AUTO
            and self.requested_operation != self.resolved_operation
        ):
            raise ValueError(
                "an explicit requested operation must equal the resolved operation"
            )
        return self


class PullRawPosting(_PullModel):
    """Stable provider-native evidence roles for one normalized job."""

    job_id: BoundedIdentifier
    listing: JsonDict | None
    detail: JsonDict | None


class PullMembershipEvidence(_PullModel):
    """Provider-neutral copy of complete list membership evidence."""

    scope: PullMembershipScope
    authoritative: bool
    complete: bool
    terminal_page_seen: bool
    pages_fetched: PositiveInt
    observed_count: NonNegativeInt
    advertised_count: NonNegativeInt | None = None

    @model_validator(mode="after")
    def _validate_authority(self) -> PullMembershipEvidence:
        if self.authoritative and not (self.complete and self.terminal_page_seen):
            raise ValueError(
                "authoritative membership requires complete terminal-page evidence"
            )
        if (
            self.authoritative
            and self.advertised_count is not None
            and self.advertised_count != self.observed_count
        ):
            raise ValueError(
                "authoritative membership must reconcile advertised and observed counts"
            )
        return self


class PullDetailCoverageEvidence(_PullModel):
    """Provider-neutral detail fan-out outcomes for a list-backed mechanism."""

    required: bool = False
    requested_count: NonNegativeInt = 0
    completed_count: NonNegativeInt = 0
    failed_count: NonNegativeInt = 0

    @model_validator(mode="after")
    def _validate_counts(self) -> PullDetailCoverageEvidence:
        if self.completed_count + self.failed_count > self.requested_count:
            raise ValueError("detail outcomes cannot exceed requested details")
        return self

    @computed_field(
        description="Deterministic status derived from the preserved detail counts.",
        return_type=PullDetailCoverageStatus,
    )
    @property
    def status(self) -> PullDetailCoverageStatus:
        if self.requested_count == 0:
            return (
                PullDetailCoverageStatus.COMPLETE
                if self.required
                else PullDetailCoverageStatus.NOT_REQUESTED
            )
        if self.completed_count == self.requested_count and self.failed_count == 0:
            return PullDetailCoverageStatus.COMPLETE
        if self.completed_count == 0:
            return PullDetailCoverageStatus.UNAVAILABLE
        return PullDetailCoverageStatus.PARTIAL


class PullHttpObservability(_PullModel):
    """Payload-free counters emitted by the shared bounded HTTP operation."""

    logical_read_count: NonNegativeInt = 0
    request_count: NonNegativeInt = 0
    redirect_count: NonNegativeInt = 0
    retry_count: NonNegativeInt = 0
    cache_hit_count: NonNegativeInt = 0
    cache_miss_count: NonNegativeInt = 0
    cache_revalidation_count: NonNegativeInt = 0
    cache_stale_fallback_count: NonNegativeInt = 0
    cache_write_count: NonNegativeInt = 0
    cache_bypass_count: NonNegativeInt = 0
    encoded_bytes: NonNegativeInt = 0
    decoded_bytes: NonNegativeInt = 0


class PullTerminalObservability(_PullModel):
    """Bounded terminal evidence shared by pull results and domain failures."""

    terminal_state: PullTerminalState
    error_code: PullErrorCode | None = None
    requested_operation: PullOperation
    resolved_operation: PullOperation | None = None
    retrieval_mechanism: PullRetrievalMechanism | None = None
    provider_id: BoundedIdentifier | None = None
    discovery_method: DiscoveryMethod | None = None
    resolver_visited_url_count: NonNegativeInt | None = None
    resolver_probe_count: NonNegativeInt | None = None
    http: PullHttpObservability = Field(default_factory=PullHttpObservability)
    membership: PullMembershipEvidence | None = None
    detail_coverage: PullDetailCoverageEvidence | None = None
    duplicate_identity_count: NonNegativeInt | None = None
    provider_error_count: int | None = Field(
        default=None,
        ge=0,
        le=1,
        description=(
            "0/1 latch for whether the provider attempt failed; not an unbounded count."
        ),
    )
    persistence_handoff: PullPersistenceHandoffState
    coverage_class: PullCoverageClass | None = None
    persistence_reason: PullPersistenceFailureReason | None = None
    elapsed_milliseconds: NonNegativeInt

    @model_validator(mode="after")
    def _validate_terminal_evidence(self) -> PullTerminalObservability:
        if self.terminal_state == PullTerminalState.SUCCEEDED:
            if self.error_code is not None:
                raise ValueError("successful pull observability cannot carry an error")
            if (
                self.resolved_operation is None
                or self.retrieval_mechanism is None
                or self.provider_id is None
                or self.discovery_method is None
                or self.resolver_visited_url_count is None
                or self.resolver_probe_count is None
            ):
                raise ValueError(
                    "successful pull observability requires resolved provider evidence"
                )
            if self.provider_error_count != 0:
                raise ValueError(
                    "successful pull observability cannot report provider errors"
                )
            if self.coverage_class not in _SUCCESS_COVERAGE_CLASSES:
                raise ValueError(
                    "successful pull observability requires a catalog, overlay, "
                    "reserved, or ephemeral coverage class"
                )
            if self.persistence_reason is not None:
                raise ValueError(
                    "successful pull observability cannot carry a persistence reason"
                )
        elif self.error_code is None:
            raise ValueError("failed pull observability requires an error code")
        else:
            if self.coverage_class not in {
                None,
                PullCoverageClass.NOT_APPLICABLE,
            }:
                raise ValueError(
                    "failed pull observability cannot claim a packaged coverage class"
                )
            if self.error_code == PullErrorCode.PERSISTENCE_FAILED:
                if self.persistence_reason is None:
                    raise ValueError(
                        "persistence failures require a closed persistence reason"
                    )
            elif self.persistence_reason is not None:
                raise ValueError(
                    "persistence reason is only valid for persistence failures"
                )
        if (self.membership is None) != (self.detail_coverage is None):
            raise ValueError(
                "membership and detail coverage terminal evidence must travel together"
            )
        if self.duplicate_identity_count is not None and self.membership is None:
            raise ValueError("duplicate identity counts require membership evidence")
        if (
            self.retrieval_mechanism == PullRetrievalMechanism.NATIVE_GET
            and self.membership is not None
        ):
            raise ValueError(
                "native get observability cannot carry membership evidence"
            )
        if (
            self.terminal_state == PullTerminalState.SUCCEEDED
            and self.retrieval_mechanism != PullRetrievalMechanism.NATIVE_GET
            and self.membership is None
        ):
            raise ValueError(
                "successful list-backed observability requires membership evidence"
            )
        return self


class PullExecutionEvidence(_PullModel):
    """Storage-ready provider-neutral evidence for one retrieval mechanism."""

    mechanism: PullRetrievalMechanism
    membership: PullMembershipEvidence | None = None
    detail_coverage: PullDetailCoverageEvidence | None = None

    @model_validator(mode="after")
    def _validate_mechanism_evidence(self) -> PullExecutionEvidence:
        if self.mechanism == PullRetrievalMechanism.NATIVE_GET:
            if self.membership is not None or self.detail_coverage is not None:
                raise ValueError(
                    "native get cannot carry board membership or list detail evidence"
                )
            return self
        if self.membership is None or self.detail_coverage is None:
            raise ValueError(
                "list-backed retrieval requires membership and detail evidence"
            )
        return self


class PullResult(_PullModel):
    """Provider-neutral URL-pull result consumed by output and persistence ports."""

    provenance: PullProvenance
    execution: PullExecutionEvidence
    jobs: tuple[JobRecord, ...] = ()
    raw_postings: tuple[PullRawPosting, ...] = ()
    persisted: bool = False
    observability: PullTerminalObservability | None = None

    @model_validator(mode="after")
    def _validate_result_shape(self) -> PullResult:
        self.assert_valid()
        return self

    def assert_valid(self) -> None:
        """Recheck mutable nested job/evidence state at output and apply boundaries."""

        operation = self.provenance.resolved_operation
        mechanism = self.execution.mechanism
        membership = self.execution.membership
        detail_coverage = self.execution.detail_coverage
        if operation == PullOperation.LIST:
            if mechanism != PullRetrievalMechanism.LIST:
                raise ValueError("resolved list requires list execution evidence")
        else:
            if len(self.jobs) != 1:
                raise ValueError("resolved get must return exactly one job")
            if mechanism == PullRetrievalMechanism.LIST:
                raise ValueError("resolved get requires an exact-get mechanism")

        if mechanism != PullRetrievalMechanism.NATIVE_GET:
            if membership is None or detail_coverage is None:
                raise ValueError("list-backed result is missing execution evidence")
            if not (
                membership.authoritative
                and membership.complete
                and membership.terminal_page_seen
            ):
                raise ValueError(
                    "successful list-backed result requires authoritative membership"
                )
            if detail_coverage.required and (
                detail_coverage.status != PullDetailCoverageStatus.COMPLETE
                or detail_coverage.requested_count != membership.observed_count
                or detail_coverage.completed_count != membership.observed_count
                or detail_coverage.failed_count != 0
            ):
                raise ValueError(
                    "complete required detail coverage must span full membership"
                )
            if mechanism == PullRetrievalMechanism.LIST:
                if membership.observed_count != len(self.jobs):
                    raise ValueError(
                        "list membership count must match returned normalized jobs"
                    )
            elif membership.observed_count < len(self.jobs):
                raise ValueError(
                    "board-scan membership cannot contain fewer jobs than its result"
                )
            if membership.scope == PullMembershipScope.LISTED and any(
                job.posting_kind == "unlisted" for job in self.jobs
            ):
                raise ValueError("listed membership cannot include unlisted postings")

        job_ids = [job.id for job in self.jobs]
        if len(set(job_ids)) != len(job_ids):
            raise ValueError("pull result job identities must be unique")
        raw_ids = [posting.job_id for posting in self.raw_postings]
        if len(set(raw_ids)) != len(raw_ids):
            raise ValueError("raw evidence job identities must be unique")
        if raw_ids != job_ids:
            raise ValueError("raw evidence must match returned jobs in order")
        for job, raw in zip(self.jobs, self.raw_postings, strict=True):
            if job.provider_id != self.provenance.provider_id:
                raise ValueError("returned jobs must match the provenance provider")
            if job.board_key != self.provenance.board_identity:
                raise ValueError(
                    "returned jobs must match the provenance board identity"
                )
            if raw.listing is None:
                if job.raw_listing:
                    raise ValueError(
                        "raw listing evidence is missing for a populated job"
                    )
            elif raw.listing != job.raw_listing:
                raise ValueError("raw listing evidence must match the normalized job")
            if raw.detail is None:
                if job.raw_detail:
                    raise ValueError(
                        "raw detail evidence is missing for a populated job"
                    )
            elif raw.detail != job.raw_detail:
                raise ValueError("raw detail evidence must match the normalized job")
        if operation == PullOperation.GET:
            posting_identity = self.provenance.posting_identity
            if posting_identity is None or self.jobs[0].remote_id != posting_identity:
                raise ValueError(
                    "get result must match the provenance posting identity"
                )

        observability = self.observability
        if observability is None:
            return
        if observability.terminal_state != PullTerminalState.SUCCEEDED:
            raise ValueError("pull results require successful terminal observability")
        if observability.requested_operation != self.provenance.requested_operation:
            raise ValueError("observability requested operation must match provenance")
        if observability.resolved_operation != operation:
            raise ValueError("observability resolved operation must match provenance")
        if observability.retrieval_mechanism != mechanism:
            raise ValueError("observability retrieval mechanism must match execution")
        if observability.provider_id != self.provenance.provider_id:
            raise ValueError("observability provider must match provenance")
        if observability.discovery_method != self.provenance.discovery_method:
            raise ValueError("observability discovery method must match provenance")
        if observability.resolver_visited_url_count != len(
            self.provenance.visited_urls
        ):
            raise ValueError("observability visited URL count must match provenance")
        if observability.resolver_probe_count != len(self.provenance.probed_slugs):
            raise ValueError("observability probe count must match provenance")
        if observability.membership != membership:
            raise ValueError("observability membership must match execution")
        if observability.detail_coverage != detail_coverage:
            raise ValueError("observability detail coverage must match execution")
        expected_duplicates = 0 if membership is not None else None
        if observability.duplicate_identity_count != expected_duplicates:
            raise ValueError("successful observability must report exact duplicates")
        if observability.provider_error_count != 0:
            raise ValueError("successful observability cannot report provider errors")
        if observability.coverage_class not in _SUCCESS_COVERAGE_CLASSES:
            raise ValueError(
                "successful observability requires a catalog, overlay, reserved, "
                "or ephemeral coverage class"
            )
        expected_handoff = (
            PullPersistenceHandoffState.SUCCEEDED
            if self.persisted
            else PullPersistenceHandoffState.NOT_REQUESTED
        )
        if observability.persistence_handoff != expected_handoff:
            raise ValueError("observability persistence handoff must match the result")

    def normalized_jobs(self) -> list[dict[str, object]]:
        """Return the normalized job payload used by non-raw renderers."""

        self.assert_valid()
        return [
            cast(
                dict[str, object],
                job.model_dump(mode="json", exclude_none=True),
            )
            for job in self.jobs
        ]

    def raw_envelope(self) -> dict[str, object]:
        """Return the stable raw CLI envelope without duplicating normalized fields."""

        self.assert_valid()
        envelope: dict[str, object] = {
            "provenance": self.provenance.model_dump(mode="json"),
            "execution": self.execution.model_dump(mode="json"),
            "postings": [
                {"listing": posting.listing, "detail": posting.detail}
                for posting in self.raw_postings
            ],
        }
        if self.observability is not None:
            envelope["observability"] = self.observability.model_dump(mode="json")
        return envelope


if set(_ERROR_PROCESS_STATUSES) != set(PullErrorCode):
    raise RuntimeError("pull error status mapping must cover every PullErrorCode")
