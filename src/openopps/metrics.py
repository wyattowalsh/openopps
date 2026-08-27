from __future__ import annotations

from collections.abc import Callable, Mapping
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

_http_retry_metrics: ContextVar[SyncMetrics | None] = ContextVar(
    "openopps_http_retry_metrics",
    default=None,
)

SOURCE_CONSERVATION_TERMINALS = (
    "succeeded",
    "failed",
    "timed_out",
    "fresh_skipped",
    "policy_blocked",
    "rate_limited",
    "cancelled",
    "unstarted",
)
ROUTE_CONSERVATION_TERMINALS = (
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


@dataclass(frozen=True)
class ProgressUpdate:
    stage: str
    message: str
    completed: int | None = None
    total: int | None = None


ProgressReporter = Callable[[ProgressUpdate], None]


def validate_conservation_counts(
    planned: int,
    terminals: Mapping[str, int],
    *,
    names: tuple[str, ...],
) -> None:
    """Require planned work to equal the sum of mutually exclusive terminals."""

    if (
        isinstance(planned, bool)
        or not isinstance(planned, int)
        or planned < 0
        or set(terminals) != set(names)
        or any(
            isinstance(count, bool) or not isinstance(count, int) or count < 0
            for count in terminals.values()
        )
        or sum(terminals[name] for name in names) != planned
    ):
        raise ValueError("planned denominator is not conserved")


def _conservation_payload(
    *,
    planned: int,
    terminals: Mapping[str, int],
    names: tuple[str, ...],
    extra: Mapping[str, bool | int] | None = None,
) -> dict[str, bool | int]:
    validate_conservation_counts(planned, terminals, names=names)
    payload: dict[str, bool | int] = {
        "planned": planned,
        "succeeded": terminals["succeeded"],
        "failed": terminals["failed"],
        "timedOut": terminals["timed_out"],
        "freshSkipped": terminals["fresh_skipped"],
        "policyBlocked": terminals["policy_blocked"],
        "rateLimited": terminals["rate_limited"],
        "cancelled": terminals["cancelled"],
        "unstarted": terminals["unstarted"],
    }
    if extra:
        payload.update(extra)
    return payload


def source_conservation_payload(
    *,
    planned: int,
    terminals: Mapping[str, int],
    terminal: bool,
    complete: bool,
) -> dict[str, bool | int]:
    return _conservation_payload(
        planned=planned,
        terminals=terminals,
        names=SOURCE_CONSERVATION_TERMINALS,
        extra={"complete": complete, "terminal": terminal},
    )


def route_conservation_payload(
    *,
    planned: int,
    terminals: Mapping[str, int],
    terminal: bool,
    complete: bool,
    authoritative_succeeded: int,
) -> dict[str, bool | int]:
    return _conservation_payload(
        planned=planned,
        terminals=terminals,
        names=ROUTE_CONSERVATION_TERMINALS,
        extra={
            "authoritativeSucceeded": authoritative_succeeded,
            "complete": complete,
            "deferred": terminals["deferred"],
            "duplicateSkipped": terminals["duplicate_skipped"],
            "missingMetadata": terminals["missing_metadata"],
            "terminal": terminal,
        },
    )


def empty_source_conservation() -> dict[str, bool | int]:
    zeros = {name: 0 for name in SOURCE_CONSERVATION_TERMINALS}
    return source_conservation_payload(
        planned=0,
        terminals=zeros,
        terminal=True,
        complete=False,
    )


def empty_route_conservation() -> dict[str, bool | int]:
    zeros = {name: 0 for name in ROUTE_CONSERVATION_TERMINALS}
    return route_conservation_payload(
        planned=0,
        terminals=zeros,
        terminal=True,
        complete=False,
        authoritative_succeeded=0,
    )


@dataclass
class SyncMetrics:
    name: str
    pages: int = 0
    boards: int = 0
    board_providers: int = 0
    jobs: int = 0
    jobs_persisted: int = 0
    job_sync_attempts: int = 0
    job_sync_runs: int = 0
    jobs_deduped: int = 0
    skipped: int = 0
    duplicate_routes_skipped: int = 0
    retries: int = 0
    provider_errors: dict[str, int] = field(default_factory=dict)
    provider_error_details: dict[str, dict[str, int]] = field(default_factory=dict)
    source_conservation: dict[str, bool | int] | None = None
    route_conservation: dict[str, bool | int] | None = None
    source_accounting: Any = None
    route_accounting: Any = None
    schema_version: int | None = None
    run_id: str | None = None
    attestation: str | None = None
    degraded_class: str | None = None
    evidence_digest: str | None = None
    started_at: float = field(default_factory=perf_counter)
    finished_at: float | None = None

    def finish(self) -> "SyncMetrics":
        self.finished_at = perf_counter()
        return self

    @property
    def elapsed_seconds(self) -> float:
        end = self.finished_at or perf_counter()
        return end - self.started_at

    @property
    def errors(self) -> dict[str, int]:
        return self.provider_errors

    def error(self, provider_id: str, reason: str = "error") -> None:
        self.provider_errors[provider_id] = self.provider_errors.get(provider_id, 0) + 1
        details = self.provider_error_details.setdefault(provider_id, {})
        details[reason] = details.get(reason, 0) + 1

    def as_dict(self) -> dict[str, Any]:
        elapsed = self.elapsed_seconds
        payload: dict[str, Any] = {
            "name": self.name,
            "pages": self.pages,
            "boards": self.boards,
            "boardProviders": self.board_providers,
            "jobs": self.jobs,
            "jobsPersisted": self.jobs_persisted,
            "jobSyncAttempts": self.job_sync_attempts,
            "jobSyncRuns": self.job_sync_runs,
            "jobsDeduped": self.jobs_deduped,
            "skipped": self.skipped,
            "duplicateRoutesSkipped": self.duplicate_routes_skipped,
            "retries": self.retries,
            "providerErrors": self.provider_errors,
            "providerErrorDetails": self.provider_error_details,
            "elapsedSeconds": elapsed,
            "boardsPerSecond": self.boards / elapsed if elapsed else 0,
            "jobsPerSecond": self.jobs / elapsed if elapsed else 0,
        }
        conservation: dict[str, dict[str, bool | int]] = {}
        if self.source_conservation is not None:
            conservation["sources"] = dict(self.source_conservation)
        if self.route_conservation is not None:
            conservation["routes"] = dict(self.route_conservation)
        if conservation:
            payload["conservation"] = conservation
        if self.attestation is not None:
            payload["schemaVersion"] = (
                1 if self.schema_version is None else self.schema_version
            )
            payload["runId"] = self.run_id
            payload["attestation"] = self.attestation
            payload["degradedClass"] = self.degraded_class
            payload["evidenceDigest"] = self.evidence_digest
        return payload


def combine_sync_metrics(name: str, *metrics: SyncMetrics) -> SyncMetrics:
    """Merge stage metrics; source and route conservation stay first-wins pins."""

    combined = SyncMetrics(name=name)
    for item in metrics:
        combined.pages += item.pages
        combined.boards += item.boards
        combined.board_providers += item.board_providers
        combined.jobs += item.jobs
        combined.jobs_persisted += item.jobs_persisted
        combined.job_sync_attempts += item.job_sync_attempts
        combined.job_sync_runs += item.job_sync_runs
        combined.jobs_deduped += item.jobs_deduped
        combined.skipped += item.skipped
        combined.duplicate_routes_skipped += item.duplicate_routes_skipped
        combined.retries += item.retries
        for provider_id, count in item.provider_errors.items():
            combined.provider_errors[provider_id] = (
                combined.provider_errors.get(provider_id, 0) + count
            )
        for provider_id, details in item.provider_error_details.items():
            combined_details = combined.provider_error_details.setdefault(
                provider_id, {}
            )
            for reason, count in details.items():
                combined_details[reason] = combined_details.get(reason, 0) + count
        if (
            combined.source_conservation is None
            and item.source_conservation is not None
        ):
            combined.source_conservation = dict(item.source_conservation)
        if combined.route_conservation is None and item.route_conservation is not None:
            combined.route_conservation = dict(item.route_conservation)
        if combined.source_accounting is None and item.source_accounting is not None:
            combined.source_accounting = item.source_accounting
        if combined.route_accounting is None and item.route_accounting is not None:
            combined.route_accounting = item.route_accounting
    if metrics:
        combined.started_at = min(item.started_at for item in metrics)
        combined.finished_at = max(
            item.finished_at or item.started_at for item in metrics
        )
        return combined
    return combined.finish()


def bind_http_retry_metrics(metrics: SyncMetrics | None) -> Token[SyncMetrics | None]:
    """Attach sync metrics for Tenacity HTTP retry accounting in the current context."""
    return _http_retry_metrics.set(metrics)


def reset_http_retry_metrics(token: Token[SyncMetrics | None]) -> None:
    _http_retry_metrics.reset(token)


def record_http_retry() -> None:
    metrics = _http_retry_metrics.get()
    if metrics is not None:
        metrics.retries += 1
