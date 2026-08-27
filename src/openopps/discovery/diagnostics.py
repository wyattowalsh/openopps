"""Bounded, fully redacted discovery diagnostics and metric attributes.

Arbitrary upstream text is never rendered.  Callers receive a fixed summary for
one repository-owned reason code plus, when supplied, a digest of only the
bounded admitted prefix.  Metric attributes accept only finite enums, booleans,
and an optional canonical digest identity.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Final, Literal

from openopps.discovery.accounting import (
    OPERATION_TERMINALS,
    TYPED_DEGRADED_CLASSES,
    RouteAccounting,
    ScoutRunEvidence,
    SourceAccounting,
    build_route_accounting,
    build_uniform_source_accounting,
    classify_typed_degraded,
    validate_operation_conservation,
)
from openopps.discovery.canonical import canonical_json_bytes
from openopps.discovery.inventory import (
    DEFAULT_DISCOVERY_OWNED_PATHS,
    DEFAULT_PACKAGED_CATALOG_PATH,
    DEFAULT_V7_POLICY_PATHS,
    read_repository_resources,
)
from openopps.discovery.models import (
    ApprovedIngestionSelectorEnvelope,
    BoundedReason,
    DiscoveryChannel,
    RouteOutcome,
)
from openopps.discovery.policy import bind_v7_policy_digests
from openopps.discovery.promotion import (
    EnvelopeValidationError,
    bind_catalog_fingerprints,
    compute_envelope_id,
    validate_envelope_keys,
)
from openopps.discovery.transport import OperationLedger, OperationLedgerSnapshot


MAX_DIAGNOSTIC_INPUT_BYTES: Final = 4_096
MAX_DIAGNOSTIC_SUMMARY_CHARS: Final = 96
MAX_METRIC_ATTRIBUTES: Final = 6

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TERMINAL_STATES = frozenset(
    {"complete", "partial", "failed", "cancelled", "aborted", "nonterminal"}
)


class DiagnosticRenderingError(ValueError):
    """Raised when a diagnostic would escape the bounded rendering contract."""


@dataclass(frozen=True, slots=True)
class BoundedDiagnostic:
    """One redacted diagnostic containing no caller-controlled text."""

    reason_code: BoundedReason
    summary: str
    detail_prefix_sha256: str | None
    admitted_detail_bytes: int
    detail_truncated: bool

    def as_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-compatible diagnostic mapping."""

        return {
            "admittedDetailBytes": self.admitted_detail_bytes,
            "detailPrefixSha256": self.detail_prefix_sha256,
            "detailTruncated": self.detail_truncated,
            "reasonCode": self.reason_code.value,
            "summary": self.summary,
        }


def _bounded_utf8_prefix(detail: str | bytes) -> tuple[bytes, bool]:
    if isinstance(detail, bytes):
        admitted = detail[:MAX_DIAGNOSTIC_INPUT_BYTES]
        return admitted, len(detail) > len(admitted)
    if not isinstance(detail, str):
        raise DiagnosticRenderingError("diagnostic detail must be text or bytes")

    admitted = bytearray()
    truncated = False
    for character in detail:
        encoded = character.encode("utf-8", errors="replace")
        if len(admitted) + len(encoded) > MAX_DIAGNOSTIC_INPUT_BYTES:
            truncated = True
            break
        admitted.extend(encoded)
    return bytes(admitted), truncated


def _fixed_summary(reason_code: BoundedReason) -> str:
    if reason_code is BoundedReason.NONE:
        return "No discovery failure was recorded."
    label = reason_code.value.replace("_", " ")
    summary = f"Discovery stopped with bounded reason: {label}."
    if len(summary) > MAX_DIAGNOSTIC_SUMMARY_CHARS:  # Defensive enum evolution.
        raise DiagnosticRenderingError("bounded reason summary exceeds its limit")
    return summary


