"""Bounded O-lane metric catalog (O901–O906).

Scout, channel, candidate, evaluation, promotion, skill-handoff, source, and
route stages share one closed name set, closed reason/terminal dimensions, and
redacted payloads.  This module does not adopt a numeric SLO; the benchmark ADR
verdict remains ``defer``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal

from openopps.discovery.accounting import (
    OPERATION_TERMINALS,
    ROUTE_DISPOSITIONS,
    SOURCE_DISPOSITIONS,
    RouteAccounting,
    ScoutRunEvidence,
    SourceAccounting,
)
from openopps.discovery.diagnostics import (
    MAX_METRIC_ATTRIBUTES,
    render_metric_attributes,
)
from openopps.discovery.models import (
    BoundedReason,
    ChannelOperationAccounting,
    DiscoveryChannel,
    EvaluationDisposition,
)
from openopps.discovery.transport import OperationLedgerSnapshot


METRIC_CATALOG_SCHEMA: Final = "openopps.discovery.metric-catalog.v1"
METRIC_STAGES: Final[tuple[str, ...]] = (
    "scout",
    "channel",
    "candidate",
    "evaluation",
    "promotion",
    "skill_handoff",
    "source",
    "route",
)
METRIC_NAMES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "scout": "openopps.discovery.scout.operations",
        "channel": "openopps.discovery.channel.operations",
        "candidate": "openopps.discovery.candidate.occurrences",
        "evaluation": "openopps.discovery.evaluation.dispositions",
        "promotion": "openopps.discovery.promotion.previews",
        "skill_handoff": "openopps.discovery.skill.handoffs",
        "source": "openopps.discovery.source.terminals",
        "route": "openopps.discovery.route.terminals",
    }
)
TERMINAL_STATES: Final[frozenset[str]] = frozenset(
    {"complete", "partial", "failed", "cancelled", "aborted", "nonterminal"}
)
EVIDENCE_CLASSES: Final[tuple[str, ...]] = (
    "fetched",
    "not_modified",
    "reused",
    "blocked",
    "rate_limited",
    "partial",
    "complete",
)
OBSERVATION_EVIDENCE_CLASSES: Final[tuple[str, ...]] = EVIDENCE_CLASSES[:-1]
CANDIDATE_TERMINALS: Final[tuple[str, ...]] = (
    "admitted",
    "duplicate",
    "invalid",
    "unstarted",
)
EVALUATION_TERMINALS: Final[tuple[str, ...]] = tuple(
    item.value for item in EvaluationDisposition
)
PROMOTION_TERMINALS: Final[tuple[str, ...]] = (
    "identity_closed",
    "proposed",
    "blocked",
    "unstarted",
)
SKILL_HANDOFF_TERMINALS: Final[tuple[str, ...]] = (
    "projected",
    "skipped",
    "blocked",
    "unstarted",
)
STAGE_TERMINALS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "scout": OPERATION_TERMINALS,
        "channel": OPERATION_TERMINALS,
        "candidate": CANDIDATE_TERMINALS,
        "evaluation": EVALUATION_TERMINALS,
        "promotion": PROMOTION_TERMINALS,
        "skill_handoff": SKILL_HANDOFF_TERMINALS,
        "source": SOURCE_DISPOSITIONS,
        "route": ROUTE_DISPOSITIONS,
    }
)
REASON_CODES: Final[frozenset[str]] = frozenset(item.value for item in BoundedReason)
_SHA256_LEN: Final = 64
_FORBIDDEN_PAYLOAD_MARKERS: Final[tuple[str, ...]] = (
    "http://",
    "https://",
    "unaccounted",
    "authorization",
    "bearer ",
    "cookie:",
    "token=",
)
_TERMINAL_REASONS: Final[Mapping[str, BoundedReason]] = MappingProxyType(
    {
        "admitted": BoundedReason.NONE,
        "already_approved": BoundedReason.NONE,
        "blocked": BoundedReason.POLICY_UNRESOLVED,
        "cancelled": BoundedReason.EVIDENCE_INCOMPLETE,
        "deferred": BoundedReason.EVIDENCE_STALE,
        "duplicate": BoundedReason.COLLISION_UNRESOLVED,
        "duplicate_skipped": BoundedReason.NONE,
        "failed": BoundedReason.TRANSPORT_REJECTED,
        "fresh_skipped": BoundedReason.NONE,
        "identity_closed": BoundedReason.NONE,
        "inconclusive": BoundedReason.EVIDENCE_INCOMPLETE,
        "invalid": BoundedReason.CONTENT_REJECTED,
        "missing_metadata": BoundedReason.EVIDENCE_INCOMPLETE,
        "policy_blocked": BoundedReason.POLICY_UNRESOLVED,
        "projected": BoundedReason.NONE,
        "promotable": BoundedReason.NONE,
        "proposed": BoundedReason.NONE,
        "rate_limited": BoundedReason.RATE_LIMITED,
        "skipped": BoundedReason.NONE,
        "succeeded": BoundedReason.NONE,
        "timed_out": BoundedReason.TIMED_OUT,
        "unstarted": BoundedReason.EVIDENCE_INCOMPLETE,
        "unsupported": BoundedReason.UNSUPPORTED_ROUTE,
    }
)
TransportStateName = Literal[
    "response",
    "network_unreachable",
    "security_rejected_redirect",
    "verified_cache",
    "not_modified",
    "missing",
]
RequestOutcomeName = Literal[
    "succeeded",
    "blocked",
    "rate_limited",
    "timed_out",
    "failed",
    "cancelled",
]


class ObservabilityError(ValueError):
    """Raised when a metric catalog payload would escape its bounded contract."""


@dataclass(frozen=True, slots=True)
class MetricSeries:
    """One named instrument sample with conserved terminals and closed labels."""

    name: str
    stage: str
    planned: int
    terminals: Mapping[str, int]
    reasons: Mapping[str, int]
    evidence: Mapping[str, int]
    attributes: Mapping[str, bool | str]

    def as_dict(self) -> dict[str, object]:
        names = STAGE_TERMINALS[self.stage]
        return {
            "attributes": dict(self.attributes),
            "evidence": {name: self.evidence[name] for name in EVIDENCE_CLASSES},
            "name": self.name,
            "planned": self.planned,
            "reasons": {name: self.reasons[name] for name in sorted(self.reasons)},
            "stage": self.stage,
            "terminals": {name: self.terminals[name] for name in names},
        }


@dataclass(frozen=True, slots=True)
class MetricCatalogReport:
    """Whole-run catalog: eight stage names, digest correlation, no raw URLs."""

    schema_version: str
    digests: Mapping[str, str]
    metrics: tuple[MetricSeries, ...]

    def as_dict(self) -> dict[str, object]:
        payload = {
            "digests": dict(self.digests),
            "metrics": [item.as_dict() for item in self.metrics],
            "schemaVersion": self.schema_version,
        }
        assert_bounded_metric_payload(payload)
        return payload


def metric_name(stage: str) -> str:
    """Return the closed instrument name for a catalog stage."""

    if stage not in METRIC_NAMES:
        raise ObservabilityError("metric stage is unsupported")
    return METRIC_NAMES[stage]


def classify_evidence_class(
    *,
    request_outcome: RequestOutcomeName | None = None,
    transport_state: TransportStateName | None = None,
    reused: bool = False,
    grain_complete: bool = False,
) -> str:
    """Map bounded transport/request facts onto one evidence class (O906)."""

    if request_outcome == "rate_limited":
        return "rate_limited"
    if request_outcome == "blocked":
        return "blocked"
    if reused or transport_state == "verified_cache":
        return "reused"
    if transport_state == "not_modified":
        return "not_modified"
    if request_outcome in {"failed", "timed_out", "cancelled"} or transport_state in {
        "missing",
        "network_unreachable",
        "security_rejected_redirect",
    }:
        return "partial"
    if request_outcome in {None, "succeeded"}:
        return "complete" if grain_complete else "fetched"
    raise ObservabilityError("evidence class is unsupported")


def assert_bounded_metric_payload(payload: object) -> None:
    """Reject URLs, queries, secrets, payload fragments, and arbitrary labels."""

    rendered = _walk(payload).lower()
    if any(marker in rendered for marker in _FORBIDDEN_PAYLOAD_MARKERS):
        raise ObservabilityError("metric payload contains a forbidden token")
    _assert_payload_shape(payload)


def build_metric_catalog_report(
    *,
    evidence: ScoutRunEvidence,
    manifest_digest: str,
    scout: OperationLedgerSnapshot | None = None,
    channels: Sequence[ChannelOperationAccounting] = (),
    candidates: Mapping[str, int] | None = None,
    evaluations: Mapping[str, int] | None = None,
    promotion: Mapping[str, int] | None = None,
    skill_handoff: Mapping[str, int] | None = None,
    source: SourceAccounting | None = None,
    route: RouteAccounting | None = None,
    run_state: str = "succeeded",
) -> MetricCatalogReport:
    """Emit conserved totals and reason distributions per channel and run."""

    digests = _digest_correlation(evidence, manifest_digest)
    series: list[MetricSeries] = [
        _operation_series(
            stage="scout",
            terminals=_operation_terminal_map(scout),
            channel=None,
            run_state=run_state,
            identity_digest=evidence.invocation_digest,
        )
    ]
    seen_channels: set[str] = set()
    for accounting in channels:
        if accounting.channel in seen_channels:
            raise ObservabilityError("channel metric was emitted twice")
        seen_channels.add(accounting.channel)
        series.append(
            _channel_series(
                accounting,
                run_state=run_state,
                identity_digest=evidence.invocation_digest,
            )
        )
    for channel in DiscoveryChannel:
        if channel.value in seen_channels:
            continue
        series.append(
            _empty_series(
                stage="channel",
                channel=channel,
                identity_digest=evidence.invocation_digest,
            )
        )
    series.append(
        _count_series(
            stage="candidate",
            terminals=_count_map(candidates, CANDIDATE_TERMINALS),
            run_state=run_state,
            identity_digest=evidence.invocation_digest,
        )
    )
    series.append(
        _count_series(
            stage="evaluation",
            terminals=_count_map(evaluations, EVALUATION_TERMINALS),
            run_state=run_state,
            identity_digest=evidence.invocation_digest,
        )
    )
    series.append(
        _count_series(
            stage="promotion",
            terminals=_count_map(promotion, PROMOTION_TERMINALS),
            run_state=run_state,
            identity_digest=evidence.invocation_digest,
        )
    )
    series.append(
        _count_series(
            stage="skill_handoff",
            terminals=_count_map(skill_handoff, SKILL_HANDOFF_TERMINALS),
            run_state=run_state,
            identity_digest=evidence.invocation_digest,
        )
    )
    series.append(
        _source_series(
            source,
            run_state=run_state,
            identity_digest=evidence.invocation_digest,
        )
    )
    series.append(
        _route_series(
            route,
            run_state=run_state,
            identity_digest=evidence.invocation_digest,
        )
    )
    names = {item.name for item in series}
    if names != set(METRIC_NAMES.values()):
        raise ObservabilityError("metric catalog names are not closed")
    report = MetricCatalogReport(
        schema_version=METRIC_CATALOG_SCHEMA,
        digests=digests,
        metrics=tuple(series),
    )
    assert_bounded_metric_payload(report.as_dict())
    return report


def _digest_correlation(
    evidence: ScoutRunEvidence, manifest_digest: str
) -> Mapping[str, str]:
    if len(manifest_digest) != _SHA256_LEN or any(
        char not in "0123456789abcdef" for char in manifest_digest
    ):
        raise ObservabilityError("digest identity must be canonical SHA-256")
    return MappingProxyType(
        {
            "catalogSha256": evidence.catalog_content_digest,
            "catalogTreeSha256": evidence.catalog_tree_digest,
            "manifestSha256": manifest_digest,
            "policySha256": evidence.policy_digest,
            "promotionSha256": evidence.promotion_digest,
            "selectorSha256": evidence.selector_digest,
        }
    )


def _operation_terminal_map(
    snapshot: OperationLedgerSnapshot | None,
) -> dict[str, int]:
    if snapshot is None:
        return {name: 0 for name in OPERATION_TERMINALS}
    return {name: snapshot.terminals[name] for name in OPERATION_TERMINALS}


def _count_map(
    values: Mapping[str, int] | None, names: tuple[str, ...]
) -> dict[str, int]:
    counts = {name: 0 for name in names}
    if not values:
        return counts
    if set(values) - set(names):
        raise ObservabilityError("metric terminal label is unsupported")
    for name, count in values.items():
        _require_count(count)
        counts[name] = count
    return counts


def _source_series(
    source: SourceAccounting | None,
    *,
    run_state: str,
    identity_digest: str,
) -> MetricSeries:
    if source is None:
        terminals = {name: 0 for name in SOURCE_DISPOSITIONS}
        complete = False
    else:
        terminals = {name: getattr(source, name) for name in SOURCE_DISPOSITIONS}
        if source.planned != sum(terminals.values()):
            raise ObservabilityError("source accounting is not conserved")
        complete = source.complete
    return _finish_series(
        stage="source",
        terminals=terminals,
        channel=None,
        run_state=run_state,
        identity_digest=identity_digest,
        grain_complete=complete,
    )


def _route_series(
    route: RouteAccounting | None,
    *,
    run_state: str,
    identity_digest: str,
) -> MetricSeries:
    if route is None:
        terminals = {name: 0 for name in ROUTE_DISPOSITIONS}
        complete = False
    else:
        terminals = {name: getattr(route, name) for name in ROUTE_DISPOSITIONS}
        if route.planned != sum(terminals.values()):
            raise ObservabilityError("route accounting is not conserved")
        complete = route.complete
    return _finish_series(
        stage="route",
        terminals=terminals,
        channel=None,
        run_state=run_state,
        identity_digest=identity_digest,
        grain_complete=complete,
    )


def _channel_series(
    accounting: ChannelOperationAccounting,
    *,
    run_state: str,
    identity_digest: str,
) -> MetricSeries:
    terminals = {
        "blocked": accounting.blocked,
        "cancelled": accounting.cancelled,
        "failed": accounting.failed,
        "rate_limited": accounting.rate_limited,
        "succeeded": accounting.succeeded,
        "timed_out": accounting.timed_out,
        "unstarted": accounting.unstarted,
    }
    if accounting.planned_operations != sum(terminals.values()):
        raise ObservabilityError("channel accounting is not conserved")
    return _finish_series(
        stage="channel",
        terminals=terminals,
        channel=DiscoveryChannel(accounting.channel),
        run_state=run_state,
        identity_digest=identity_digest,
        grain_complete=accounting.channel_state == "complete",
        channel_state=accounting.channel_state,
    )


def _operation_series(
    *,
    stage: str,
    terminals: Mapping[str, int],
    channel: DiscoveryChannel | None,
    run_state: str,
    identity_digest: str,
) -> MetricSeries:
    return _finish_series(
        stage=stage,
        terminals=dict(terminals),
        channel=channel,
        run_state=run_state,
        identity_digest=identity_digest,
        grain_complete=_terminals_complete(terminals),
    )


def _count_series(
    *,
    stage: str,
    terminals: Mapping[str, int],
    run_state: str,
    identity_digest: str,
) -> MetricSeries:
    return _finish_series(
        stage=stage,
        terminals=dict(terminals),
        channel=None,
        run_state=run_state,
        identity_digest=identity_digest,
        grain_complete=_count_stage_complete(stage, terminals),
    )


def _empty_series(
    *,
    stage: str,
    channel: DiscoveryChannel | None,
    identity_digest: str,
) -> MetricSeries:
    return _finish_series(
        stage=stage,
        terminals={name: 0 for name in STAGE_TERMINALS[stage]},
        channel=channel,
        run_state="succeeded",
        identity_digest=identity_digest,
        grain_complete=False,
    )


def _finish_series(
    *,
    stage: str,
    terminals: dict[str, int],
    channel: DiscoveryChannel | None,
    run_state: str,
    identity_digest: str,
    grain_complete: bool,
    channel_state: str | None = None,
) -> MetricSeries:
    names = STAGE_TERMINALS[stage]
    if set(terminals) != set(names):
        raise ObservabilityError("metric terminal label is unsupported")
    for count in terminals.values():
        _require_count(count)
    planned = sum(terminals[name] for name in names)
    reasons = _reason_distribution(terminals)
    if sum(reasons.values()) != planned:
        raise ObservabilityError("reason distribution is not conserved")
    evidence = _evidence_distribution(terminals, grain_complete=grain_complete)
    state, reason, complete = _metric_state(
        planned=planned,
        terminals=terminals,
        grain_complete=grain_complete,
        run_state=run_state,
        channel_state=channel_state,
    )
    attributes = render_metric_attributes(
        channel=channel,
        terminal_state=state,
        reason_code=reason,
        complete=complete,
        identity_digest=identity_digest,
    )
    if len(attributes) > MAX_METRIC_ATTRIBUTES:
        raise ObservabilityError("metric attribute set exceeds its limit")
    return MetricSeries(
        name=metric_name(stage),
        stage=stage,
        planned=planned,
        terminals=MappingProxyType(dict(terminals)),
        reasons=MappingProxyType(reasons),
        evidence=MappingProxyType(evidence),
        attributes=attributes,
    )


def _reason_distribution(terminals: Mapping[str, int]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for name, count in terminals.items():
        reason = _TERMINAL_REASONS.get(name)
        if reason is None:
            raise ObservabilityError("metric terminal label is unsupported")
        counts[reason.value] += count
    if set(counts) - REASON_CODES:
        raise ObservabilityError("metric reason is unsupported")
    return dict(sorted(counts.items()))


def _evidence_distribution(
    terminals: Mapping[str, int], *, grain_complete: bool
) -> dict[str, int]:
    counts = {name: 0 for name in EVIDENCE_CLASSES}
    for name, count in terminals.items():
        evidence_class = _evidence_for_terminal(name, grain_complete=grain_complete)
        counts[evidence_class] += count
    observed = sum(counts[name] for name in OBSERVATION_EVIDENCE_CLASSES)
    if observed + counts["complete"] != sum(terminals.values()):
        raise ObservabilityError("evidence distribution is not conserved")
    return counts


def _evidence_for_terminal(name: str, *, grain_complete: bool) -> str:
    if name == "rate_limited":
        return "rate_limited"
    if name in {"blocked", "policy_blocked"}:
        return "blocked"
    if name in {"fresh_skipped", "skipped"}:
        return "reused"
    if name in {
        "failed",
        "timed_out",
        "cancelled",
        "unstarted",
        "deferred",
        "missing_metadata",
        "invalid",
        "inconclusive",
        "unsupported",
    }:
        return "partial"
    if name in {
        "succeeded",
        "admitted",
        "promotable",
        "already_approved",
        "identity_closed",
        "proposed",
        "projected",
        "duplicate",
        "duplicate_skipped",
    }:
        return "complete" if grain_complete else "fetched"
    raise ObservabilityError("evidence class is unsupported")


def _metric_state(
    *,
    planned: int,
    terminals: Mapping[str, int],
    grain_complete: bool,
    run_state: str,
    channel_state: str | None,
) -> tuple[
    Literal["complete", "partial", "failed", "cancelled", "aborted", "nonterminal"],
    BoundedReason,
    bool,
]:
    if planned == 0:
        return "nonterminal", BoundedReason.NONE, False
    if grain_complete:
        return "complete", BoundedReason.NONE, True
    if run_state == "aborted":
        return "aborted", BoundedReason.EVIDENCE_INCOMPLETE, False
    if (channel_state or "") == "cancelled" or terminals.get("cancelled", 0):
        return "cancelled", BoundedReason.EVIDENCE_INCOMPLETE, False
    if terminals.get("failed", 0) or terminals.get("timed_out", 0):
        return "failed", _dominant_reason(terminals), False
    return "partial", _dominant_reason(terminals), False


def _dominant_reason(terminals: Mapping[str, int]) -> BoundedReason:
    for name in (
        "rate_limited",
        "timed_out",
        "failed",
        "policy_blocked",
        "blocked",
        "cancelled",
        "unstarted",
        "invalid",
        "inconclusive",
        "unsupported",
        "deferred",
        "missing_metadata",
    ):
        if terminals.get(name, 0):
            return _TERMINAL_REASONS[name]
    return BoundedReason.EVIDENCE_INCOMPLETE


def _terminals_complete(terminals: Mapping[str, int]) -> bool:
    planned = sum(terminals.values())
    return planned > 0 and terminals.get("succeeded", 0) == planned


def _count_stage_complete(stage: str, terminals: Mapping[str, int]) -> bool:
    planned = sum(terminals.values())
    if planned == 0:
        return False
    success = {
        "candidate": {"admitted"},
        "evaluation": {"already_approved", "promotable"},
        "promotion": {"identity_closed", "proposed"},
        "skill_handoff": {"projected", "skipped"},
    }[stage]
    return sum(terminals[name] for name in success) == planned


def _require_count(count: int) -> None:
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ObservabilityError("metric count must be a non-negative integer")


def _walk(value: object) -> str:
    if isinstance(value, Mapping):
        return " ".join(f"{key} {_walk(item)}" for key, item in value.items())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return " ".join(_walk(item) for item in value)
    return str(value)


def _assert_payload_shape(payload: object) -> None:
    if not isinstance(payload, Mapping):
        raise ObservabilityError("metric payload must be a mapping")
    metrics = payload.get("metrics")
    if not isinstance(metrics, Sequence) or isinstance(metrics, (str, bytes)):
        raise ObservabilityError("metric catalog is missing series")
    names: set[str] = set()
    for item in metrics:
        if not isinstance(item, Mapping):
            raise ObservabilityError("metric series must be a mapping")
        name = item.get("name")
        stage = item.get("stage")
        if not isinstance(name, str) or name not in METRIC_NAMES.values():
            raise ObservabilityError("metric name is unsupported")
        if not isinstance(stage, str) or METRIC_NAMES.get(stage) != name:
            raise ObservabilityError("metric stage is unsupported")
        names.add(name)
        attributes = item.get("attributes")
        if not isinstance(attributes, Mapping):
            raise ObservabilityError("metric attributes must be a mapping")
        if len(attributes) > MAX_METRIC_ATTRIBUTES:
            raise ObservabilityError("metric attribute set exceeds its limit")
        reasons = item.get("reasons")
        if not isinstance(reasons, Mapping) or any(
            key not in REASON_CODES for key in reasons
        ):
            raise ObservabilityError("metric reason is unsupported")
        evidence_map = item.get("evidence")
        if not isinstance(evidence_map, Mapping) or set(evidence_map) != set(
            EVIDENCE_CLASSES
        ):
            raise ObservabilityError("evidence class is unsupported")
    if names != set(METRIC_NAMES.values()):
        raise ObservabilityError("metric catalog names are not closed")
