from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from collections.abc import Callable
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
    skipped: int = 0
    duplicate_routes_skipped: int = 0
    retries: int = 0
    provider_errors: dict[str, int] = field(default_factory=dict)
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

    def error(self, provider_id: str) -> None:
        self.provider_errors[provider_id] = self.provider_errors.get(provider_id, 0) + 1

    def as_dict(self) -> dict[str, Any]:
        elapsed = self.elapsed_seconds
        return {
            "name": self.name,
            "pages": self.pages,
            "boards": self.boards,
            "boardProviders": self.board_providers,
            "jobs": self.jobs,
            "skipped": self.skipped,
            "duplicateRoutesSkipped": self.duplicate_routes_skipped,
            "retries": self.retries,
            "providerErrors": self.provider_errors,
            "elapsedSeconds": elapsed,
            "boardsPerSecond": self.boards / elapsed if elapsed else 0,
            "jobsPerSecond": self.jobs / elapsed if elapsed else 0,
        }