def render_bounded_diagnostic(
    reason_code: BoundedReason,
    *,
    detail: str | bytes | None = None,
) -> BoundedDiagnostic:
    """Render a fixed diagnostic without exposing raw URLs, queries, or secrets."""

    if not isinstance(reason_code, BoundedReason):
        raise DiagnosticRenderingError("reason code must use the bounded enum")
    if detail is None:
        admitted = b""
        truncated = False
        digest = None
    else:
        admitted, truncated = _bounded_utf8_prefix(detail)
        digest = sha256(admitted).hexdigest()
    return BoundedDiagnostic(
        reason_code=reason_code,
        summary=_fixed_summary(reason_code),
        detail_prefix_sha256=digest,
        admitted_detail_bytes=len(admitted),
        detail_truncated=truncated,
    )


def render_metric_attributes(
    *,
    channel: DiscoveryChannel | None,
    terminal_state: Literal[
        "complete", "partial", "failed", "cancelled", "aborted", "nonterminal"
    ],
    reason_code: BoundedReason,
    complete: bool,
    identity_digest: str | None = None,
) -> Mapping[str, bool | str]:
    """Return a small immutable OpenTelemetry-style discovery attribute set."""

    if channel is not None and not isinstance(channel, DiscoveryChannel):
        raise DiagnosticRenderingError("metric channel must use the bounded enum")
    if terminal_state not in _TERMINAL_STATES:
        raise DiagnosticRenderingError("metric terminal state is unsupported")
    if not isinstance(reason_code, BoundedReason):
        raise DiagnosticRenderingError("metric reason must use the bounded enum")
    if not isinstance(complete, bool):
        raise DiagnosticRenderingError("metric completeness must be boolean")
    if identity_digest is not None and _SHA256_RE.fullmatch(identity_digest) is None:
        raise DiagnosticRenderingError("metric identity must be canonical SHA-256")

    if channel is not None and terminal_state == "aborted":
        raise DiagnosticRenderingError("aborted is a whole-run state only")
    if complete != (terminal_state == "complete"):
        raise DiagnosticRenderingError("metric completeness conflicts with state")
    if terminal_state == "complete" and reason_code is not BoundedReason.NONE:
        raise DiagnosticRenderingError("complete metric cannot carry a failure reason")
    if terminal_state in {"partial", "failed", "cancelled", "aborted"} and (
        reason_code is BoundedReason.NONE
    ):
        raise DiagnosticRenderingError("terminal failure metric needs a bounded reason")

    attributes: dict[str, bool | str] = {
        "openopps.discovery.complete": complete,
        "openopps.discovery.reason": reason_code.value,
        "openopps.discovery.scope": "channel" if channel is not None else "run",
        "openopps.discovery.state": terminal_state,
    }
    if channel is not None:
        attributes["openopps.discovery.channel"] = channel.value
    if identity_digest is not None:
        attributes["openopps.discovery.identity.sha256"] = identity_digest
    if len(attributes) > MAX_METRIC_ATTRIBUTES:  # Defensive contract assertion.
        raise DiagnosticRenderingError("metric attribute set exceeds its limit")
    return MappingProxyType(attributes)



_DEGRADED_REASONS = {
    "cancelled": BoundedReason.EVIDENCE_INCOMPLETE,
    "deferred": BoundedReason.EVIDENCE_STALE,
    "failed": BoundedReason.TRANSPORT_REJECTED,
    "missing_metadata": BoundedReason.EVIDENCE_INCOMPLETE,
    "nonterminal": BoundedReason.NONE,
    "partial": BoundedReason.EVIDENCE_INCOMPLETE,
    "policy_blocked": BoundedReason.POLICY_UNRESOLVED,
    "rate_limited": BoundedReason.RATE_LIMITED,
    "timed_out": BoundedReason.TIMED_OUT,
    "unstarted": BoundedReason.EVIDENCE_INCOMPLETE,
}


