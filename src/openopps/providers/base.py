from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, overload

import httpx

from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    JobRecord,
    ProviderSupport,
    SourceRecord,
)


class ProviderKind(StrEnum):
    BOARD_SOURCE = "board_source"
    BOARD_PROVIDER = "board_provider"


@dataclass(frozen=True)
class ProviderRouteMatch:
    """Provider route fields parsed from a public hosted job-board URL."""

    token: str | None = None
    host: str | None = None
    tenant: str | None = None
    site: str | None = None


ProviderRouteDetector = Callable[[str], ProviderRouteMatch | None]


@dataclass(frozen=True)
class JobFetchResult(Sequence[JobRecord]):
    """Normalized jobs plus whether the fetch represents a complete snapshot."""

    jobs: list[JobRecord]
    authoritative: bool

    def __len__(self) -> int:
        return len(self.jobs)

    @overload
    def __getitem__(self, index: int) -> JobRecord: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[JobRecord]: ...

    def __getitem__(self, index: int | slice) -> JobRecord | Sequence[JobRecord]:
        return self.jobs[index]


@dataclass(frozen=True)
class ProviderDefinition:
    """Indexed source or job-provider capability exposed by OpenOpps or plugins."""

    id: str
    label: str
    kind: ProviderKind
    support_level: ProviderSupport
    description: str
    route_detector: ProviderRouteDetector | None = None

    @property
    def job_capable(self) -> bool:
        return (
            self.kind == ProviderKind.BOARD_PROVIDER
            and self.support_level == ProviderSupport.JOBS
        )

    @property
    def source_capable(self) -> bool:
        return self.kind == ProviderKind.BOARD_SOURCE


class BoardSourceAdapter(Protocol):
    provider_id: str

    def iter_boards(
        self,
        client: httpx.AsyncClient,
        source: SourceRecord,
        *,
        page_size: int,
    ) -> AsyncIterator[tuple[list[BoardRecord], list[BoardProviderRecord], dict]]: ...


class BoardJobProvider(Protocol):
    provider_id: str

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> JobFetchResult: ...

    async def check_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> int: ...
