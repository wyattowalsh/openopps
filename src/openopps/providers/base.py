from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

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
class ProviderDefinition:
    id: str
    label: str
    kind: ProviderKind
    support_level: ProviderSupport
    description: str

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
    ) -> list[JobRecord]: ...

    async def check_jobs(
        self,
        client: httpx.AsyncClient,
        board: BoardRecord,
        route: BoardProviderRecord,
    ) -> int: ...