def _source_counts(source: SourceAccounting) -> dict[str, bool | int]:
    return {
        "cancelled": source.cancelled,
        "complete": source.complete,
        "failed": source.failed,
        "freshSkipped": source.fresh_skipped,
        "planned": source.planned,
        "policyBlocked": source.policy_blocked,
        "rateLimited": source.rate_limited,
        "succeeded": source.succeeded,
        "terminal": source.terminal,
        "timedOut": source.timed_out,
        "unstarted": source.unstarted,
    }


def _route_counts(route: RouteAccounting) -> dict[str, bool | int]:
    return {
        "authoritativeSucceeded": route.authoritative_succeeded,
        "cancelled": route.cancelled,
        "complete": route.complete,
        "deferred": route.deferred,
        "duplicateSkipped": route.duplicate_skipped,
        "failed": route.failed,
        "freshSkipped": route.fresh_skipped,
        "missingMetadata": route.missing_metadata,
        "planned": route.planned,
        "policyBlocked": route.policy_blocked,
        "rateLimited": route.rate_limited,
        "succeeded": route.succeeded,
        "terminal": route.terminal,
        "timedOut": route.timed_out,
        "unstarted": route.unstarted,
    }


def _operation_counts(operations: OperationLedgerSnapshot) -> dict[str, object]:
    return {
        "channelState": operations.channel_state,
        "planned": operations.planned,
        "terminals": {name: operations.terminals[name] for name in OPERATION_TERMINALS},
    }


def _require_unique_nonempty(pinned: tuple[str, ...], label: str) -> None:
    if (
        not pinned
        or any(not item for item in pinned)
        or len(set(pinned)) != len(pinned)
    ):
        raise ValueError(f"planned {label} IDs must be non-empty and unique")


def _metric_terminal_state(
    *,
    attestation: str,
    run_state: str,
    degraded_class: str | None,
) -> Literal[
    "complete", "partial", "failed", "cancelled", "aborted", "nonterminal"
]:
    if attestation == "complete":
        return "complete"
    if run_state == "aborted":
        return "aborted"
    if degraded_class == "cancelled":
        return "cancelled"
    if degraded_class == "nonterminal":
        return "nonterminal"
    if degraded_class in {"failed", "timed_out"}:
        return "failed"
    return "partial"


@dataclass(frozen=True, slots=True)
class ScoutObservabilityJoin:
    attestation: str
    degraded_class: str | None
    source: SourceAccounting
    route: RouteAccounting
    operations: OperationLedgerSnapshot
    diagnostic: BoundedDiagnostic
    metric_attributes: Mapping[str, bool | str]
    evidence: ScoutRunEvidence
    source_plan_digest: str
    route_plan_digest: str
    operation_plan_digest: str

    def as_dict(self) -> dict[str, object]:
        return {
            "attestation": self.attestation,
            "degradedClass": self.degraded_class,
            "diagnostic": self.diagnostic.as_dict(),
            "evidence": self.evidence.as_dict(),
            "metrics": dict(self.metric_attributes),
            "operationPlanDigest": self.operation_plan_digest,
            "operations": _operation_counts(self.operations),
            "route": _route_counts(self.route),
            "routePlanDigest": self.route_plan_digest,
            "source": _source_counts(self.source),
            "sourcePlanDigest": self.source_plan_digest,
        }


