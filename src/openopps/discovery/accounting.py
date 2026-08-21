"""Exact source and pre-dedup route terminal accounting."""

from __future__ import annotations

from collections import Counter
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
