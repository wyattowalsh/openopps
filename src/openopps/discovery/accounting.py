"""Exact source and pre-dedup route terminal accounting."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
import re

from openopps.discovery.models import RouteOutcome, SourceOutcome


SOURCE_DISPOSITIONS = (
    "succeeded",
    "failed",
    "timed_out",
    "fresh_skipped",
    "policy_blocked",
    "rate_limited",
    "cancelled",
    "unstarted",
)
ROUTE_DISPOSITIONS = (
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
)
TERMINAL_RUN_STATES = frozenset(
    {"succeeded", "failed", "partial", "aborted", "cancelled"}
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class SourceAccounting:
    planned: int
    succeeded: int
    failed: int
    timed_out: int
    fresh_skipped: int
    policy_blocked: int
    rate_limited: int
    cancelled: int
    unstarted: int
    terminal: bool
    complete: bool
    unaccounted_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RouteAccounting:
    planned: int
    succeeded: int
    failed: int
    timed_out: int
    fresh_skipped: int
    deferred: int
    duplicate_skipped: int
    missing_metadata: int
    policy_blocked: int
    rate_limited: int
    cancelled: int
    unstarted: int
    authoritative_succeeded: int
    terminal: bool
    complete: bool
    unaccounted_ids: tuple[str, ...]


def _planned_ids(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    if any(not value for value in values) or len(set(values)) != len(values):
        raise ValueError(f"planned {label} IDs must be non-empty and unique")
    return values


def _validate_outcome_closure(
    *,
    planned: tuple[str, ...],
    observed: tuple[str, ...],
    run_state: str,
    label: str,
) -> tuple[bool, tuple[str, ...]]:
    if len(set(observed)) != len(observed):
        raise ValueError(f"duplicate {label} terminal outcomes")
    unexpected = set(observed) - set(planned)
    if unexpected:
        raise ValueError(f"unexpected {label} terminal outcomes")
    missing = tuple(value for value in planned if value not in set(observed))
    terminal = run_state in TERMINAL_RUN_STATES
    if run_state != "nonterminal" and not terminal:
        raise ValueError("run_state is unsupported")
    if terminal and missing:
        raise ValueError(f"terminal {label} run has an unaccounted planned item")
    return terminal, missing


def build_source_accounting(
    *,
    planned_source_ids: tuple[str, ...],
    outcomes: tuple[SourceOutcome, ...],
    run_state: str,
    freshness_context_digest: str,
) -> SourceAccounting:
    if _SHA256_RE.fullmatch(freshness_context_digest) is None:
        raise ValueError("freshness context digest must be canonical sha256")
    planned = _planned_ids(planned_source_ids, "source")
    terminal, missing = _validate_outcome_closure(
        planned=planned,
        observed=tuple(outcome.source_id for outcome in outcomes),
        run_state=run_state,
        label="source",
    )
    for outcome in outcomes:
        if outcome.disposition == "fresh_skipped" and (
            not outcome.authoritative
            or outcome.freshness_context_digest != freshness_context_digest
        ):
            raise ValueError("source freshness context is not authoritative")
    counts = Counter(outcome.disposition for outcome in outcomes)
    bad = {
        "failed",
        "timed_out",
        "policy_blocked",
        "rate_limited",
        "cancelled",
        "unstarted",
    }
    complete = (
        terminal
        and run_state == "succeeded"
        and not missing
        and not any(outcome.disposition in bad for outcome in outcomes)
        and all(
            outcome.authoritative
            for outcome in outcomes
            if outcome.disposition in {"succeeded", "fresh_skipped"}
        )
    )
    return SourceAccounting(
        planned=len(planned),
        **{name: counts[name] for name in SOURCE_DISPOSITIONS},
        terminal=terminal,
        complete=complete,
        unaccounted_ids=missing,
    )


def build_route_accounting(
    *,
    planned_route_ids: tuple[str, ...],
    outcomes: tuple[RouteOutcome, ...],
    run_state: str,
    freshness_context_digest: str,
) -> RouteAccounting:
    if _SHA256_RE.fullmatch(freshness_context_digest) is None:
        raise ValueError("freshness context digest must be canonical sha256")
    planned = _planned_ids(planned_route_ids, "route")
    terminal, missing = _validate_outcome_closure(
        planned=planned,
        observed=tuple(outcome.route_id for outcome in outcomes),
        run_state=run_state,
        label="route",
    )
    by_id = {outcome.route_id: outcome for outcome in outcomes}
    for outcome in outcomes:
        if outcome.disposition == "fresh_skipped" and (
            not outcome.authoritative
            or outcome.freshness_context_digest != freshness_context_digest
        ):
            raise ValueError("route freshness context is not authoritative")
        if outcome.disposition == "duplicate_skipped":
            representative = by_id.get(outcome.representative_id or "")
            if (
                representative is None
                or representative.disposition not in {"succeeded", "fresh_skipped"}
                or not representative.authoritative
            ):
                raise ValueError(
                    "duplicate representative is missing, skipped, or non-authoritative"
                )
            if representative.disposition == "fresh_skipped" and (
                representative.freshness_context_digest != freshness_context_digest
            ):
                raise ValueError("representative freshness context does not match")
    counts = Counter(outcome.disposition for outcome in outcomes)
    authoritative_succeeded = sum(
        outcome.disposition == "succeeded" and outcome.authoritative
        for outcome in outcomes
    )
    bad = {
        "failed",
        "timed_out",
        "deferred",
        "missing_metadata",
        "policy_blocked",
        "rate_limited",
        "cancelled",
        "unstarted",
    }
    complete = (
        terminal
        and run_state == "succeeded"
        and not missing
        and not any(outcome.disposition in bad for outcome in outcomes)
        and all(
            outcome.authoritative
            for outcome in outcomes
            if outcome.disposition in {"succeeded", "fresh_skipped"}
        )
    )
    return RouteAccounting(
        planned=len(planned),
        **{name: counts[name] for name in ROUTE_DISPOSITIONS},
        authoritative_succeeded=authoritative_succeeded,
        terminal=terminal,
        complete=complete,
        unaccounted_ids=missing,
    )


OPERATION_TERMINALS = (
    "blocked",
    "cancelled",
    "failed",
    "rate_limited",
    "succeeded",
    "timed_out",
    "unstarted",
)
TYPED_DEGRADED_CLASSES = (
    "failed",
    "timed_out",
    "policy_blocked",
    "rate_limited",
    "cancelled",
    "unstarted",
    "missing_metadata",
    "deferred",
    "partial",
    "nonterminal",
)
_COUNT_DEGRADED_CLASSES = (
    "failed",
    "timed_out",
    "policy_blocked",
    "rate_limited",
    "cancelled",
    "unstarted",
    "missing_metadata",
    "deferred",
)
_OPERATION_DEGRADED = {
    "blocked": "policy_blocked",
    "cancelled": "cancelled",
    "failed": "failed",
    "rate_limited": "rate_limited",
    "timed_out": "timed_out",
    "unstarted": "unstarted",
}
_RUN_STATE_DEGRADED = {
    "aborted": "partial",
    "cancelled": "cancelled",
    "failed": "failed",
    "nonterminal": "nonterminal",
    "partial": "partial",
}


@dataclass(frozen=True, slots=True)
class ScoutRunEvidence:
    catalog_content_digest: str
    catalog_tree_digest: str
    selector_digest: str
    policy_digest: str
    promotion_digest: str
    invocation_digest: str

    def __post_init__(self) -> None:
        for digest in (
            self.catalog_content_digest,
            self.catalog_tree_digest,
            self.selector_digest,
            self.policy_digest,
            self.promotion_digest,
            self.invocation_digest,
        ):
            if _SHA256_RE.fullmatch(digest) is None:
                raise ValueError("run evidence digest must be canonical sha256")

    def as_dict(self) -> dict[str, str]:
        return {
            "catalogContentDigest": self.catalog_content_digest,
            "catalogTreeDigest": self.catalog_tree_digest,
            "invocationDigest": self.invocation_digest,
            "policyDigest": self.policy_digest,
            "promotionDigest": self.promotion_digest,
            "selectorDigest": self.selector_digest,
        }


def validate_operation_conservation(
    planned: int, terminals: Mapping[str, int]
) -> None:
    if (
        isinstance(planned, bool)
        or not isinstance(planned, int)
        or planned < 1
        or set(terminals) != set(OPERATION_TERMINALS)
        or any(
            isinstance(count, bool) or not isinstance(count, int) or count < 0
            for count in terminals.values()
        )
        or sum(terminals[name] for name in OPERATION_TERMINALS) != planned
    ):
        raise ValueError("planned operation denominator is not conserved")


def _operations_all_succeeded(terminals: Mapping[str, int]) -> bool:
    succeeded = terminals.get("succeeded", 0)
    if isinstance(succeeded, bool) or not isinstance(succeeded, int) or succeeded <= 0:
        return False
    return not any(
        terminals.get(name, 0)
        for name in OPERATION_TERMINALS
        if name != "succeeded"
    )


def classify_typed_degraded(
    *,
    source: SourceAccounting,
    route: RouteAccounting,
    operation_terminals: Mapping[str, int],
    operation_channel_state: str,
    run_state: str,
) -> tuple[str, str | None]:
    if (source.complete or route.complete) and run_state != "succeeded":
        raise ValueError(
            "complete source or route accounting cannot pair with a non-succeeded run"
        )
    if (
        source.complete
        and route.complete
        and _operations_all_succeeded(operation_terminals)
        and operation_channel_state == "complete"
        and run_state == "succeeded"
    ):
        return "complete", None

    present: list[str] = []
    for name in _COUNT_DEGRADED_CLASSES:
        source_count = getattr(source, name, 0)
        route_count = getattr(route, name, 0)
        if source_count or route_count:
            present.append(name)
    for outcome, mapped in _OPERATION_DEGRADED.items():
        if operation_terminals.get(outcome, 0) and mapped not in present:
            present.append(mapped)
    if run_state == "nonterminal" and "nonterminal" not in present:
        present.append("nonterminal")

    if len(present) == 1:
        degraded_class = present[0]
    elif len(present) > 1:
        degraded_class = "nonterminal" if "nonterminal" in present else "partial"
    else:
        degraded_class = _RUN_STATE_DEGRADED.get(run_state, "partial")
    if degraded_class not in TYPED_DEGRADED_CLASSES:
        raise ValueError("degraded class must be explicitly typed")
    return "degraded", degraded_class


def build_uniform_source_accounting(
    planned_source_ids: tuple[str, ...],
    *,
    disposition: str,
    run_state: str,
) -> SourceAccounting:
    """Account every pinned source as the same terminal class without per-id models."""

    planned = _planned_ids(planned_source_ids, "source")
    if disposition not in SOURCE_DISPOSITIONS:
        raise ValueError("source disposition is not a terminal class")
    if run_state not in TERMINAL_RUN_STATES and run_state != "nonterminal":
        raise ValueError("run state is not a known terminal class")
    count = len(planned)
    counts = {name: 0 for name in SOURCE_DISPOSITIONS}
    counts[disposition] = count
    complete = run_state == "succeeded" and disposition in {
        "succeeded",
        "fresh_skipped",
    }
    return SourceAccounting(
        planned=count,
        succeeded=counts["succeeded"],
        failed=counts["failed"],
        timed_out=counts["timed_out"],
        fresh_skipped=counts["fresh_skipped"],
        policy_blocked=counts["policy_blocked"],
        rate_limited=counts["rate_limited"],
        cancelled=counts["cancelled"],
        unstarted=counts["unstarted"],
        terminal=True,
        complete=complete,
        unaccounted_ids=(),
    )