def join_scout_observability(
    *,
    source: SourceAccounting,
    route: RouteAccounting,
    operations: OperationLedgerSnapshot,
    planned_source_ids: Sequence[str],
    planned_route_ids: Sequence[str],
    planned_operation_ids: Sequence[str],
    run_state: str,
    evidence: ScoutRunEvidence,
) -> ScoutObservabilityJoin:
    if isinstance(planned_source_ids, (str, bytes)) or isinstance(
        planned_route_ids, (str, bytes)
    ) or isinstance(planned_operation_ids, (str, bytes)):
        raise ValueError("planned IDs must be non-empty and unique")
    pinned_source_ids = tuple(planned_source_ids)
    pinned_route_ids = tuple(planned_route_ids)
    pinned_operation_ids = tuple(planned_operation_ids)
    source_plan_digest = sha256(
        canonical_json_bytes(list(pinned_source_ids))
    ).hexdigest()
    route_plan_digest = sha256(
        canonical_json_bytes(list(pinned_route_ids))
    ).hexdigest()
    operation_plan_digest = sha256(
        canonical_json_bytes(list(pinned_operation_ids))
    ).hexdigest()
    _require_unique_nonempty(pinned_source_ids, "source")
    _require_unique_nonempty(pinned_route_ids, "route")
    _require_unique_nonempty(pinned_operation_ids, "operation")
    if len(pinned_source_ids) != source.planned:
        raise ValueError("planned source denominator is not conserved")
    if len(pinned_route_ids) != route.planned:
        raise ValueError("planned route denominator is not conserved")
    if len(pinned_operation_ids) != operations.planned:
        raise ValueError("planned operation denominator is not conserved")
    validate_operation_conservation(operations.planned, operations.terminals)
    attestation, degraded_class = classify_typed_degraded(
        source=source,
        route=route,
        operation_terminals=operations.terminals,
        operation_channel_state=operations.channel_state,
        run_state=run_state,
    )
    if attestation == "complete":
        if degraded_class is not None:
            raise ValueError("complete attestation cannot carry a degraded class")
        reason_code = BoundedReason.NONE
        diagnostic = render_bounded_diagnostic(reason_code)
    else:
        if degraded_class not in TYPED_DEGRADED_CLASSES:
            raise ValueError("degraded attestation requires a typed class")
        reason_code = _DEGRADED_REASONS[degraded_class]
        diagnostic = render_bounded_diagnostic(
            reason_code,
            detail=canonical_json_bytes(
                {
                    "degradedClass": degraded_class,
                    "operations": _operation_counts(operations),
                    "route": _route_counts(route),
                    "runState": run_state,
                    "source": _source_counts(source),
                }
            ),
        )
    terminal_state = _metric_terminal_state(
        attestation=attestation,
        run_state=run_state,
        degraded_class=degraded_class,
    )
    return ScoutObservabilityJoin(
        attestation=attestation,
        degraded_class=degraded_class,
        source=source,
        route=route,
        operations=operations,
        diagnostic=diagnostic,
        metric_attributes=render_metric_attributes(
            channel=None,
            terminal_state=terminal_state,
            reason_code=reason_code,
            complete=attestation == "complete",
            identity_digest=evidence.invocation_digest,
        ),
        evidence=evidence,
        source_plan_digest=source_plan_digest,
        route_plan_digest=route_plan_digest,
        operation_plan_digest=operation_plan_digest,
    )


_DECISION_SCHEMA_RELATIVE: Final = (
    "src/openopps/discovery/data/discovery-promotion-policy-decision.schema.json"
)
_SCOUT_EVALUATION_ROUTE_ID: Final = "scout-evaluation"
_SCOUT_EVALUATION_OPERATION_ID: Final = "scout-evaluate"
_GIT_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")


class SelectorBoundError(ValueError):
    """Raised when selector-bound scout cannot pin the private envelope."""


@dataclass(frozen=True, slots=True)
class SelectorBoundScoutPin:
    envelope: ApprovedIngestionSelectorEnvelope
    frozen_source_ids: tuple[str, ...]
    checkout_sha: str


def read_checkout_sha(repository_root: Path) -> str:
    """Record the checkout SHA separately from tracked envelope bytes."""

    git_dir = Path(repository_root) / ".git"
    try:
        if git_dir.is_file():
            git_dir = _gitdir_from_pointer(git_dir, Path(repository_root))
        if not git_dir.is_dir():
            raise SelectorBoundError("checkout SHA is unavailable")
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
        sha = _resolve_git_head(git_dir, head)
    except OSError as error:
        raise SelectorBoundError("checkout SHA is unavailable") from error
    if _GIT_SHA1_RE.fullmatch(sha) is None:
        raise SelectorBoundError("checkout SHA is unavailable")
    return sha


