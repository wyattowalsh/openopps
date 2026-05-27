from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any


@dataclass(frozen=True)
class ProgressUpdate:
    stage: str
    message: str
    completed: int | None = None
    total: int | None = None


ProgressReporter = Callable[[ProgressUpdate], None]


@dataclass
class SyncMetrics:
    name: str
    pages: int = 0
    boards: int = 0
    board_providers: int = 0
    jobs: int = 0
    jobs_persisted: int = 0
    job_sync_runs: int = 0
    jobs_deduped: int = 0
    skipped: int = 0
    duplicate_routes_skipped: int = 0
    retries: int = 0
    provider_errors: dict[str, int] = field(default_factory=dict)
    provider_error_details: dict[str, dict[str, int]] = field(default_factory=dict)
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
        return {
            "name": self.name,
            "pages": self.pages,
            "boards": self.boards,
            "boardProviders": self.board_providers,
            "jobs": self.jobs,
            "jobsPersisted": self.jobs_persisted,
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