def _gitdir_from_pointer(pointer: Path, repository_root: Path) -> Path:
    for line in pointer.read_text(encoding="utf-8").splitlines():
        if line.startswith("gitdir:"):
            git_dir = Path(line.split(":", 1)[1].strip())
            if not git_dir.is_absolute():
                git_dir = (repository_root / git_dir).resolve()
            return git_dir
    raise SelectorBoundError("checkout SHA is unavailable")


def _resolve_git_head(git_dir: Path, head: str) -> str:
    if not head.startswith("ref:"):
        return head
    ref = head.split(":", 1)[1].strip()
    ref_path = git_dir / ref
    if ref_path.is_file():
        return ref_path.read_text(encoding="utf-8").strip()
    packed = git_dir / "packed-refs"
    if packed.is_file():
        for line in packed.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#") or line.startswith("^"):
                continue
            parts = line.split()
            if len(parts) == 2 and parts[1] == ref:
                return parts[0]
    raise SelectorBoundError("checkout SHA is unavailable")


def prepare_selector_bound_scout(
    repository_root: Path,
    *,
    envelope_bytes: bytes | None = None,
    key_classes: Mapping[str, str] | None = None,
) -> SelectorBoundScoutPin:
    """Validate and freeze the private approved-ingestion envelope in memory."""

    root = Path(repository_root)
    checkout_sha = read_checkout_sha(root)
    raw = envelope_bytes
    if raw is None:
        raw = (root / DEFAULT_DISCOVERY_OWNED_PATHS["envelope"]).read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SelectorBoundError("approved-ingestion envelope is invalid") from error
    if not isinstance(payload, dict):
        raise SelectorBoundError("approved-ingestion envelope is invalid")
    if "corpusId" in payload or "sourceKeysSha256" in payload:
        raise SelectorBoundError("v7 public SourceSelector is not accepted")
    try:
        envelope = ApprovedIngestionSelectorEnvelope.model_validate_json(
            raw,
            strict=True,
            by_alias=True,
            by_name=False,
        )
    except (TypeError, ValueError) as error:
        raise SelectorBoundError("approved-ingestion envelope is invalid") from error
    dumped = envelope.model_dump(mode="json", by_alias=True)
    if compute_envelope_id(dumped) != envelope.envelope_id:
        raise SelectorBoundError("approved-ingestion envelope identity does not match")
    catalog = (root / DEFAULT_PACKAGED_CATALOG_PATH).read_bytes()
    fingerprint, file_digest, catalog_keys = bind_catalog_fingerprints(catalog)
    if (
        fingerprint != envelope.packaged_catalog_fingerprint
        or file_digest != envelope.catalog_content_digest
        or file_digest != envelope.catalog_tree_digest
        or catalog_keys != envelope.source_keys
        or sha256(canonical_json_bytes(list(catalog_keys))).hexdigest()
        != envelope.source_key_digest
    ):
        raise SelectorBoundError("approved-ingestion envelope does not match catalog")
    resources = read_repository_resources(root, DEFAULT_V7_POLICY_PATHS)
    v7 = bind_v7_policy_digests(
        policy_code=resources["policy_code"],
        policy_schema=resources["policy_schema"],
        policy_evidence=resources["policy_evidence"],
        policy_corpus=resources["policy_corpus"],
        public_selector=None,
    )
    if (
        v7.policy_code_sha256 != envelope.v7_policy_code_digest
        or v7.policy_schema_sha256 != envelope.v7_policy_schema_digest
        or v7.policy_evidence_sha256 != envelope.v7_policy_evidence_digest
        or v7.policy_corpus_sha256 != envelope.v7_policy_corpus_digest
    ):
        raise SelectorBoundError("approved-ingestion envelope does not match v7 policy")
    supplementary = sha256((root / _DECISION_SCHEMA_RELATIVE).read_bytes()).hexdigest()
    if supplementary != envelope.supplementary_policy_digest:
        raise SelectorBoundError(
            "approved-ingestion envelope does not match supplementary policy"
        )
    decision_payload = json.loads(
        (root / DEFAULT_DISCOVERY_OWNED_PATHS["decision"]).read_text(encoding="utf-8")
    )
    if (
        not isinstance(decision_payload, dict)
        or decision_payload.get("promotionDigest") != envelope.promotion_digest
    ):
        raise SelectorBoundError(
            "approved-ingestion envelope does not match promotion digest"
        )
    try:
        validate_envelope_keys(envelope.source_keys, key_classes=key_classes or {})
    except EnvelopeValidationError as error:
        raise SelectorBoundError(str(error)) from error
    frozen_source_ids = tuple(envelope.source_keys)
    return SelectorBoundScoutPin(
        envelope=envelope,
        frozen_source_ids=frozen_source_ids,
        checkout_sha=checkout_sha,
    )


def join_selector_bound_scout_observability(
    pin: SelectorBoundScoutPin,
    *,
    invocation_identity: str,
) -> ScoutObservabilityJoin:
    """Join conserved scout accounting for the already frozen selector pin."""

    if not invocation_identity:
        raise SelectorBoundError("invocation identity is required")
    envelope = pin.envelope
    planned_sources = pin.frozen_source_ids
    planned_routes = (_SCOUT_EVALUATION_ROUTE_ID,)
    planned_operations = (_SCOUT_EVALUATION_OPERATION_ID,)
    policy_digest = sha256(
        canonical_json_bytes(
            {
                "corpus": envelope.v7_policy_corpus_digest,
                "code": envelope.v7_policy_code_digest,
                "evidence": envelope.v7_policy_evidence_digest,
                "schema": envelope.v7_policy_schema_digest,
                "supplementary": envelope.supplementary_policy_digest,
            }
        )
    ).hexdigest()
    invocation_digest = sha256(
        canonical_json_bytes(
            {
                "checkoutSha": pin.checkout_sha,
                "envelopeId": envelope.envelope_id,
                "invocationIdentity": invocation_identity,
            }
        )
    ).hexdigest()
    evidence = ScoutRunEvidence(
        catalog_content_digest=envelope.catalog_content_digest,
        catalog_tree_digest=envelope.catalog_tree_digest,
        selector_digest=envelope.source_key_digest,
        policy_digest=policy_digest,
        promotion_digest=envelope.promotion_digest,
        invocation_digest=invocation_digest,
    )
    ledger = OperationLedger(planned_operation_ids=planned_operations)
    ledger.start(_SCOUT_EVALUATION_OPERATION_ID)
    ledger.finish(_SCOUT_EVALUATION_OPERATION_ID, outcome="succeeded")
    return join_scout_observability(
        source=build_uniform_source_accounting(
            planned_sources,
            disposition="unstarted",
            run_state="succeeded",
        ),
        route=build_route_accounting(
            planned_route_ids=planned_routes,
            outcomes=(
                RouteOutcome(
                    route_id=_SCOUT_EVALUATION_ROUTE_ID,
                    disposition="succeeded",
                    started=True,
                    authoritative=True,
                ),
            ),
            run_state="succeeded",
            freshness_context_digest=envelope.envelope_id,
        ),
        operations=ledger.close(channel_state="complete"),
        planned_source_ids=planned_sources,
        planned_route_ids=planned_routes,
        planned_operation_ids=planned_operations,
        run_state="succeeded",
        evidence=evidence,
    )


def attach_selector_bound_observability(
    payload: Mapping[str, object],
    *,
    pin: SelectorBoundScoutPin,
    invocation_identity: str,
) -> dict[str, object]:
    """Attach redacted observability counts and digests to CLI JSON."""

    joined = join_selector_bound_scout_observability(
        pin, invocation_identity=invocation_identity
    )
    attached = dict(payload)
    attached["checkoutSha"] = pin.checkout_sha
    attached["observability"] = {
        **joined.as_dict(),
        "envelopeId": pin.envelope.envelope_id,
    }
    return attached
